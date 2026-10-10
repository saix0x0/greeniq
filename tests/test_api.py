"""API: routes read ComputedFacts, a what-if reruns the engine, errors share one shape."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from greeniq.api import create_app


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def test_health_and_one_port_ui(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["homes"] == 3000 and h["engine_key"]
    assert "GreenIQ" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_portfolio_kpis_are_consistent_with_rows(client):
    p = client.get("/api/portfolio").json()
    assert sum(p["band_distribution"]["all"].values()) == p["n_homes"]
    assert sum(p["triage"].values()) == p["n_homes"]
    op = p["kpis"]["opportunity"]
    assert op["gwh"] == pytest.approx(op["gas_gwh"] + op["electricity_gwh"], abs=0.02)
    assert op["electricity_gwh"] < 0 < op["gas_gwh"]  # heat pumps: electricity up, gas down


def test_search_filters(client):
    r = client.get("/api/properties?band=Poor&region=north&limit=500").json()
    assert r["total"] > 0 and all(x["band"] == "Poor" and x["region"] == "north" for x in r["items"])
    refer = client.get("/api/properties?disposition=refer_for_survey&limit=500").json()
    assert all(x["nba_disposition"] == "refer_for_survey" for x in refer["items"])


def test_property_report_has_facts_nba_and_grounded_explanation(client):
    r = client.get("/api/properties/P00007").json()
    f = r["facts"]
    assert f["property_id"] == "P00007" and f["next_best_action"]["reasons"]
    assert len(f["score"]["components"]) == 7
    assert f["baseline_emissions_kg"]["value"] > 0
    assert all(s["refs"] for s in r["explanation"]["sentences"])


def test_what_if_reruns_the_engine(client):
    base = client.get("/api/properties/P00007").json()["facts"]
    r = client.post("/api/properties/P00007/scenarios", json={"measures": ["air_source_heat_pump"]}).json()
    f = r["facts"]
    assert f["facts_id"] != base["facts_id"]
    assert f["scenario"]["modelled"] == ["air_source_heat_pump"]
    im = f["package"]["impact"]
    assert im["electricity"]["saving_kwh"] < 0 < im["gas"]["saving_kwh"]
    assert set(f["package"]["components_after"]) == {c["key"] for c in base["score"]["components"]}
    assert "raises electricity" in " ".join(s["text"] for s in r["explanation"]["sentences"])


def test_infeasible_measure_is_rejected_with_a_reason_not_an_error(client):
    r = client.post("/api/properties/P00007/scenarios", json={"measures": ["solar_pv"]})
    assert r.status_code == 200
    f = r.json()["facts"]
    assert f["package"] is None and f["scenario"]["rejected"][0]["measure_id"] == "solar_pv"


def test_uniform_errors(client):
    e = client.get("/api/properties/NOPE")
    assert e.status_code == 404 and e.json()["error"]["code"] == "unknown_property"
    e = client.post("/api/properties/P00007/scenarios", json={"measures": ["jetpack"]})
    assert e.status_code == 422 and e.json()["error"]["code"] == "invalid_request"
    e = client.get("/api/properties/P00007/next-best-action?objective=fastest")
    assert e.status_code == 422 and "objective" in e.json()["error"]["message"]


def test_objective_changes_the_selection_basis(client):
    n = client.get("/api/properties/P00007/next-best-action?objective=carbon").json()
    assert n["objective"] == "carbon" and n["benefit_unit"] == "kg CO2e/yr"


def test_group_summaries_cover_every_ps2_output_and_add_up(client):
    rows = client.get("/api/properties?limit=500").json()["total"]
    for by in ("region", "property_type", "age_band", "heating_system", "epc_band", "band", "baseline_basis"):
        g = client.get(f"/api/portfolio/groups?by={by}").json()
        assert sum(x["homes"] for x in g["groups"]) == rows
        x = g["groups"][0]
        for k in ("avg_score", "poor_pct", "median_potential_pct", "electricity_saving_mwh", "gas_saving_mwh",
                  "carbon_saving_t", "median_uplift_pct"):
            assert k in x
    assert client.get("/api/portfolio/groups?by=nonsense").status_code == 422


def test_compare_by_ids_keeps_the_requested_order(client):
    r = client.get("/api/properties?ids=P00007,P00004,P99999").json()
    assert [x["property_id"] for x in r["items"]] == ["P00007", "P00004"]
    assert {"issues", "value_uplift_pct_low", "heating_system"} <= set(r["items"][0])


def test_evidence_exposes_formulas_assumptions_and_validation(client):
    e = client.get("/api/evidence").json()
    assert abs(sum(e["score"]["weights"].values()) - 1) < 1e-12
    assert all("value" in a and "source" in a for a in e["assumptions"]["items"].values())
    assert e["calibration"]["sources"]["cavity_wall_insulation"].startswith("real UK homes")
    assert e["metrics"] is None or "validation" in e["metrics"]


def test_explain_endpoint_is_gated_and_works_with_ai_off(client):
    for scope in ("home", "package"):
        r = client.get(f"/api/properties/P00007/explain?scope={scope}").json()
        ex = r["explanation"]
        assert ex["gate"]["passed"] and ex["mode"] == "template"  # tests run with GREENIQ_LLM=off
        assert r["provider"]["name"] == "off"
    assert client.get("/api/properties/P00007/explain?scope=bogus").status_code == 422


def test_explain_endpoint_uses_the_model_when_one_is_configured(client, monkeypatch):
    from greeniq.trust import llm
    monkeypatch.setattr(llm, "provider", lambda: ("ollama", "fake-model behind the grounding gate"))
    monkeypatch.setattr(llm, "generate", lambda f, scope, st=None: ("Most of the gain comes from keeping heat in.", "fake-model"))
    monkeypatch.setattr("greeniq.api.llm_provider", llm.provider)
    r = client.get("/api/properties/P00004/explain?scope=home").json()
    assert r["explanation"]["mode"] == "llm" and r["explanation"]["gate"]["passed"]
    assert r["explanation"]["sentences"][0]["text"].startswith("Most of the gain")


def test_priority_tiers_follow_the_documented_rule(client):
    p = client.get("/api/portfolio").json()
    assert sum(t["homes"] for t in p["tiers"]) == p["n_homes"]
    for tier in ("act_now", "check_first", "worth_doing", "no_action"):
        for x in client.get(f"/api/properties?tier={tier}&limit=50").json()["items"]:
            assert x["tier"] == tier
            if tier == "act_now":
                assert x["is_poor"] and x["nba_disposition"] == "recommend"
            if tier == "check_first":
                assert x["nba_disposition"] == "refer_for_survey"
    items = client.get("/api/properties?sort=priority&limit=500").json()["items"]
    order = ["act_now", "check_first", "worth_doing", "no_action"]
    assert [order.index(x["tier"]) for x in items] == sorted(order.index(x["tier"]) for x in items)


def test_standing_is_a_mid_rank_percentile(client):
    s = client.get("/api/properties/P00007/standing").json()
    assert s["available"] and 0 <= s["all"]["percentile"] <= 100 and s["all"]["homes"] > 1000
    rng = client.get("/api/properties/P00004/standing").json()
    assert rng["available"] is False  # a score range is never ranked


def test_alternatives_say_why_they_lost(client):
    nba = client.get("/api/properties/P00007").json()["facts"]["next_best_action"]
    ranked = [a for a in nba["alternatives"] if a["benefit"] is not None]
    assert ranked and all(" vs " in a["why_not_first"] for a in ranked)
