"""Models: leakage guards, promotion evidence, pipeline integration, value ranges, ranking."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from greeniq.context import load_context
from greeniq.contract import Property
from greeniq.data import ROOT, load_splits
from greeniq.engines.ranking import portfolio_row, rank_poor_homes
from greeniq.ml.features import FEATURES, FORBIDDEN, feature_frame, feature_row
from greeniq.ml.registry import load_card
from greeniq.pipeline import analyse_home

FIXTURES = {f["property"]["property_id"]: f for f in
            json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())}


@pytest.fixture(scope="module")
def ctx():
    return load_context(with_models=True)


@pytest.fixture(scope="module")
def card():
    return load_card()


def prop(pid, **over):
    d = dict(FIXTURES[pid]["property"])
    d.update(over)
    return Property(**d)


# --- Leakage ---------------------------------------------------------------------------------

def test_features_never_read_meters():
    p = prop("FX-POOR-SEMI")
    assert feature_row(p) == feature_row(p.model_copy(update={"meter_readings": []}))


def test_no_forbidden_feature_names():
    assert not (set(FEATURES) & FORBIDDEN)
    assert not any("price" in f or "kwh" in f or "value" in f for f in FEATURES)


def test_missing_values_stay_missing_not_zero():
    row = feature_row(prop("FX-MISSING-DATA"))
    assert np.isnan(row["age_index"]) and np.isnan(row["sap"]) and np.isnan(row["wall_insulated"])


def test_model_card_records_protocol_and_promotions(card):
    assert card["energy"]["rows"]["train"] > 0 and card["energy"]["rows"]["validation"] > 0
    for fuel in ("electricity", "gas"):
        val = card["energy"]["fuels"][fuel]["validation"]
        promoted = card["energy"]["promoted"][fuel]
        # whatever was promoted must have had the lowest validation MAE of the stored candidates
        assert val[promoted]["mae"] <= min(val["peer"]["mae"], val["gbm"]["mae"])
    cal = card["calibration"]
    assert cal["promoted"] == (cal["validation"]["calibrated"]["mae_total"] < cal["validation"]["uncalibrated"]["mae_total"])
    assert card["value"]["selection"].startswith("customer-grouped")
    assert any("test untouched" in c for c in card["leakage_controls"])


def test_value_cv_folds_are_grouped_by_customer():
    from sklearn.model_selection import GroupKFold
    sales = pd.read_csv(ROOT / "data" / "raw" / "sales.csv").merge(load_splits(), on="property_id")
    dev = sales[sales["split"] != "test"].reset_index(drop=True)
    for tr, te in GroupKFold(n_splits=5).split(dev, groups=dev["customer_id"]):
        assert not set(dev.loc[tr, "customer_id"]) & set(dev.loc[te, "customer_id"])


# --- Models inside the pipeline ---------------------------------------------------------------

def test_estimated_baseline_comes_from_the_promoted_model(ctx):
    f = analyse_home(prop("FX-MISSING-DATA"), ctx)
    assert f.baseline_basis == "estimated"
    assert f.baseline["gas"].provider.startswith("energy model")
    assert f.baseline["gas"].receipt.provider == f.baseline["gas"].provider


def test_calibration_shrinks_fabric_savings(ctx):
    engineering = analyse_home(prop("FX-HP-CANDIDATE"), load_context(with_models=False))
    calibrated = analyse_home(prop("FX-HP-CANDIDATE"), ctx)
    m = "cavity_wall_insulation"
    e = next(r for r in engineering.plan if r.measure_id == m).standalone.gas.saving_kwh
    c = next(r for r in calibrated.plan if r.measure_id == m).standalone.gas.saving_kwh
    assert ctx.calibration[m] < 1 and c < e


def test_value_is_a_range_with_caveat(ctx):
    v = analyse_home(prop("FX-POOR-SEMI"), ctx).value
    assert v.status == "available"
    lo, hi = v.uplift_pct_range
    assert lo <= hi and v.value_after_range[0] <= v.value_after_range[1]
    assert v.current_range[0] <= v.current_value <= v.current_range[1]
    assert "not proof" in v.caveat and "Indicative" in v.caveat
    assert v.band_before != v.band_after


def test_no_band_change_means_no_indicative_uplift(ctx):
    v = analyse_home(prop("FX-MID-FLAT"), ctx).value
    assert v.band_before == v.band_after and v.uplift_pct_range == (0.0, 0.0)
    assert "not expected to change" in v.reason


def test_value_unavailable_without_floor_area(ctx):
    v = analyse_home(prop("FX-POOR-SEMI", floor_area_m2=None), ctx).value
    assert v.status == "unavailable" and "Floor area" in v.reason


def test_models_never_break_the_pipeline(ctx):
    import dataclasses

    class Broken:
        name = "broken"

        def predict(self, *a):
            raise RuntimeError("boom")

        def estimate(self, *a):
            raise RuntimeError("boom")

    c = dataclasses.replace(ctx, energy_estimator=Broken(), value_model=Broken())
    f = analyse_home(prop("FX-MISSING-DATA"), c)
    assert f.baseline["gas"].provider == "physics estimate"  # fell back to the transparent baseline
    assert f.value.status == "unavailable"


# --- Ranking -----------------------------------------------------------------------------------

def test_ranking_orders_by_potential_and_separates_unavailable(ctx):
    rows = [portfolio_row(analyse_home(Property(**f["property"]), ctx)) for f in FIXTURES.values()]
    out = rank_poor_homes(rows)
    pcts = [r["potential_pct"] for r in out["ranked"]]
    assert pcts == sorted(pcts, reverse=True)
    assert all(r["is_poor"] for r in out["ranked"] + out["unavailable"])
    assert all(r["potential_status"] != "available" for r in out["unavailable"])
    assert rank_poor_homes(rows)["ranked"] == out["ranked"]  # deterministic


# --- Reports ---------------------------------------------------------------------------------

def test_held_out_predictions_are_test_split_only():
    preds = pd.read_csv(ROOT / "reports" / "test_predictions.csv")
    splits = load_splits().set_index("property_id")["split"]
    assert set(splits[preds["property_id"]]) == {"test"}
    schema = (ROOT / "reports" / "TEST_PREDICTIONS_SCHEMA.md").read_text(encoding="utf-8")
    for col in preds.columns:
        assert f"`{col}`" in schema, f"column {col} undocumented"


def test_feature_frame_matches_feature_order():
    X = feature_frame([prop("FX-POOR-SEMI"), prop("FX-MID-FLAT")])
    assert list(X.columns) == FEATURES and len(X) == 2
