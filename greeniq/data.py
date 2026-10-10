"""Data layer: write/load the dataset, validate every record, split by customer, annualise.

Layout (all CSV so judges can open them):
    data/raw/        what a bank would hold: properties (recorded, with gaps and errors),
                     monthly meter reads, weather, sales, market index, retrofit history
    data/truth/      hidden simulator truth, read ONLY by the evaluation harness
    data/processed/  splits, annualised energy, validation report (all regenerable)
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError

from .contract import FUELS, MonthlyReading, Property
from .features.annualise import AnnualFuel, annualise_fuel

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
AS_OF = "2026-09"  # latest complete meter month in the dataset
SPLIT_SALT = "greeniq-split-v1"
SPLIT_FRACTIONS = (0.70, 0.15, 0.15)  # train / validation / test, by customer

RAW_TABLES = ["customers", "properties", "meter_readings", "weather", "weather_normals", "sales",
              "market_index", "retrofit_history"]
INT_FIELDS = {"loft_insulation_mm", "boiler_age_years", "sap_score", "epc_year"}
BOOL_FIELDS = {"wall_insulated", "has_loft", "floor_insulated", "has_gas_connection", "listed_or_conservation",
               "outdoor_space"}
PROPERTY_FIELDS = list(Property.model_fields)


def baseline_window(as_of: str = AS_OF) -> list[str]:
    return [str(p) for p in pd.period_range(end=as_of, periods=12, freq="M")]


def clean(v):
    """Pandas/numpy scalar → plain Python, NaN → None."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if math.isnan(v) else float(v)
    if v is pd.NA:
        return None
    return v


def assign_split(customer_id: str) -> str:
    """Deterministic, customer-level split: all of a customer's homes share one split."""
    h = int(hashlib.sha256(f"{SPLIT_SALT}:{customer_id}".encode()).hexdigest()[:12], 16) / 16**12
    train, val, _ = SPLIT_FRACTIONS
    return "train" if h < train else ("validation" if h < train + val else "test")


# ------------------------------------------------------------------------------------------
# Weather
# ------------------------------------------------------------------------------------------

class Weather:
    """Monthly heating degree days by region, and normal-year values."""

    def __init__(self, weather: pd.DataFrame, normals: pd.DataFrame):
        self._hdd = {(r, m): float(h) for r, m, h in weather[["region", "month", "hdd"]].itertuples(index=False)}
        self._normal = {(r, int(c)): float(h) for r, c, h in
                        normals[["region", "calendar_month", "hdd_normal"]].itertuples(index=False)}

    def hdd(self, region: str, months: list[str]) -> dict[str, float]:
        out = {}
        for m in months:
            v = self._hdd.get((region, m))
            out[m] = v if v is not None else self._normal[(region, int(m[5:7]))]
        return out

    def normal_year(self, region: str) -> float:
        return sum(self._normal[(region, c)] for c in range(1, 13))

    def normal_month(self, region: str, calendar_month: int) -> float:
        return self._normal[(region, calendar_month)]


def days_in(months: list[str]) -> dict[str, int]:
    return {m: pd.Period(m, freq="M").days_in_month for m in months}


def annualise_property(p: Property, weather: Weather, as_of: str = AS_OF) -> dict[str, AnnualFuel]:
    """Annual electricity and gas for a home, with explicit not-applicable/no-data states."""
    window = baseline_window(as_of)
    hdd = weather.hdd(p.region, window)
    days = days_in(window)
    normal = weather.normal_year(p.region)
    out: dict[str, AnnualFuel] = {}
    for fuel in FUELS:
        reads = {r.month: r.kwh for r in p.meter_readings if r.fuel == fuel and r.month in window}
        if fuel == "gas" and not reads:
            no_gas = p.has_gas_connection is False or (
                p.has_gas_connection is None and p.heating_system is not None
                and not p.heating_system.startswith("gas_boiler"))
            if no_gas:
                out[fuel] = AnnualFuel(fuel=fuel, status="not_applicable", annual_kwh=0.0, baseload_kwh=0.0,
                                       heating_kwh=0.0)
                continue
        out[fuel] = annualise_fuel(fuel, reads, window, hdd, normal, days)
    return out


# ------------------------------------------------------------------------------------------
# Dataset
# ------------------------------------------------------------------------------------------

