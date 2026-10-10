"""Retrofit planner: which measures are feasible for THIS home, how suitable, and in what order.

Feasibility comes first (PS2: "feasible, not exhaustive"). Each candidate carries its
suitability (High / Medium / Low), the property evidence behind it, what it depends on,
and what is uncertain. Everything not recommended is listed with a reason.

Sequencing follows the "fabric first" principle of UK whole-house retrofit guidance:
1 fabric → 2 controls → 3 low-carbon heating (sized for the improved home) → 4 solar
(sized for the new electricity demand).
"""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from ..contract import MEASURES, Property, Resolved
from . import physics
from .catalogue import measure, measure_name

RETROFIT_VERSION = "retrofit-rules/1.1"  # 1.1: thresholds from the catalogue; consent cases = needs_survey
Suitability = Literal["High", "Medium", "Low"]
ExclusionStatus = Literal["not_needed", "infeasible", "not_applicable", "needs_survey", "declined", "completed"]
FABRIC = ("loft_insulation", "cavity_wall_insulation", "solid_wall_insulation", "glazing_upgrade")


class Candidate(BaseModel):
    measure_id: str
    name: str
    stage: int
    suitability: Suitability
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)


class Excluded(BaseModel):
    measure_id: str
    name: str
    status: ExclusionStatus
    reason: str


def _rule(measure_id: str, key: str) -> float:
    """An applicability threshold, documented in the retrofit catalogue (config/retrofit_catalogue.json)."""
    return measure(measure_id)["applicability"][key]


def _ev(label: str, r: Resolved, fmt=lambda v: ("yes" if v else "no") if isinstance(v, bool) else str(v).replace("_", " ")) -> str:
    tag = "" if r.basis in ("observed", "derived") else f" ({r.basis})"
    return f"{label}: {fmt(r.value)}{tag}"


def _assumed(r: Resolved) -> bool:
    return r.basis in ("assumed", "estimated")


