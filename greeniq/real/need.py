"""Real data: DESNZ National Energy Efficiency Data-Framework (NEED), anonymised 2026, 50,000 homes.

Source: https://www.gov.uk/government/statistics/national-energy-efficiency-data-framework-need-anonymised-data-2026
Licence: Open Government Licence v3.0. "Contains public sector information licensed under the Open
Government Licence v3.0." Files and SHA-256 checksums in data/real/need/.

Rules taken from the official metadata (data/real/need/need_metadata.ods):
- Gas is weather-corrected; electricity is not. Both are rounded to 100 kWh.
- Validity flag V = valid. E (estimated), L (too small), G (too large) and O (missing) are all
  treated as **missing**, never as zero. A blank gas flag means no gas meter was matched (usually
  not on the gas grid).
- MAIN_HEAT_FUEL 1 = gas is the main heating fuel; 2 = not.
- Years are meter years, not calendar years (e.g. electricity "2024" = Feb 2024–Jan 2025).

There are no property IDs, wall types, loft depths, glazing, controls, exact floor areas or prices.
Each row is a distinct property, so rows are split directly (no customer grouping is needed).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

import numpy as np
import pandas as pd

from ..data import ROOT

NEED_DIR = ROOT / "data" / "real" / "need"
NEED_FILE = NEED_DIR / "anon2026_50k.csv"
NEED_SHA256 = "5da6b2c1d6c2296f200a3ff3f8e3e05d2141fd40767e51cd5f3c57faa501b50b"
YEARS = list(range(2005, 2025))

AGE = {1: "before 1930", 2: "1930-1972", 3: "1973-1999", 4: "2000 or later"}
AREA = {1: "50 m² or less", 2: "51-100 m²", 3: "101-150 m²", 4: "151-200 m²", 5: "over 200 m²"}
AREA_MID = {1: 40.0, 2: 75.0, 3: 125.0, 4: 175.0, 5: 240.0}  # band midpoints (band 5: assumed)
REGION = {"E12000001": "North East", "E12000002": "North West", "E12000003": "Yorkshire and The Humber",
          "E12000004": "East Midlands", "E12000005": "West Midlands", "E12000006": "East",
          "E12000007": "London", "E12000008": "South East", "E12000009": "South West", "W92000004": "Wales"}
EPC_ORDER = ["F/G", "E", "D", "C", "A/B"]  # worst → best; "No EPC" kept as its own category


def checksum_ok() -> bool:
    return hashlib.sha256(NEED_FILE.read_bytes()).hexdigest() == NEED_SHA256


def _split(i: int) -> str:
    h = int(hashlib.sha256(f"need-split-v1:{i}".encode()).hexdigest()[:12], 16) / 16**12
    return "train" if h < 0.70 else ("validation" if h < 0.85 else "test")


@lru_cache(maxsize=1)
def load_need() -> pd.DataFrame:
    """Decoded NEED frame: one row per home, consumption NaN unless the flag is V."""
    raw = pd.read_csv(NEED_FILE, low_memory=False)
    d = pd.DataFrame({
        "need_row": np.arange(len(raw)),
        "property_type": raw["PROP_TYPE"],
        "age_band": raw["PROP_AGE_BAND"].map(AGE),
        "age_code": raw["PROP_AGE_BAND"],
        "area_band": raw["FLOOR_AREA_BAND"].map(AREA),
        "area_code": raw["FLOOR_AREA_BAND"],
        "area_mid_m2": raw["FLOOR_AREA_BAND"].map(AREA_MID),
        "region": raw["REGION"].map(REGION),
        "epc": raw["EPC"],
        "gas_main_heating": raw["MAIN_HEAT_FUEL"] == 1,
        "conservatory": raw["CONSERVATORY_FLAG"],
        "council_tax_band": raw["COUNCIL_TAX_BAND"],
        "loft_installed": raw["LI_FLAG"] == 1, "loft_year": raw["LI_DATE"],
        "cavity_installed": raw["CWI_FLAG"] == 1, "cavity_year": raw["CWI_DATE"],
        "pv_installed": raw["PV_FLAG"] == 1, "pv_year": raw["PV_DATE"],
        "gas_meter": raw[[f"GasValFlag{y}" for y in YEARS]].notna().any(axis=1),
    })
    for y in YEARS:
        d[f"gas_{y}"] = raw[f"Gcons{y}"].where(raw[f"GasValFlag{y}"] == "V")
        d[f"elec_{y}"] = raw[f"Econs{y}"].where(raw[f"ElecValFlag{y}"] == "V")
    d["split"] = [_split(i) for i in d["need_row"]]
    return d


def summary(d: pd.DataFrame | None = None) -> dict:
    d = load_need() if d is None else d
    return {
        "homes": int(len(d)), "checksum_ok": checksum_ok(),
        "split": d["split"].value_counts().to_dict(),
        "gas_main_heating": int(d["gas_main_heating"].sum()),
        "valid_2024": {"gas": int(d["gas_2024"].notna().sum()), "electricity": int(d["elec_2024"].notna().sum())},
        "median_2024": {"gas": float(d["gas_2024"].median()), "electricity": float(d["elec_2024"].median())},
        "installs": {"loft": int(d["loft_installed"].sum()), "cavity": int(d["cavity_installed"].sum()),
                     "solar_pv": int(d["pv_installed"].sum())},
        "epc": d["epc"].value_counts().to_dict(),
    }
