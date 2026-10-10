"""Grounded AI: the gate blocks what it must, passes honest text, and the app never depends on a model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from greeniq.api import create_app
from greeniq.context import load_context
from greeniq.contract import Property
from greeniq.pipeline import analyse_home
from greeniq.trust import narrator
from greeniq.trust.assistant import interpret
from greeniq.trust.gate import check
from greeniq.trust.narrator import explain, explain_home, explain_package

FIXTURES = {f["property"]["property_id"]: f for f in
            json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())}


@pytest.fixture(scope="module")
def ctx():
    return load_context()


@pytest.fixture(scope="module")
def hp(ctx):
    return analyse_home(Property(**FIXTURES["FX-HP-CANDIDATE"]["property"]), ctx)


# --- the gate ---------------------------------------------------------------------------------

@pytest.mark.parametrize("pid", list(FIXTURES))
def test_honest_template_explanations_always_pass(ctx, pid):
    f = analyse_home(Property(**FIXTURES[pid]["property"]), ctx)
    assert check(explain_home(f).text, f, "home").passed
    if f.package:
        assert check(explain_package(f).text, f, "package").passed


def test_invented_number_is_blocked(hp):
    g = check(explain_package(hp).text + " It also saves 4,321 kWh a year on top.", hp, "package")
    assert not g.passed and any(v.kind == "unsupported_number" for v in g.violations)


def test_change_claim_cannot_borrow_a_baseline_number(hp):
    """'Saves X' must match a saving, not an unrelated level that happens to equal X."""
    base = hp.package.impact.gas.baseline_kwh
    g = check(f"This package cuts gas by {base:,.0f} kWh a year.", hp, "package")
    assert not g.passed
    ok = check(f"Today the home uses {base:,.0f} kWh of gas a year.", hp, "package")
    assert ok.passed


def test_flipped_fuel_direction_is_blocked(hp):
    e = abs(hp.package.impact.electricity.saving_kwh)
    assert hp.package.impact.electricity.saving_kwh < 0  # the heat pump raises electricity
    g = check(f"This package cuts electricity by {e:,.0f} kWh a year.", hp, "package")
    assert any(v.kind == "wrong_direction" for v in g.violations)


def test_causal_value_promise_is_blocked(hp):
    g = check("This will increase your home's value.", hp, "package")
    assert any(v.kind == "causal_claim" for v in g.violations)


def test_off_scenario_measure_is_blocked(ctx):
    f = analyse_home(Property(**FIXTURES["FX-MID-FLAT"]["property"]), ctx)
    g = check(explain_package(f).text + " Adding solar panels would help too.", f, "package")
    assert any(v.kind == "scenario_mismatch" for v in g.violations)


def test_wrong_unit_is_blocked(hp):
    pct = hp.package.improvement_potential.pct
    g = check(f"It cuts gas by {pct:.1f} kWh.", hp, "package")
    assert not g.passed


# --- narrator: model optional, gated, falls back --------------------------------------------

def test_no_key_means_template_and_gated(hp, monkeypatch):
    monkeypatch.setenv("GREENIQ_LLM", "off")
    e = explain(hp, "package")
    assert e.mode == "template" and e.gate["passed"]


def test_model_text_that_fails_the_gate_is_never_shown(hp, monkeypatch):
    monkeypatch.setattr("greeniq.trust.llm.generate",
                        lambda f, scope: ("Electricity falls by 9,999 kWh and your home will be worth more.", "fake"))
    e = explain(hp, "package")
    assert e.mode == "template" and "blocked" in e.note
    assert "9,999" not in e.text


def test_model_text_that_passes_is_shown(hp, monkeypatch):
    honest = explain_package(hp).text
    monkeypatch.setattr("greeniq.trust.llm.generate", lambda f, scope: (honest, "fake-model"))
    e = explain(hp, "package")
    assert e.mode == "llm" and e.gate["passed"]


def test_model_failure_falls_back(hp, monkeypatch):
    monkeypatch.setattr("greeniq.trust.llm.generate", lambda f, scope: (None, "language model unreachable"))
    e = explain(hp, "package")
    assert e.mode == "template" and e.note == "language model unreachable"
    assert narrator  # module imported


# --- what-if assistant -----------------------------------------------------------------------

def test_assistant_parses_without_computing(hp):
    it = interpret("What if I only add a heat pump?", hp)
    assert it.understood and it.measures == ["air_source_heat_pump"]
    it = interpret("What if I do everything but skip the solar panels?", hp)
    assert it.understood and "solar_pv" in it.declined
    assert not interpret("will it rain tomorrow?", hp).understood


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def test_ask_reruns_engine_and_explanation_matches_fresh_run(client):
    pid = "P00007"
    r = client.post(f"/api/properties/{pid}/ask", json={"question": "What if I only add a heat pump?"}).json()
    assert r["interpretation"]["understood"]
    facts = r["facts"]
    assert facts["package"]["measures"] == ["air_source_heat_pump"]
    assert facts["package"]["impact"]["electricity"]["saving_kwh"] < 0 < facts["package"]["impact"]["gas"]["saving_kwh"]
    direct = client.post(f"/api/properties/{pid}/scenarios", json={"measures": ["air_source_heat_pump"]}).json()
    assert direct["facts"]["package"]["impact"] == facts["package"]["impact"]
    assert r["explanation"]["gate"]["passed"]


def test_infeasible_what_if_is_refused_not_invented(client):
    flat = next(p for p in client.get("/api/properties?limit=500").json()["items"] if p.get("property_type") == "flat")
    r = client.post(f"/api/properties/{flat['property_id']}/ask", json={"question": "What if I only add solar panels?"}).json()
    if r["facts"] is not None:
        assert r["facts"]["package"] is None or "solar_pv" not in r["facts"]["package"]["measures"]


def test_gate_demo_passes_honest_and_blocks_corruptions(client):
    cases = client.get("/api/properties/P00007/gate-demo").json()["cases"]
    assert cases[0]["gate"]["passed"]
    assert all(not c["gate"]["passed"] for c in cases[1:])
