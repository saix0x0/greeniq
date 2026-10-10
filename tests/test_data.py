"""Data pipeline: determinism, validation, leakage-safe splits, annualisation."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import pytest

from greeniq.contract import Property
from greeniq.data import (
    DATA_DIR, annualise_property, assign_split, baseline_window, load_dataset, load_splits, make_splits, validate,
)
from greeniq.simulator.world import generate_world

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())


@pytest.fixture(scope="module")
def ds():
    return load_dataset()


def fixture(pid: str) -> dict:
    return next(f for f in FIXTURES if f["property"]["property_id"] == pid)


# --- Reproducibility --------------------------------------------------------------------

def test_generation_is_deterministic_for_a_seed():
    a, b = generate_world(120, seed=11), generate_world(120, seed=11)
    pd.testing.assert_frame_equal(a.properties, b.properties)
    pd.testing.assert_frame_equal(a.meter_readings, b.meter_readings)
    pd.testing.assert_frame_equal(a.sales, b.sales)
    c = generate_world(120, seed=12)
    assert not a.properties.equals(c.properties)


# --- Validation ---------------------------------------------------------------------------

def test_committed_dataset_validates(ds):
    report = validate(ds)
    assert report["passed"], report["schema_errors"][:3]
    assert report["duplicate_meter_rows"] == 0 and report["orphan_meter_rows"] == 0


def test_every_fixture_is_a_valid_property():
    for f in FIXTURES:
        Property(**f["property"])


# --- Splits: grouped by customer, no leakage --------------------------------------------

def test_split_is_by_customer_and_disjoint():
    splits = load_splits()
    per_customer = splits.groupby("customer_id")["split"].nunique()
    assert (per_customer == 1).all(), "a customer's homes span more than one split"
    assert splits["property_id"].is_unique
    sets = {s: set(g["customer_id"]) for s, g in splits.groupby("split")}
    assert not (sets["train"] & sets["test"]) and not (sets["train"] & sets["validation"])
    assert not (sets["validation"] & sets["test"])


def test_split_fractions_close_to_configured():
    frac = load_splits()["split"].value_counts(normalize=True)
    assert abs(frac["train"] - 0.70) < 0.05 and abs(frac["test"] - 0.15) < 0.05


def test_split_assignment_is_stable(ds):
    assert assign_split("C00001") == assign_split("C00001")
    regenerated = make_splits(ds)
    pd.testing.assert_frame_equal(regenerated.reset_index(drop=True), load_splits())


# --- Annualisation ------------------------------------------------------------------------

def test_annualisation_recovers_the_true_degree_day_model(ds):
    f = fixture("FX-POOR-SEMI")
    p = Property(**f["property"])
    out = annualise_property(p, ds.weather)
    for fuel, ab in f["true_model"].items():
        expected = ab["a"] * 365 + ab["b"] * ds.weather.normal_year(p.region)
        assert out[fuel].status == "metered_full"
        assert out[fuel].annual_kwh == pytest.approx(expected, rel=0.01)
        assert out[fuel].heating_kwh == pytest.approx(ab["b"] * ds.weather.normal_year(p.region), rel=0.01)


def test_missing_months_are_not_zero_filled(ds):
    f = fixture("FX-POOR-SEMI")
    full = Property(**f["property"])
    drop = set(baseline_window()[2:5])
    reads = [r for r in f["property"]["meter_readings"] if not (r["fuel"] == "gas" and r["month"] in drop)]
    gappy = Property(**{**f["property"], "meter_readings": reads})
    a_full = annualise_property(full, ds.weather)["gas"]
    a_gap = annualise_property(gappy, ds.weather)["gas"]
    assert a_gap.status == "metered_partial" and a_gap.months_missing == 3
    assert a_gap.annual_kwh == pytest.approx(a_full.annual_kwh, rel=0.02)
    naive_sum = sum(r["kwh"] for r in reads if r["fuel"] == "gas")
    assert a_gap.annual_kwh > naive_sum * 1.05  # a zero-fill would have under-counted


def test_too_few_months_is_insufficient_not_a_guess(ds):
    out = annualise_property(Property(**fixture("FX-MISSING-DATA")["property"]), ds.weather)
    assert out["gas"].status == "insufficient" and out["gas"].annual_kwh is None


def test_zero_reads_give_zero_baseline(ds):
    out = annualise_property(Property(**fixture("FX-VOID-ZERO")["property"]), ds.weather)
    assert out["gas"].status == "zero" and out["electricity"].annual_kwh == 0.0


def test_home_without_gas_is_not_applicable_not_missing(ds):
    out = annualise_property(Property(**fixture("FX-MID-FLAT")["property"]), ds.weather)
    assert out["gas"].status == "not_applicable" and out["gas"].annual_kwh == 0.0


# --- Architecture guard: engines must never see the simulator's hidden truth ------------

def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Name) and node.id == "load_truth":
            names.add("load_truth")
    return names


def test_product_code_never_imports_the_simulator_or_truth():
    pkg = Path(__file__).resolve().parents[1] / "greeniq"
    allowed = {"cli.py", "data.py"}  # cli generates data; data.py defines (not calls) load_truth
    offenders = []
    for py in pkg.rglob("*.py"):
        rel = py.relative_to(pkg)
        if rel.parts[0] in ("simulator", "evaluation") or rel.name in allowed:
            continue
        imps = _imports(py)
        if any("simulator" in i for i in imps) or "load_truth" in imps:
            offenders.append(str(rel))
    assert not offenders, f"product code touching hidden truth: {offenders}"
