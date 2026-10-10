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
