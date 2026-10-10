"""Green Home Score engine: S = Σ w_k · s_k with the PS2-fixed weights.

A pure function of resolved inputs. No I/O, no randomness, no model calls.

Missing data is handled without guessing:
- every component valued from observed data              → status "complete";
- some values are documented defaults or model estimates → status "provisional"
  (a point score, with those components marked);
- a component cannot be valued at all                    → status "partial": we report
  the *range* the score could take (missing sub-scores at 0 and at 100) and a band
  only if the whole range sits inside one band.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

from .config import score_mappings as M
from .contract import Basis, Receipt, Resolved

SCORE_METHOD = "Weighted sum of 7 sub-scores (PS2 fixed weights); round half up; PS2 bands"


class ComponentScore(BaseModel):
    key: str
    label: str
    weight: float
    sub_score: float | None
    contribution: float | None
    points_available: float | None
    basis: Basis
    input_display: str
    explanation: str
    improved_by: list[str]
    receipt: Receipt


class Issue(BaseModel):
    component: str
    label: str
    sub_score: float
    points_available: float
    text: str
    improved_by: list[str]


class ScoreResult(BaseModel):
    status: Literal["complete", "provisional", "partial"]
    score: int | None
    raw_score: float | None
    band: str | None
    score_range: tuple[int, int] | None = None
    is_poor: bool | None
    components: list[ComponentScore]
    missing_components: list[str]
    estimated_components: list[str]
    issues: list[Issue]
    receipt: Receipt


# ---------------------------------------------------------------------------------------
# Primitive, individually testable mappings
# ---------------------------------------------------------------------------------------

def round_half_up(x: float) -> int:
    """Round to the nearest integer, halves upwards (64.5 → 65). Python's round() would give 64."""
    return int(math.floor(round(x, 9) + 0.5))


