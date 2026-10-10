"""Green Home Score: PS2 formula, weights, bands, rounding, monotonicity, missing data."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greeniq.config import score_mappings as M
from greeniq.contract import Property, Resolved
from greeniq.features.resolve import resolve_inputs
from greeniq.score import (
    band_for, compute_score, heating_subscore, intensity_subscore, loft_subscore, pv_subscore,
    round_half_up, wall_subscore,
)


def inputs_for(p: Property, sap=None, intensity=None) -> dict[str, Resolved]:
    inp = resolve_inputs(p)
    inp["sap_score"] = Resolved(value=sap, basis="observed") if sap is not None else Resolved(basis="missing")
    inp["intensity_kwh_m2"] = (
        Resolved(value=intensity, basis="observed") if intensity is not None else Resolved(basis="missing")
    )
    return inp


def full_house(**over) -> Property:
    base = dict(
        property_id="T1", region="midlands", property_type="semi_detached", age_band="1945_1964",
        floor_area_m2=90, wall_type="cavity", wall_insulated=False, has_loft=True, loft_insulation_mm=100,
        floor_insulated=False, glazing="double_pre_2002", heating_system="gas_boiler_condensing",
        boiler_age_years=8, controls="programmer_thermostat", solar_pv_kwp=0.0,
    )
    base.update(over)
    return Property(**base)


# --- PS2-fixed contract -------------------------------------------------------------------

def test_weights_are_exactly_ps2():
    assert M.WEIGHTS == {
        "energy_efficiency": 0.25, "consumption_intensity": 0.20, "insulation": 0.15,
        "heating_system": 0.15, "glazing": 0.10, "renewables": 0.10, "smart_controls": 0.05,
    }
    assert sum(M.WEIGHTS.values()) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("score,band", [
    (0, "Very poor"), (29, "Very poor"), (30, "Poor"), (49, "Poor"), (50, "Moderate"),
    (64, "Moderate"), (65, "Good"), (79, "Good"), (80, "Highly efficient"), (100, "Highly efficient"),
])
def test_band_boundaries(score, band):
    assert band_for(score) == band


@pytest.mark.parametrize("x,expected", [(64.5, 65), (64.49, 64), (29.5, 30), (79.5, 80), (0.0, 0), (100.0, 100)])
def test_round_half_up(x, expected):
    assert round_half_up(x) == expected


def test_score_is_weighted_sum_of_contributions():
    r = compute_score(inputs_for(full_house(), sap=58, intensity=170))
    assert r.status == "complete"
    raw = sum(c.weight * c.sub_score for c in r.components)
    assert r.raw_score == pytest.approx(raw, abs=1e-6)
    assert r.score == round_half_up(raw)
    assert sum(c.contribution for c in r.components) == pytest.approx(raw, abs=1e-3)
    assert r.band == band_for(r.score)
    assert all(c.receipt.method_version == M.MAPPING_VERSION for c in r.components)


def test_ps_style_poor_home_is_flagged_poor():
    p = full_house(age_band="pre_1919", wall_type="solid", wall_insulated=False, loft_insulation_mm=25,
                   glazing="single", heating_system="gas_boiler_noncondensing", boiler_age_years=22,
                   controls="none")
    r = compute_score(inputs_for(p, sap=34, intensity=290))
    assert r.band in ("Poor", "Very poor") and r.is_poor
    assert r.issues and r.issues[0].points_available >= r.issues[-1].points_available


# --- Monotonicity of every mapping --------------------------------------------------------

@given(st.floats(0, 600), st.floats(0, 600))
def test_intensity_never_rewards_more_energy(a, b):
    lo, hi = sorted((a, b))
    assert intensity_subscore(lo) >= intensity_subscore(hi)


@given(st.floats(0, 600), st.floats(0, 600))
def test_loft_depth_monotone(a, b):
    lo, hi = sorted((a, b))
    assert loft_subscore(lo) <= loft_subscore(hi)


@given(st.floats(0, 25), st.floats(0, 25))
def test_pv_monotone(a, b):
    lo, hi = sorted((a, b))
    assert pv_subscore(lo) <= pv_subscore(hi)


@given(st.integers(0, 80), st.integers(0, 80))
def test_newer_boiler_never_scores_lower(a, b):
    young, old = sorted((a, b))
    for system in ("gas_boiler_condensing", "gas_boiler_noncondensing"):
        assert heating_subscore(system, young) >= heating_subscore(system, old)


@pytest.mark.parametrize("ladder", [M.GLAZING_LADDER, M.HEATING_LADDER, M.CONTROLS_LADDER])
def test_ladders_never_decrease(ladder):
    scores = [s for _, s in ladder]
    assert scores == sorted(scores)


def test_heating_rungs_do_not_overlap_even_with_oldest_boiler():
    """Moving up the heating ladder must never lower the sub-score, whatever the boiler age."""
    systems = [s for s, _ in M.HEATING_LADDER]
    for lower, upper in zip(systems, systems[1:]):
        best_lower = max(heating_subscore(lower, age) for age in range(0, 81))
        worst_upper = min(heating_subscore(upper, age) for age in range(0, 81))
        assert worst_upper >= best_lower, (lower, upper)


def test_insulated_wall_never_lower():
    for wt in ("solid", "cavity"):
        assert wall_subscore(wt, True) >= wall_subscore(wt, False)


def test_sap_bands_and_midpoints_are_ordered():
    mids = [M.EPC_BAND_MIDPOINT[b] for b in "GFEDCBA"]
    assert mids == sorted(mids)


# Whole-score monotonicity: improving any single input never lowers the score.
GLAZ = [g for g, _ in M.GLAZING_LADDER]
HEAT = [h for h, _ in M.HEATING_LADDER]
CTRL = [c for c, _ in M.CONTROLS_LADDER]

home_strategy = st.fixed_dictionaries({
    "glazing": st.integers(0, len(GLAZ) - 1),
    "heating": st.integers(0, len(HEAT) - 1),
    "controls": st.integers(0, len(CTRL) - 1),
    "loft": st.integers(0, 400),
    "wall_type": st.sampled_from(["solid", "cavity"]),
    "wall_ins": st.booleans(),
    "floor_ins": st.booleans(),
    "pv": st.floats(0, 8),
    "sap": st.integers(1, 110),
    "intensity": st.floats(20, 500),
    "boiler_age": st.integers(0, 40),
})


def _score_of(h: dict) -> float:
    p = full_house(glazing=GLAZ[h["glazing"]], heating_system=HEAT[h["heating"]], controls=CTRL[h["controls"]],
                   loft_insulation_mm=h["loft"], wall_type=h["wall_type"], wall_insulated=h["wall_ins"],
                   floor_insulated=h["floor_ins"], solar_pv_kwp=h["pv"], boiler_age_years=h["boiler_age"])
    return compute_score(inputs_for(p, sap=h["sap"], intensity=h["intensity"])).raw_score


@settings(max_examples=300, deadline=None)
@given(home_strategy, st.sampled_from(["glazing", "heating", "controls", "loft", "wall_ins", "floor_ins",
                                       "pv", "sap", "intensity", "boiler_age"]))
def test_improving_one_input_never_lowers_the_score(h, field):
    better = dict(h)
    if field in ("glazing", "controls"):
        better[field] = min(h[field] + 1, len(GLAZ if field == "glazing" else CTRL) - 1)
    elif field == "heating":
        better[field] = min(h[field] + 1, len(HEAT) - 1)
    elif field == "loft":
        better[field] = h[field] + 50
    elif field in ("wall_ins", "floor_ins"):
        better[field] = True
    elif field == "pv":
        better[field] = h[field] + 1.0
    elif field == "sap":
        better[field] = min(h[field] + 5, 150)
    elif field == "intensity":
        better[field] = max(h[field] - 25, 1.0)
    elif field == "boiler_age":
        better[field] = max(h[field] - 5, 0)
    assert _score_of(better) >= _score_of(h) - 1e-9


# --- Missing data and fairness ------------------------------------------------------------

def test_missing_component_gives_honest_range_not_a_guess():
    r = compute_score(inputs_for(full_house(), sap=None, intensity=170))
    assert r.status == "partial" and r.score is None
    assert "energy_efficiency" in r.missing_components
    lo, hi = r.score_range
    assert hi - lo == 25  # the missing 25% weight spans 0..100
    full = compute_score(inputs_for(full_house(), sap=60, intensity=170))
    assert lo <= full.score <= hi


def test_band_reported_only_when_range_is_unambiguous():
    r = compute_score(inputs_for(full_house(), sap=None, intensity=None))
    assert r.score_range[1] - r.score_range[0] == 45
    assert r.band is None


def test_assumed_defaults_make_score_provisional():
    p = Property(property_id="T2", region="north", property_type="terraced", age_band="1919_1944",
                 floor_area_m2=80, heating_system="gas_boiler_condensing")
    r = compute_score(inputs_for(p, sap=55, intensity=180))
    assert r.status == "provisional" and r.score is not None
    assert "insulation" in r.estimated_components and "glazing" in r.estimated_components


def test_mid_floor_flat_not_penalised_for_missing_loft():
    flat = Property(property_id="F", region="london", property_type="flat", flat_position="mid",
                    age_band="1981_2002", floor_area_m2=60, wall_type="cavity", wall_insulated=True,
                    glazing="double_post_2002", heating_system="gas_boiler_condensing", boiler_age_years=5,
                    controls="smart_thermostat", solar_pv_kwp=0)
    r = compute_score(inputs_for(flat, sap=72, intensity=140))
    ins = next(c for c in r.components if c.key == "insulation")
    assert ins.sub_score == pytest.approx(wall_subscore("cavity", True))


def test_intensity_is_per_m2_so_size_alone_does_not_lower_score():
    small = compute_score(inputs_for(full_house(floor_area_m2=80), sap=65, intensity=120))
    big = compute_score(inputs_for(full_house(floor_area_m2=240), sap=65, intensity=120))
    assert small.score == big.score


def test_contract_rejects_impossible_values():
    with pytest.raises(ValueError):
        full_house(floor_area_m2=-5)
    with pytest.raises(ValueError):
        full_house(sap_score=500)
    with pytest.raises(ValueError):
        Property(property_id="X", region="london", property_type="detached", flat_position="mid")


def test_ps2_worked_example_p10001_is_poor():
    """PS2 §2 example: rating E, high electricity and gas use, no solar, poor insulation, gas boiler, single
    glazing → 38/100, Poor. The sub-score mappings are the team's (documented) choice, so we check the class
    and that the score sits near the example, not the exact figure."""
    import json
    from pathlib import Path

    from greeniq.context import load_context
    from greeniq.contract import Property
    from greeniq.pipeline import analyse_home

    base = json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())[0]["property"]
    gas = [m for m in base["meter_readings"] if m["fuel"] == "gas"]
    total = sum(m["kwh"] for m in gas)
    p = dict(base, property_id="P10001", epc_band="E", sap_score=45, wall_type="cavity", wall_insulated=False,
             loft_insulation_mm=50, glazing="single", heating_system="gas_boiler_condensing", boiler_age_years=18,
             controls="programmer_thermostat", solar_pv_kwp=0, floor_area_m2=90, age_band="1945_1964",
             meter_readings=[{**m, "kwh": round(m["kwh"] * 14000 / total, 1)} for m in gas]
             + [{"month": m["month"], "fuel": "electricity", "kwh": 400} for m in gas])
    s = analyse_home(Property(**p), load_context()).score
    assert s.band == "Poor" and 30 <= s.score <= 45


def test_score_by_hand_from_the_ps2_formula():
    """S = Σ w_k s_k worked by hand with the documented tables (docs/SCORING_METHOD.md), literal numbers only."""
    r = compute_score(inputs_for(full_house(), sap=45, intensity=200))
    subs = {c.key: c.sub_score for c in r.components}
    assert subs == {
        "energy_efficiency": 45.0,          # SAP 45 maps one-to-one
        "consumption_intensity": 47.0,      # knot (200 kWh/m², 47)
        "insulation": 34.25,                # 0.50×30 (cavity, unfilled) + 0.35×55 (loft 100 mm) + 0.15×0 (floor)
        "heating_system": 62.0,             # condensing gas; 8-year boiler → no age penalty
        "glazing": 70.0,                    # double glazing pre-2002
        "renewables": 0.0,                  # no PV
        "smart_controls": 40.0,             # programmer + room thermostat
    }
    # 0.25×45 + 0.20×47 + 0.15×34.25 + 0.15×62 + 0.10×70 + 0.10×0 + 0.05×40
    # = 11.25 + 9.4 + 5.1375 + 9.3 + 7.0 + 0 + 2.0 = 44.0875 → 44 → Poor (30-49)
    assert r.raw_score == pytest.approx(44.0875)
    assert (r.score, r.band, r.is_poor) == (44, "Poor", True)
    ins = next(c for c in r.components if c.key == "insulation")
    assert "walls 50%, loft 35%, floor 15%" in ins.explanation  # the text states the weights actually used
