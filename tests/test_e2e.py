"""End to end through the API, one home per PS2 scenario test: report → lab → what-if → explanation."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from greeniq.api import create_app
from greeniq.data import ROOT


def _pick() -> dict[str, str]:
    a = pd.read_csv(ROOT / "data" / "processed" / "annual_energy.csv")
    st = a.pivot(index="property_id", columns="fuel", values="status")
    pick = {
        "missing_meters": st[st["gas"].isin(["insufficient", "no_data"])].index[0],
        "zero_use": st[(st["electricity"] == "zero") & (st["gas"] == "zero")].index[0],
        "all_electric": st[st["gas"] == "not_applicable"].index[0],
        "well_metered": st[(st["electricity"] == "metered_full") & (st["gas"] == "metered_full")].index[0],
    }
    hid = pd.read_csv(ROOT / "data" / "truth" / "hidden.csv")
    pick["conflict"] = hid[hid["recorded_heating_error"]]["property_id"].iloc[0]
    return pick


HOMES = _pick()


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("case", list(HOMES))
def test_full_journey_is_consistent_and_grounded(client, case):
    pid = HOMES[case]
    rep = client.get(f"/api/properties/{pid}").json()
    f, ex = rep["facts"], rep["explanation"]
    assert ex["gate"]["passed"]
    assert len(f["next_best_action"]["reasons"]) == 3
    planned = {r["measure_id"] for r in f["plan"]}

    lab = client.get(f"/api/properties/{pid}/lab").json()
    assert all(set(o["measures"]) <= planned for o in lab["packages"])

    sc = client.post(f"/api/properties/{pid}/scenarios", json={"measures": sorted(planned)}).json()
    assert sc["explanation"]["gate"]["passed"]
    if f["package"]:
        assert sc["facts"]["package"]["impact"] == f["package"]["impact"]  # same package, same numbers

    if case == "missing_meters":
        assert f["baseline_basis"] == "estimated"
        assert f["package"] is None or f["package"]["improvement_potential"]["status"] == "unavailable"
    if case == "zero_use":
        assert f["intensity_kwh_m2"]["value"] is None
        assert f["package"] is None or f["package"]["improvement_potential"]["pct"] is None
    if case == "conflict":
        assert "heating_system_vs_gas_use" in {c["code"] for c in f["conflicts"]}
    if case == "all_electric":
        assert f["baseline"]["gas"]["basis"] == "not_applicable"


def test_heat_pump_what_if_raises_electricity_end_to_end(client):
    pid = HOMES["well_metered"]
    r = client.post(f"/api/properties/{pid}/ask", json={"question": "What if I only add a heat pump?"}).json()
    if r["facts"] and r["facts"]["package"]:
        im = r["facts"]["package"]["impact"]
        assert im["electricity"]["saving_kwh"] < 0 < im["gas"]["saving_kwh"]
        assert r["explanation"]["gate"]["passed"]


def test_unknown_home_and_bad_input_give_structured_errors(client):
    assert client.get("/api/properties/NOPE").status_code == 404
    r = client.post("/api/properties/P00007/ask", json={"question": "x" * 400})
    assert r.status_code == 422 and "error" in r.json()