def plan_candidates(
    p: Property,
    inp: dict[str, Resolved],
    effective_heating: str | None,
    constraints: dict | None = None,
) -> tuple[list[Candidate], list[Excluded]]:
    """Return (feasible candidates, excluded measures with reasons)."""
    constraints = constraints or {}
    declined = set(constraints.get("declined_measures", []))
    done = {r.measure_id for r in p.retrofits_completed} | set(constraints.get("completed_measures", []))
    cands: list[Candidate] = []
    excl: list[Excluded] = []

    def exclude(mid: str, status: ExclusionStatus, reason: str) -> None:
        excl.append(Excluded(measure_id=mid, name=measure_name(mid), status=status, reason=reason))

    def add(mid: str, suit: Suitability, rationale: str, evidence: list[str], uncertainty=None, depends=None) -> None:
        cands.append(Candidate(measure_id=mid, name=measure_name(mid), stage=measure(mid)["stage"], suitability=suit,
                               rationale=rationale, evidence=evidence, uncertainty=uncertainty or [],
                               depends_on=depends or []))

    listed = p.listed_or_conservation is True
    is_flat = p.property_type == "flat"

    # --- Loft --------------------------------------------------------------------------
    has_loft, loft = inp["has_loft"], inp["loft_insulation_mm"]
    if not has_loft.known:
        exclude("loft_insulation", "needs_survey", "Whether the home has its own roof space is unknown (flat position not recorded).")
    elif has_loft.value is False:
        exclude("loft_insulation", "infeasible", has_loft.note or "No loft: another dwelling is above.")
    elif loft.known and loft.value >= _rule("loft_insulation", "not_needed_from_mm"):
        exclude("loft_insulation", "not_needed", f"Loft already has {loft.value} mm of insulation.")
    else:
        mm = loft.value if loft.known else None
        suit: Suitability = "High" if mm is not None and mm <= _rule("loft_insulation", "high_suitability_up_to_mm") else "Medium"
        unc = ["Loft depth not recorded; assumed from construction age. A quick loft check confirms it."] if _assumed(loft) else []
        add("loft_insulation", suit, "Topping up to 270 mm cuts heat lost through the roof; it is cheap and quick.",
            [_ev("Loft insulation", loft, lambda v: f"{v} mm")], unc)

    # --- Walls ---------------------------------------------------------------------------
    wt, wi = inp["wall_type"], inp["wall_insulated"]
    if not wt.known or not wi.known:
        for mid in ("cavity_wall_insulation", "solid_wall_insulation"):
            exclude(mid, "needs_survey", "Wall type or wall insulation unknown and no construction age to infer it.")
    else:
        if wi.value:
            for mid in ("cavity_wall_insulation", "solid_wall_insulation"):
                exclude(mid, "not_needed", "Walls are already insulated.")
        elif wt.value == "cavity":
            unc = ["Wall construction assumed from age band; a borescope survey confirms an empty cavity."] \
                if _assumed(wt) or _assumed(wi) else []
            add("cavity_wall_insulation", "Medium" if unc else "High",
                "Filling an empty cavity is one of the most cost-effective fabric measures.",
                [_ev("Wall type", wt), _ev("Wall insulated", wi)], unc)
            exclude("solid_wall_insulation", "not_applicable", "Walls are cavity walls; cavity fill applies instead.")
        else:
            unc = ["High cost and disruption; internal insulation reduces room size."]
            if listed:
                unc.append("Listed or conservation area: external insulation usually needs consent; internal insulation assumed.")
            if _assumed(wt):
                unc.append("Solid walls assumed from construction age.")
            add("solid_wall_insulation", "Low" if listed else "Medium",
                "Solid walls lose heat fastest of any element; insulating them gives a large heating saving.",
                [_ev("Wall type", wt), _ev("Wall insulated", wi)], unc)
            exclude("cavity_wall_insulation", "not_applicable", "Walls are solid; there is no cavity to fill.")

    # --- Glazing -------------------------------------------------------------------------
    gl = inp["glazing"]
    if not gl.known:
        exclude("glazing_upgrade", "needs_survey", "Glazing type unknown.")
    elif gl.value in ("double_post_2002", "triple"):
        exclude("glazing_upgrade", "not_needed", "Glazing is already modern double or triple.")
    else:
        suit = "High" if gl.value == "single" else ("Medium" if gl.value == "secondary" else "Low")
        if listed:
            suit = "Low"
        unc = ["Listed or conservation area: replacement windows may need consent; secondary glazing is the usual route."] \
            if listed else []
        add("glazing_upgrade", suit, "Modern double glazing reduces heat loss and draughts.", [_ev("Glazing", gl)], unc)

    # --- Controls --------------------------------------------------------------------------
    ctrl = inp["controls"]
    if effective_heating is None:
        exclude("smart_controls", "needs_survey", "Heating system unknown.")
    elif ctrl.value in ("smart_thermostat", "smart_zoned") and ctrl.basis == "observed":
        exclude("smart_controls", "not_needed", "Smart controls already installed.")
    elif effective_heating in ("electric_storage", "electric_direct"):
        exclude("smart_controls", "not_applicable",
                "Electric storage/direct heaters need different (heater-level) controls, which this version does not model.")
    else:
        unc = ["Measured savings from smart thermostats vary widely between households (about 0-10%)."]
        if ctrl.basis == "assumed":
            unc.append("Current controls not recorded; assumed programmer + thermostat.")
        add("smart_controls", "High" if ctrl.value == "none" else "Medium",
            "Heating only when and where it is needed trims heating demand at low cost.", [_ev("Controls", ctrl)], unc)

    # --- Heat pump ---------------------------------------------------------------------------
    fabric_cands = [c.measure_id for c in cands if c.measure_id in FABRIC]
    if effective_heating is None:
        exclude("air_source_heat_pump", "needs_survey", "Heating system unknown.")
    elif effective_heating.endswith("heat_pump"):
        exclude("air_source_heat_pump", "not_needed", "The home already has a heat pump.")
    elif p.outdoor_space is False:
        exclude("air_source_heat_pump", "infeasible", "No outdoor space for the external unit.")
    else:
        phys = physics.physical_state(p.property_type, inp)
        improved = copy.deepcopy(phys)
        for mid in fabric_cands:
            if mid == "loft_insulation":
                improved["loft_mm"] = 270.0
            elif mid in ("cavity_wall_insulation", "solid_wall_insulation"):
                improved["wall_insulated"] = True
            elif mid == "glazing_upgrade":
                improved["glazing"] = "double_post_2002"
        hlc_now, hlc_fab = physics.hlc_per_m2(phys), physics.hlc_per_m2(improved)
        suit = ("High" if hlc_fab <= _rule("air_source_heat_pump", "high_suitability_max_hlc_per_m2")
                else "Medium" if hlc_fab <= _rule("air_source_heat_pump", "medium_suitability_max_hlc_per_m2") else "Low")
        if effective_heating in ("electric_storage", "electric_direct") and suit != "High":
            suit = "High" if suit == "Medium" else "Medium"
        hp = measure("air_source_heat_pump")["engineering"]
        unc = ["Real-world efficiency (SCOP) depends on design and installation quality."]
        if p.outdoor_space is None:
            unc.append("Outdoor space for the external unit not recorded; a site survey must confirm it.")
            suit = "Low" if suit == "Medium" else ("Medium" if suit == "High" else "Low")
        if is_flat:
            unc.append("Flats often need freeholder or landlord permission for an external unit.")
        add("air_source_heat_pump", suit,
            f"Replaces fossil or direct-electric heating with heat that is {hp['scop_worst']}-{hp['scop_best']}x more "
            "efficient; electricity use rises while gas falls.",
            [f"Current heating: {effective_heating.replace('_', ' ')}",
             f"Heat loss {hlc_now:.1f} W/K per m² now, {hlc_fab:.1f} after recommended fabric measures"],
            unc, depends=fabric_cands)

    # --- Solar PV ------------------------------------------------------------------------------
    pv, orient, shade = inp["solar_pv_kwp"], p.roof_orientation, p.roof_shading
    if pv.known and pv.value and pv.value > 0:
        exclude("solar_pv", "not_needed", f"Already has {pv.value} kWp of solar PV.")
    elif is_flat and p.flat_position is None:
        exclude("solar_pv", "needs_survey", "Flat position not recorded: only a top-floor flat has a roof above it.")
    elif is_flat and p.flat_position != "top":
        exclude("solar_pv", "infeasible", "Not a top-floor flat: there is no roof above this home for panels.")
    elif orient == "north":
        exclude("solar_pv", "infeasible", "North-facing roof: generation would be too low to justify panels.")
    elif is_flat:
        exclude("solar_pv", "needs_survey", "Top-floor flat: the roof is usually shared, so panels need the freeholder's "
                                            "consent. Check this first.")
    elif listed:
        exclude("solar_pv", "needs_survey", "Listed building or conservation area: roof panels usually need consent. "
                                            "Check this first.")
    else:
        suit = "High" if orient == "south" else "Medium"
        if shade == "high":
            suit = "Low"
        unc = []
        if orient is None:
            unc.append("Roof orientation not recorded; an east/west roof is assumed.")
            suit = "Medium"
        if shade is None:
            unc.append("Roof shading not recorded; low shading assumed.")
        hp_dep = [c.measure_id for c in cands if c.measure_id == "air_source_heat_pump"]
        add("solar_pv", suit, "Panels cut grid imports by supplying some of the home's own electricity "
                              "(they do not reduce demand).",
            [f"Roof orientation: {orient or 'unknown'}", f"Shading: {shade or 'unknown'}"], unc, depends=hp_dep)

    # --- Unknown listed/conservation status gates several measures ---------------------------
    if p.listed_or_conservation is None:
        for c in cands:
            if c.measure_id in ("solar_pv", "solid_wall_insulation", "glazing_upgrade"):
                c.uncertainty.append("Listed-building / conservation-area status not recorded; consent may be needed.")

    # --- Customer memory: completed and declined measures -----------------------------------
    final, out_excl = [], list(excl)
    for c in cands:
        if c.measure_id in done:
            out_excl.append(Excluded(measure_id=c.measure_id, name=c.name, status="completed",
                                     reason="Already completed (from retrofit history or what the customer told us)."))
        elif c.measure_id in declined:
            out_excl.append(Excluded(measure_id=c.measure_id, name=c.name, status="declined",
                                     reason="The customer said they do not want this measure."))
        else:
            final.append(c)
    covered = {c.measure_id for c in final} | {e.measure_id for e in out_excl}
    assert covered == set(MEASURES), covered ^ set(MEASURES)
    return final, out_excl