@dataclass
class Dataset:
    root: Path
    tables: dict[str, pd.DataFrame]
    weather: Weather = field(init=False)
    _reads: dict[str, list[MonthlyReading]] = field(init=False, default_factory=dict)
    _props: dict[str, dict] = field(init=False, default_factory=dict)

    def __post_init__(self):
        self.weather = Weather(self.tables["weather"], self.tables["weather_normals"])
        mr = self.tables["meter_readings"]
        for pid, grp in mr.groupby("property_id", sort=False):
            self._reads[pid] = [MonthlyReading(month=m, fuel=f, kwh=clean(k))
                                for m, f, k in grp[["month", "fuel", "kwh"]].itertuples(index=False)]
        for row in self.tables["properties"].to_dict("records"):
            self._props[row["property_id"]] = row

    @property
    def property_ids(self) -> list[str]:
        return list(self._props)

    def record(self, pid: str) -> dict:
        row = {k: clean(v) for k, v in self._props[pid].items() if k in PROPERTY_FIELDS}
        for k in INT_FIELDS:
            if row.get(k) is not None:
                row[k] = int(row[k])
        for k in BOOL_FIELDS:
            if row.get(k) is not None:
                row[k] = bool(row[k]) if not isinstance(row[k], str) else row[k] == "True"
        return row

    def property(self, pid: str) -> Property:
        return Property(**self.record(pid), meter_readings=self._reads.get(pid, []))

    def retrofits(self, pid: str) -> list[dict]:
        rh = self.tables["retrofit_history"]
        return rh[rh["property_id"] == pid].to_dict("records")


def load_dataset(root: Path = DATA_DIR) -> Dataset:
    tables = {t: pd.read_csv(root / "raw" / f"{t}.csv") for t in RAW_TABLES}
    return Dataset(root=root, tables=tables)


def load_truth(root: Path = DATA_DIR) -> pd.DataFrame:
    """Hidden simulator truth. Only the evaluation harness may call this."""
    return pd.read_csv(root / "truth" / "hidden.csv")


def load_splits(root: Path = DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(root / "processed" / "splits.csv")


# ------------------------------------------------------------------------------------------
# Pipeline: write → validate → split → annualise
# ------------------------------------------------------------------------------------------

def write_world(world, root: Path = DATA_DIR) -> None:
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "truth").mkdir(parents=True, exist_ok=True)
    for t in RAW_TABLES:
        getattr(world, t).to_csv(root / "raw" / f"{t}.csv", index=False, encoding="utf-8")
    world.hidden.to_csv(root / "truth" / "hidden.csv", index=False, encoding="utf-8")


def validate(ds: Dataset) -> dict:
    """Validate every record through the contract and check integrity. Returns a report."""
    errors: list[dict] = []
    for pid in ds.property_ids:
        try:
            ds.property(pid)
        except ValidationError as e:
            errors.append({"property_id": pid, "error": str(e.errors()[0]["msg"])})
    props = ds.tables["properties"]
    mr = ds.tables["meter_readings"]
    known = set(props["property_id"])
    report = {
        "properties": int(len(props)),
        "customers": int(props["customer_id"].nunique()),
        "meter_rows": int(len(mr)),
        "meter_rows_missing_kwh": int(mr["kwh"].isna().sum()),
        "sales": int(len(ds.tables["sales"])),
        "retrofit_events": int(len(ds.tables["retrofit_history"])),
        "schema_errors": errors,
        "duplicate_property_ids": int(props["property_id"].duplicated().sum()),
        "duplicate_meter_rows": int(mr.duplicated(["property_id", "month", "fuel"]).sum()),
        "orphan_meter_rows": int((~mr["property_id"].isin(known)).sum()),
        "orphan_sales": int((~ds.tables["sales"]["property_id"].isin(known)).sum()),
        "negative_kwh": int((mr["kwh"] < 0).sum()),
        "field_missing_rate": {c: round(float(props[c].isna().mean()), 3) for c in PROPERTY_FIELDS
                               if c in props.columns and c != "meter_readings"},
    }
    report["passed"] = not (errors or report["duplicate_property_ids"] or report["duplicate_meter_rows"]
                            or report["orphan_meter_rows"] or report["orphan_sales"] or report["negative_kwh"])
    return report


def make_splits(ds: Dataset) -> pd.DataFrame:
    props = ds.tables["properties"][["property_id", "customer_id"]].copy()
    props["split"] = props["customer_id"].map(assign_split)
    return props


def annual_table(ds: Dataset, as_of: str = AS_OF) -> pd.DataFrame:
    rows = []
    for pid in ds.property_ids:
        p = ds.property(pid)
        for fuel, a in annualise_property(p, ds.weather, as_of).items():
            rows.append(dict(property_id=pid, fuel=fuel, status=a.status, annual_kwh=a.annual_kwh,
                             baseload_kwh=a.baseload_kwh, heating_kwh=a.heating_kwh, months_used=a.months_used,
                             months_missing=a.months_missing, r2=a.r2))
    return pd.DataFrame(rows)


def build_processed(root: Path = DATA_DIR) -> dict:
    ds = load_dataset(root)
    report = validate(ds)
    out = root / "processed"
    out.mkdir(parents=True, exist_ok=True)
    splits = make_splits(ds)
    splits.to_csv(out / "splits.csv", index=False)
    annual = annual_table(ds)
    annual.to_csv(out / "annual_energy.csv", index=False)
    report["split_counts"] = splits["split"].value_counts().to_dict()
    report["annualisation_status"] = {
        f: annual[annual.fuel == f]["status"].value_counts().to_dict() for f in FUELS
    }
    (out / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
