"""Deterministic engines and the analyse_home pipeline, against PS2's scenario tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from greeniq.context import load_context
from greeniq.contract import Property
from greeniq.engines.carbon import carbon_reduction, factor
from greeniq.engines.energy import apply_measure
from greeniq.facts import Scenario
from greeniq.pipeline import analyse_home

FIXTURES = {f["property"]["property_id"]: f for f in
            json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())}


@pytest.fixture(scope="module")
def ctx():
    return load_context(with_models=False)


def run(ctx, pid, **kw):
    return analyse_home(Property(**FIXTURES[pid]["property"]), ctx, **kw)


def rec(facts, mid):
    return next(r for r in facts.plan if r.measure_id == mid)


# --- Fixture expectations (documented in the fixture file) -------------------------------

@pytest.mark.parametrize("pid", list(FIXTURES))
def test_fixture_expected_behaviour(ctx, pid):
    exp = FIXTURES[pid]["expected"]
    f = run(ctx, pid)
    planned = {r.measure_id for r in f.plan}
    if "band_in" in exp:
        assert f.score.band in exp["band_in"]
    if "is_poor" in exp:
        assert f.score.is_poor is exp["is_poor"]
    for m in exp.get("feasible", []):
        assert m in planned, f"{m} should be feasible for {pid}"
    for m in exp.get("infeasible", []):
        assert m not in planned, f"{m} should not be recommended for {pid}"
        assert any(e.measure_id == m and e.reason for e in f.excluded)
    if "improvement_potential" in exp:
        assert f.package is None or f.package.improvement_potential.status == exp["improvement_potential"]
    if "score_status_in" in exp:
        assert f.score.status in exp["score_status_in"]
    if "conflict" in exp:
        assert exp["conflict"] in {c.code for c in f.conflicts}
    if "gas_status" in exp:
        assert f.baseline["gas"].basis == exp["gas_status"]


# --- Per-fuel energy -----------------------------------------------------------------------

def test_heat_pump_raises_electricity_cuts_gas_and_still_cuts_carbon(ctx):
    f = run(ctx, "FX-HP-CANDIDATE")
    hp = rec(f, "air_source_heat_pump")
    assert hp.standalone.electricity.saving_kwh < 0, "electricity must rise (negative saving)"
    assert hp.standalone.gas.saving_kwh > 0
    assert hp.standalone.net_saving_kwh > 0
    assert hp.standalone.carbon.electricity_kg < 0 < hp.standalone.carbon.gas_kg
    assert hp.standalone.carbon.total_kg > 0


def test_package_is_not_the_sum_of_standalone_savings(ctx):
    pk = run(ctx, "FX-POOR-SEMI").package
    assert pk.interaction_kwh != 0
    assert pk.impact.net_saving_kwh < pk.sum_of_standalone_net_kwh  # overlapping heat savings
    assert pk.impact.net_saving_kwh == pytest.approx(pk.sum_of_standalone_net_kwh + pk.interaction_kwh)


def test_insulation_before_heat_pump_beats_heat_pump_first(ctx):
    measures = ["loft_insulation", "solid_wall_insulation", "air_source_heat_pump"]
    insulate_first = run(ctx, "FX-POOR-SEMI", scenario=Scenario(measures=measures, order="recommended")).package
    hp_first = run(ctx, "FX-POOR-SEMI",
                   scenario=Scenario(measures=list(reversed(measures)), order="as_given")).package
    assert insulate_first.measures[-1] == "air_source_heat_pump"
    assert hp_first.measures[0] == "air_source_heat_pump"
    # same measures, but the heat pump designed for the leaky home runs less efficiently
    assert insulate_first.impact.electricity.after_kwh < hp_first.impact.electricity.after_kwh


def test_fabric_comes_before_heat_pump_and_solar_last(ctx):
    order = [r.measure_id for r in run(ctx, "FX-POOR-SEMI").plan]
    assert order.index("air_source_heat_pump") > max(order.index(m) for m in ("loft_insulation", "solid_wall_insulation"))
    assert order[-1] == "solar_pv"
    hp = rec(run(ctx, "FX-POOR-SEMI"), "air_source_heat_pump")
    assert "loft_insulation" in hp.depends_on


def test_solar_reduces_imports_not_demand(ctx):
    from greeniq.engines.energy import decompose
    from greeniq.features.resolve import resolve_inputs
    p = Property(**FIXTURES["FX-HP-CANDIDATE"]["property"])
    st = decompose(p.property_type, resolve_inputs(p), p.region, "gas_boiler_condensing", 9,
                   {"electricity": {"annual": 3000.0, "heating": 0.0}, "gas": {"annual": 12000.0, "heating": 9000.0}},
                   0.0, "south", "low", "programmer_thermostat")
    before, after = st.purchased(), apply_measure(st, "solar_pv", property_type=p.property_type).purchased()
    assert after["electricity_demand"] == pytest.approx(before["electricity_demand"])
    assert after["electricity"] < before["electricity"]
    assert after["pv_self_consumed"] > 0


def test_decomposition_reproduces_the_metered_baseline(ctx):
    for pid in ("FX-POOR-SEMI", "FX-HP-CANDIDATE", "FX-MID-FLAT", "FX-LARGE-EFFICIENT"):
        f = run(ctx, pid)
        if f.package:
            assert f.package.impact.electricity.baseline_kwh == pytest.approx(f.baseline["electricity"].annual_kwh, abs=10)
            assert f.package.impact.gas.baseline_kwh == pytest.approx(f.baseline["gas"].annual_kwh, abs=10)


# --- Feasibility and scenarios ------------------------------------------------------------

def test_infeasible_retrofit_is_refused_with_a_reason(ctx):
    f = run(ctx, "FX-MID-FLAT", scenario=Scenario(name="flat solar", measures=["solar_pv", "glazing_upgrade"]))
    assert f.scenario.modelled == ["glazing_upgrade"]
    rej = {r.measure_id: r for r in f.scenario.rejected}
    assert "solar_pv" in rej and rej["solar_pv"].status in ("infeasible", "needs_survey") and "roof" in rej["solar_pv"].reason


def test_unmodelled_scenario_rejected_entirely_gives_no_numbers(ctx):
    f = run(ctx, "FX-MID-FLAT", scenario=Scenario(measures=["air_source_heat_pump"]))
    assert f.package is None and f.scenario.rejected


# --- Improvement potential --------------------------------------------------------------

def test_improvement_potential_matches_ps2_formula(ctx):
    pk = run(ctx, "FX-POOR-SEMI").package
    ip = pk.improvement_potential
    assert ip.status == "available"
    assert ip.pct == pytest.approx(100 * (ip.e_baseline_kwh - ip.e_after_kwh) / ip.e_baseline_kwh, abs=0.05)


def test_zero_baseline_gives_unavailable_not_zero_percent(ctx):
    f = run(ctx, "FX-VOID-ZERO")
    assert f.package.improvement_potential.status == "unavailable"
    assert f.package.improvement_potential.pct is None
    assert f.intensity_kwh_m2.basis == "missing"  # zero use must not score as "efficient"
    assert any("zero" in w.lower() for w in f.warnings)


def test_estimated_baseline_still_reports_potential_labelled_estimated(ctx):
    """PS2 §3 makes the metric unavailable only for a zero or unavailable baseline, not an estimated one."""
    f = run(ctx, "FX-MISSING-DATA")
    assert f.baseline_basis == "estimated"
    ip = f.package.improvement_potential
    assert ip.status == "available" and ip.basis == "estimated"
    assert ip.pct == pytest.approx(100 * (ip.e_baseline_kwh - ip.e_after_kwh) / ip.e_baseline_kwh, abs=0.05)


# --- Carbon --------------------------------------------------------------------------------

def test_carbon_is_per_fuel_with_signs():
    c = carbon_reduction(1000, 2000)
    assert c.electricity_kg == pytest.approx(1000 * factor("electricity"), abs=0.1)
    assert c.gas_kg == pytest.approx(2000 * factor("gas"), abs=0.1)
    assert c.total_kg == pytest.approx(c.electricity_kg + c.gas_kg, abs=0.2)
    neg = carbon_reduction(-3000, 0)
    assert neg.total_kg < 0  # an increase is reported, not hidden


def test_package_carbon_recomputes_from_displayed_kwh(ctx):
    pk = run(ctx, "FX-HP-CANDIDATE").package
    e, g = pk.impact.electricity.saving_kwh, pk.impact.gas.saving_kwh
    assert pk.impact.carbon.total_kg == pytest.approx(e * factor("electricity") + g * factor("gas"), abs=0.2)


# --- Data quality --------------------------------------------------------------------------

def test_conflict_lowers_confidence_and_annotates_heating_advice(ctx):
    f = run(ctx, "FX-CONFLICT")
    assert f.confidence.level != "high"
    hp = rec(f, "air_source_heat_pump")
    assert any("conflicts with the meters" in u for u in hp.uncertainty)


def test_stale_epc_is_adjusted_and_labelled(ctx):
    base = dict(FIXTURES["FX-HP-CANDIDATE"]["property"])
    base.update(epc_year=2019, retrofits_completed=[{"measure_id": "solar_pv", "month": "2025-04"}], solar_pv_kwp=3.5)
    f = analyse_home(Property(**base), ctx)
    assert "stale_epc" in {c.code for c in f.conflicts}
    assert f.sap.basis == "estimated" and f.sap.value > base["sap_score"]


def test_missing_data_home_asks_the_right_questions(ctx):
    qs = run(ctx, "FX-MISSING-DATA").questions
    fields = [q.field for q in qs]
    assert fields[0] in ("sap_score", "meters")
    assert {"sap_score", "meters", "age_band"} <= set(fields)


# --- Memory constraints ---------------------------------------------------------------------

def test_declined_and_completed_measures_change_the_plan(ctx):
    f = run(ctx, "FX-POOR-SEMI", constraints={"declined_measures": ["air_source_heat_pump"],
                                              "completed_measures": ["loft_insulation"]})
    planned = {r.measure_id for r in f.plan}
    assert "air_source_heat_pump" not in planned and "loft_insulation" not in planned
    status = {e.measure_id: e.status for e in f.excluded}
    assert status["air_source_heat_pump"] == "declined"
    assert f.inputs["loft_insulation_mm"].value == 270


# --- Receipts and reproducibility -----------------------------------------------------------

def test_every_recommendation_and_package_has_a_receipt(ctx):
    f = run(ctx, "FX-POOR-SEMI")
    assert all(r.receipt.method and r.receipt.method_version for r in f.plan)
    assert all(c.receipt.method_version for c in f.score.components)
    assert f.package.receipt and f.package.improvement_potential.receipt
    json.dumps(f.model_dump(mode="json"))  # fully serialisable


def test_analysis_is_deterministic(ctx):
    a, b = run(ctx, "FX-POOR-SEMI"), run(ctx, "FX-POOR-SEMI")
    assert a.facts_id == b.facts_id
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


@pytest.mark.parametrize("over,status", [
    ({"property_type": "flat", "flat_position": "mid"}, "infeasible"),
    ({"property_type": "flat", "flat_position": None}, "needs_survey"),
    ({"property_type": "flat", "flat_position": "top", "roof_orientation": "south"}, "needs_survey"),
    ({"listed_or_conservation": True, "roof_orientation": "south"}, "needs_survey"),
])
def test_solar_consent_cases_are_check_first_not_ruled_out(over, status):
    """Only physical impossibility is 'infeasible'; consent or unknown facts are 'needs_survey' (check first)."""
    from greeniq.engines.retrofit import plan_candidates
    from greeniq.features.resolve import resolve_inputs
    p = Property(**{**FIXTURES["FX-POOR-SEMI"]["property"], **over})
    _, excl = plan_candidates(p, resolve_inputs(p), p.heating_system)
    assert {e.measure_id: e.status for e in excl}["solar_pv"] == status
