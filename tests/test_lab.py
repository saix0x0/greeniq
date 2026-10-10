"""Decision Lab: real feasible packages, honest plans, consistent numbers, per-output interactions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from greeniq.context import load_context
from greeniq.contract import Property
from greeniq.facts import Scenario
from greeniq.lab import MIN_SHARE, decision_lab
from greeniq.pipeline import analyse_home

FIXTURES = {f["property"]["property_id"]: Property(**f["property"]) for f in
            json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())}
FABRIC = {"loft_insulation", "cavity_wall_insulation", "solid_wall_insulation", "glazing_upgrade"}


@pytest.fixture(scope="module")
def ctx():
    return load_context(with_models=False)


@pytest.fixture(scope="module")
def semi(ctx):
    return decision_lab(FIXTURES["FX-POOR-SEMI"], ctx, budget=10000)


def test_every_package_is_a_feasible_subset_and_all_are_enumerated(ctx, semi):
    base = analyse_home(FIXTURES["FX-POOR-SEMI"], ctx)
    feasible = {r.measure_id for r in base.plan}
    assert all(set(o.measures) <= feasible for o in semi.packages)
    assert len(semi.packages) == 2 ** len(feasible) - 1


def test_named_plans_follow_their_definitions(semi):
    by = {o.key: o for o in semi.packages}
    plans = {p.id: by[p.package_key] for p in semi.plans if p.package_key}
    ok = [o for o in semi.packages if o.respects_prerequisites and o.carbon_kg > 0]
    assert all(o.respects_prerequisites for o in plans.values())
    assert plans["greenest"].carbon_kg == max(o.carbon_kg for o in ok)
    assert plans["my_budget"].cost_high <= semi.budget
    assert plans["my_budget"].carbon_kg == max(o.carbon_kg for o in ok if o.cost_high <= semi.budget)
    floor = MIN_SHARE * plans["greenest"].carbon_kg
    assert plans["lowest_cost"].carbon_kg >= floor and plans["lowest_cost"].pareto_carbon
    assert plans["best_value"].carbon_kg >= floor


def test_pareto_points_are_not_dominated(semi):
    ok = [o for o in semi.packages if o.respects_prerequisites]
    for o in (o for o in ok if o.pareto_carbon):
        assert not any(q.cost_mid <= o.cost_mid and q.carbon_kg >= o.carbon_kg
                       and (q.cost_mid < o.cost_mid or q.carbon_kg > o.carbon_kg) for q in ok)


def test_heat_pump_without_fabric_is_flagged_not_hidden(semi):
    hp_alone = next(o for o in semi.packages if o.measures == ["air_source_heat_pump"])
    assert not hp_alone.respects_prerequisites and hp_alone.missing_prerequisites


def test_selected_plan_numbers_match_a_fresh_engine_run(ctx, semi):
    """Choosing a plan must update Sankey, per-fuel figures, carbon and cost consistently."""
    by = {o.key: o for o in semi.packages}
    for p in semi.plans:
        o = by[p.package_key]
        f = analyse_home(FIXTURES["FX-POOR-SEMI"], ctx, Scenario(measures=o.measures))
        pk = f.package
        assert (pk.cost_low, pk.cost_high) == (o.cost_low, o.cost_high)
        assert pk.impact.carbon.total_kg == o.carbon_kg
        assert pk.impact.electricity.saving_kwh == o.electricity_saving_kwh
        grid = sum(x.kwh for x in pk.flows_after if x.source == "Grid electricity")
        gas = sum(x.kwh for x in pk.flows_after if x.source == "Gas")
        n = len(pk.flows_after)
        assert abs(grid - pk.impact.electricity.after_kwh) <= 10 * n
        assert abs(gas - pk.impact.gas.after_kwh) <= 10 * n


def test_interactions_are_paired_runs_per_output(semi):
    by = {o.key: o for o in semi.packages}
    i = next(x for x in semi.interactions if x.a == "loft_insulation" and x.b == "air_source_heat_pump")
    joint = by["loft_insulation+air_source_heat_pump"]
    assert i.net_kwh == round(joint.net_saving_kwh - by["loft_insulation"].net_saving_kwh
                              - by["air_source_heat_pump"].net_saving_kwh)
    assert i.net_kwh < 0  # insulating first leaves less heat for the heat pump to save


def test_fabric_pairs_are_never_super_additive(ctx):
    """Regression: with realisation < 1, sequential fabric savings used to exceed the sum."""
    for pid in ("FX-POOR-SEMI", "FX-HP-CANDIDATE"):
        lab = decision_lab(FIXTURES[pid], ctx)
        for i in lab.interactions:
            if i.a in FABRIC and i.b in FABRIC:
                assert i.net_kwh <= 20, (pid, i)


def test_sensitivity_flags_fragile_decisions_from_assumed_inputs(ctx):
    lab = decision_lab(FIXTURES["FX-MISSING-DATA"], ctx)
    assert lab.sensitivity, "assumed inputs should be varied"
    for r in lab.sensitivity:
        assert r.fragile == (r.nba_changes or r.package_changes)
        assert r.basis in ("assumed", "missing", "estimated")
    assert any(r.input == "savings_realisation" for r in lab.sensitivity)


def test_no_plan_for_a_home_with_nothing_feasible(ctx):
    lab = decision_lab(FIXTURES["FX-LARGE-EFFICIENT"], ctx)
    assert lab.packages == [] and all(p.package_key is None for p in lab.plans)


def test_lab_endpoint(ctx):
    from fastapi.testclient import TestClient

    from greeniq.api import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/properties/P00007/lab?budget=8000")
        assert r.status_code == 200
        body = r.json()
        assert body["budget"] == 8000 and len(body["plans"]) == 4
        assert c.get("/api/properties/P00007/lab?budget=-5").json()["error"]["code"] == "invalid_request"
