"""Real data (DESNZ NEED): loading rules, leakage-free splits, benchmarks and evidence inside the product."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from greeniq.data import ROOT
from greeniq.real import benchmarks as B
from greeniq.real.need import NEED_FILE, checksum_ok, load_need


@pytest.fixture(scope="module")
def need():
    return load_need()


def test_file_is_the_published_one():
    assert checksum_ok()


def test_invalid_readings_are_missing_not_zero(need):
    raw = pd.read_csv(NEED_FILE, usecols=["Gcons2024", "GasValFlag2024", "Econs2024", "ElecValFlag2024"])
    not_valid = raw["GasValFlag2024"] != "V"
    assert need.loc[not_valid.values, "gas_2024"].isna().all()  # E, L, G, O and blank never become numbers
    assert (need["gas_2024"].dropna() > 0).all() and (need["elec_2024"].dropna() > 0).all()
    assert need["gas_2024"].notna().sum() == (raw["GasValFlag2024"] == "V").sum()


def test_splits_are_disjoint_and_stable(need):
    assert set(need["split"]) == {"train", "validation", "test"}
    assert need["need_row"].is_unique
    assert load_need()["split"].tolist() == need["split"].tolist()
    assert abs((need["split"] == "train").mean() - 0.70) < 0.02


def test_no_deprivation_feature_in_the_real_model():
    from greeniq.real.evidence import FEATURES
    assert not any("imd" in f.lower() for f in FEATURES)
    import re
    assert not any(re.fullmatch(r"(gas|elec)_20\d\d", f) for f in FEATURES)  # consumption is the target, not a feature


def test_benchmarks_file_is_built_from_train_only():
    b = json.loads(B.BENCH_FILE.read_text())
    assert "train split" in b["source"]
    for fuel in ("gas", "electricity"):
        assert all(c["n"] >= 30 for c in b["peers"][fuel].values())
        assert all(c["q"] == sorted(c["q"]) for c in b["peers"][fuel].values())


def test_percentile_rises_with_use():
    lo = B.compare("semi_detached", 90, "1945_1964", {"gas": (6000, "metered")})
    hi = B.compare("semi_detached", 90, "1945_1964", {"gas": (16000, "metered")})
    assert lo.fuels[0].percentile < hi.fuels[0].percentile


def test_low_use_is_a_signal_not_a_diagnosis():
    c = B.compare("detached", 180, "1965_1980", {"gas": (2000, "metered")})
    assert c.fuels[0].flag == "much_lower"
    assert "not proven" in c.signals[0] and "smaller" in c.signals[0]


def test_unmetered_baseline_is_not_compared():
    assert B.compare("flat", 60, "1981_2002", {"gas": (9000, "estimated"), "electricity": (None, "unavailable")}) is None


def test_product_shows_real_evidence_and_peers():
    from greeniq.context import load_context
    from greeniq.data import load_dataset
    from greeniq.pipeline import analyse_home

    f = analyse_home(load_dataset().property("P00007"), load_context())
    assert f.peer is not None and f.peer.fuels[0].n_peers >= 30
    loft = next(r for r in f.plan if r.measure_id == "loft_insulation")
    assert loft.real_evidence and "DESNZ NEED" in loft.real_evidence
    assert all(r.real_evidence is None for r in f.plan if r.measure_id not in B.MEASURE_KEY)


def test_real_data_report_exists_and_is_labelled():
    md = (ROOT / "reports" / "REAL_DATA.md").read_text()
    assert "real homes" in md and "Open Government Licence" in md