def interpolate(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation through ``knots``, clamped at both ends."""
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def ladder_score(ladder: list[tuple[str, float]], value: str) -> float:
    return dict(ladder)[value]


def band_for(score: int) -> str:
    for lo, hi, label in M.BANDS:
        if lo <= score <= hi:
            return label
    raise ValueError(f"score out of range: {score}")


def sap_to_band(sap: float) -> str:
    for threshold, band in M.SAP_BANDS:
        if sap >= threshold:
            return band
    return "G"


def efficiency_subscore(sap: float) -> float:
    return max(0.0, min(100.0, float(sap)))


def intensity_subscore(kwh_per_m2: float) -> float:
    return interpolate(M.INTENSITY_KNOTS, kwh_per_m2)


def loft_subscore(mm: float) -> float:
    return interpolate(M.LOFT_KNOTS, mm)


def wall_subscore(wall_type: str, insulated: bool) -> float:
    return M.WALL_SCORES[(wall_type, bool(insulated))]


def heating_subscore(system: str, boiler_age: float | None) -> float:
    base = ladder_score(M.HEATING_LADDER, system)
    if system.startswith("gas_boiler") and boiler_age is not None:
        base -= interpolate(M.BOILER_AGE_PENALTY_KNOTS, boiler_age)
    return max(0.0, base)


def pv_subscore(kwp: float) -> float:
    return interpolate(M.PV_KNOTS, kwp)


# ---------------------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------------------

_BASIS_RANK = {"observed": 0, "derived": 0, "not_applicable": 0, "assumed": 1, "estimated": 2, "missing": 3}


def _worst_basis(*items: Resolved) -> Basis:
    worst = max(items, key=lambda r: _BASIS_RANK[r.basis])
    return "observed" if worst.basis in ("derived", "not_applicable") else worst.basis


def _fmt_heating(system: str) -> str:
    return {
        "gas_boiler_noncondensing": "Non-condensing gas boiler",
        "gas_boiler_condensing": "Condensing gas boiler",
        "electric_storage": "Electric storage heaters",
        "electric_direct": "Direct electric heating",
        "air_source_heat_pump": "Air source heat pump",
        "ground_source_heat_pump": "Ground source heat pump",
    }[system]


_GLAZING_TEXT = {
    "single": "Single glazing",
    "secondary": "Secondary glazing",
    "double_pre_2002": "Double glazing (pre-2002)",
    "double_post_2002": "Double glazing (2002 or later)",
    "triple": "Triple glazing",
}
_CONTROLS_TEXT = {
    "none": "No heating controls",
    "programmer_thermostat": "Programmer and room thermostat",
    "programmer_thermostat_trvs": "Programmer, room thermostat and TRVs",
    "smart_thermostat": "Smart thermostat",
    "smart_zoned": "Smart thermostat with zone control",
}


def _component(key: str, sub: float | None, basis: Basis, display: str, explanation: str,
               inputs: dict) -> ComponentScore:
    w = M.WEIGHTS[key]
    receipt = Receipt(
        output=f"score.components.{key}",
        value=None if sub is None else round(sub, 1),
        unit="sub-score (0-100)",
        inputs=inputs,
        method=f"{M.LABELS[key]} mapping (see docs/SCORING_METHOD.md)",
        method_version=M.MAPPING_VERSION,
        sources=["Lloyds PS2 §03 (weights)", "docs/SCORING_METHOD.md"],
        notes=[f"basis: {basis}"],
    )
    return ComponentScore(
        key=key, label=M.LABELS[key], weight=w,
        sub_score=None if sub is None else round(sub, 2),
        contribution=None if sub is None else round(w * sub, 4),
        points_available=None if sub is None else round(w * (100.0 - sub), 4),
        basis=basis, input_display=display, explanation=explanation,
        improved_by=M.IMPROVED_BY[key], receipt=receipt,
    )


def _efficiency(inp: dict[str, Resolved]) -> ComponentScore:
    sap = inp.get("sap_score") or Resolved(basis="missing", note="no EPC rating")
    if not sap.known:
        return _component("energy_efficiency", None, "missing", "No EPC rating",
                          "No recorded or estimated energy rating is available.", {"sap_score": None})
    s = efficiency_subscore(sap.value)
    band = sap_to_band(sap.value)
    display = f"SAP {sap.value:.0f} (band {band})"
    if sap.note:
        display += f" · {sap.note}"
    expl = f"Energy rating SAP {sap.value:.0f} maps one-to-one onto the 0-100 scale (band {band})."
    return _component("energy_efficiency", s, _worst_basis(sap), display, expl,
                      {"sap_score": sap.value, "basis": sap.basis})


def _intensity(inp: dict[str, Resolved]) -> ComponentScore:
    it = inp.get("intensity_kwh_m2") or Resolved(basis="missing", note="no annual energy")
    if not it.known:
        return _component("consumption_intensity", None, "missing", "Unavailable",
                          it.note or "Annual purchased energy per m² could not be established.",
                          {"intensity_kwh_m2": None})
    s = intensity_subscore(it.value)
    display = f"{it.value:.0f} kWh/m²/yr"
    if it.note:
        display += f" · {it.note}"
    expl = (f"Purchased energy (grid electricity imported + gas) of {it.value:.0f} kWh per m² per year. "
            "Intensity is per m², so a large home is not penalised for its size.")
    return _component("consumption_intensity", s, _worst_basis(it), display, expl,
                      {"intensity_kwh_m2": round(it.value, 1), "basis": it.basis})


def _insulation(inp: dict[str, Resolved]) -> ComponentScore:
    wt, wi = inp["wall_type"], inp["wall_insulated"]
    loft, has_loft = inp["loft_insulation_mm"], inp["has_loft"]
    floor, has_floor = inp["floor_insulated"], inp["has_ground_floor"]

    parts: list[tuple[str, float, float]] = []  # (name, element weight, element score)
    missing: list[str] = []
    text: list[str] = []
    used = [wt, wi]

    if wt.known and wi.known:
        parts.append(("walls", M.INSULATION_ELEMENT_WEIGHTS["walls"], wall_subscore(wt.value, wi.value)))
        text.append(f"{wt.value} walls {'insulated' if wi.value else 'uninsulated'}")
    else:
        missing.append("walls")

    if has_loft.known and has_loft.value is False:
        text.append("no loft (dwelling above)")
    elif loft.known:
        parts.append(("loft", M.INSULATION_ELEMENT_WEIGHTS["loft"], loft_subscore(loft.value)))
        text.append(f"loft {loft.value} mm")
        used.append(loft)
    else:
        missing.append("loft")

    if has_floor.known and has_floor.value is False:
        text.append("no ground floor")
    elif floor.known:
        parts.append(("floor", M.INSULATION_ELEMENT_WEIGHTS["floor"], M.FLOOR_SCORES[bool(floor.value)]))
        text.append(f"floor {'insulated' if floor.value else 'uninsulated'}")
        used.append(floor)
    else:
        missing.append("floor")

    if missing:
        return _component("insulation", None, "missing", "Incomplete: " + ", ".join(missing) + " unknown",
                          "Insulation cannot be scored until " + ", ".join(missing) + " are known.",
                          {"missing": missing})
    total_w = sum(w for _, w, _ in parts)
    s = sum(w * v for _, w, v in parts) / total_w
    display = "; ".join(text)
    expl = ("Weighted average of " + ", ".join(f"{n} {v:.0f}/100" for n, _, v in parts) +
            " (element weights walls 45%, loft 35%, floor 20%, renormalised over elements that apply).")
    inputs = {n: round(v, 1) for n, _, v in parts}
    return _component("insulation", s, _worst_basis(*used), display, expl, inputs)


def _heating(inp: dict[str, Resolved]) -> ComponentScore:
    hs, age = inp["heating_system"], inp["boiler_age_years"]
    if not hs.known:
        return _component("heating_system", None, "missing", "Unknown heating system",
                          "The heating system is not recorded, so it cannot be scored.", {})
    s = heating_subscore(hs.value, age.value if age.basis != "not_applicable" else None)
    display = _fmt_heating(hs.value)
    expl = f"{display} scores {ladder_score(M.HEATING_LADDER, hs.value):.0f} on the heating ladder"
    if hs.value.startswith("gas_boiler") and age.value is not None:
        display += f", {age.value} years old"
        pen = interpolate(M.BOILER_AGE_PENALTY_KNOTS, age.value)
        if pen > 0:
            expl += f", minus {pen:.0f} for boiler age"
    expl += "."
    used = [hs] + ([age] if age.basis != "not_applicable" else [])
    return _component("heating_system", s, _worst_basis(*used), display, expl,
                      {"heating_system": hs.value, "boiler_age_years": age.value})


def _ladder_component(key: str, r: Resolved, ladder, text: dict[str, str]) -> ComponentScore:
    if not r.known:
        return _component(key, None, "missing", "Unknown", f"{M.LABELS[key]} is not recorded.", {})
    s = ladder_score(ladder, r.value)
    return _component(key, s, _worst_basis(r), text[r.value],
                      f"{text[r.value]} scores {s:.0f} on the {M.LABELS[key].lower()} ladder.", {key: r.value})


def _renewables(inp: dict[str, Resolved]) -> ComponentScore:
    pv = inp["solar_pv_kwp"]
    s = pv_subscore(pv.value)
    display = "No solar PV" if not pv.value else f"{pv.value:.1f} kWp solar PV"
    expl = f"{display}; a typical full domestic array (≈4 kWp) scores 100."
    return _component("renewables", s, _worst_basis(pv), display, expl, {"solar_pv_kwp": pv.value})


# ---------------------------------------------------------------------------------------
# The score
# ---------------------------------------------------------------------------------------

def compute_score(inp: dict[str, Resolved]) -> ScoreResult:
    """Compute the Green Home Score from resolved inputs.

    ``inp`` must contain the keys produced by ``features.resolve.resolve_inputs`` plus
    ``sap_score`` and ``intensity_kwh_m2`` (both ``Resolved``; either may be missing).
    """
    comps = [
        _efficiency(inp),
        _intensity(inp),
        _insulation(inp),
        _heating(inp),
        _ladder_component("glazing", inp["glazing"], M.GLAZING_LADDER, _GLAZING_TEXT),
        _renewables(inp),
        _ladder_component("smart_controls", inp["controls"], M.CONTROLS_LADDER, _CONTROLS_TEXT),
    ]
    assert abs(sum(c.weight for c in comps) - 1.0) < 1e-12

    missing = [c.key for c in comps if c.sub_score is None]
    estimated = [c.key for c in comps if c.basis in ("assumed", "estimated")]
    known_sum = sum(c.weight * c.sub_score for c in comps if c.sub_score is not None)

    if missing:
        missing_w = sum(c.weight for c in comps if c.sub_score is None)
        lo, hi = round_half_up(known_sum), round_half_up(known_sum + 100.0 * missing_w)
        band = band_for(lo) if band_for(lo) == band_for(hi) else None
        status, score, raw, rng = "partial", None, None, (lo, hi)
        is_poor = True if band in M.POOR_BANDS else (False if band else None)
        if band is None and band_for(hi) in M.POOR_BANDS:
            is_poor = True  # even the best case is poor
    else:
        raw = known_sum
        score = round_half_up(raw)
        band = band_for(score)
        status = "provisional" if estimated else "complete"
        rng = None
        is_poor = band in M.POOR_BANDS

    issues = [
        Issue(component=c.key, label=c.label, sub_score=c.sub_score, points_available=c.points_available,
              text=f"{c.label}: {c.input_display} ({c.sub_score:.0f}/100, {c.points_available:.1f} points available)",
              improved_by=c.improved_by)
        for c in sorted((c for c in comps if c.sub_score is not None and c.sub_score < 60),
                        key=lambda c: -c.points_available)
    ]

    receipt = Receipt(
        output="score",
        value=score if score is not None else rng,
        unit="Green Home Score (0-100)",
        inputs={c.key: c.sub_score for c in comps},
        method=SCORE_METHOD,
        method_version=M.MAPPING_VERSION,
        sources=["Lloyds PS2 §03 Green Home Score"],
        notes=([f"missing components: {', '.join(missing)}"] if missing else [])
        + ([f"assumed/estimated components: {', '.join(estimated)}"] if estimated else []),
    )
    return ScoreResult(
        status=status, score=score, raw_score=None if raw is None else round(raw, 4), band=band,
        score_range=rng, is_poor=is_poor, components=comps, missing_components=missing,
        estimated_components=estimated, issues=issues, receipt=receipt,
    )
