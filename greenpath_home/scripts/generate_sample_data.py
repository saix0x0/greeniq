#!/usr/bin/env python3
"""Generate small synthetic CSV files for the first scoring prototype."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "sample"


PROPERTIES = [
    {
        "property_id": "P10001",
        "property_type": "terraced",
        "age_band": "pre_1930",
        "floor_area_m2": 82,
        "bedrooms": 3,
        "energy_rating": "E",
        "heating": "gas_boiler",
        "insulation": "poor",
        "glazing": "single",
        "solar": "false",
        "smart_controls": "false",
        "region": "London",
        "current_value_gbp": 350000,
    },
    {
        "property_id": "P10002",
        "property_type": "semi-detached",
        "age_band": "1980_1999",
        "floor_area_m2": 110,
        "bedrooms": 4,
        "energy_rating": "C",
        "heating": "modern_gas_boiler",
        "insulation": "good",
        "glazing": "double",
        "solar": "true",
        "smart_controls": "true",
        "region": "North West",
        "current_value_gbp": 285000,
    },
    {
        "property_id": "P10003",
        "property_type": "flat",
        "age_band": "post_2012",
        "floor_area_m2": 62,
        "bedrooms": 2,
        "energy_rating": "B",
        "heating": "district_heating",
        "insulation": "excellent",
        "glazing": "triple",
        "solar": "false",
        "smart_controls": "true",
        "region": "South East",
        "current_value_gbp": 310000,
    },
    {
        "property_id": "P10004",
        "property_type": "detached",
        "age_band": "1930_1949",
        "floor_area_m2": 165,
        "bedrooms": 5,
        "energy_rating": "F",
        "heating": "oil_boiler",
        "insulation": "none",
        "glazing": "single",
        "solar": "false",
        "smart_controls": "false",
        "region": "South West",
        "current_value_gbp": 520000,
    },
]


MONTHLY_USAGE = {
    "P10001": (390, 980),
    "P10002": (310, 620),
    "P10003": (240, 0),
    "P10004": (560, 1850),
}


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_properties()
    write_energy_usage()
    write_emissions_factors()
    print(f"Wrote sample data to {DATA_DIR}")


def write_properties() -> None:
    path = DATA_DIR / "properties.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(PROPERTIES[0].keys()))
        writer.writeheader()
        writer.writerows(PROPERTIES)


def write_energy_usage() -> None:
    path = DATA_DIR / "energy_usage.csv"
    fieldnames = ["property_id", "month", "electricity_kwh", "gas_kwh"]
    months = [f"2026-{month:02d}" for month in range(1, 13)]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for property_id, (base_electricity, base_gas) in MONTHLY_USAGE.items():
            for index, month in enumerate(months):
                winter_factor = 1.25 if index in {0, 1, 10, 11} else 0.9
                writer.writerow(
                    {
                        "property_id": property_id,
                        "month": month,
                        "electricity_kwh": round(base_electricity * (0.96 + index * 0.006), 2),
                        "gas_kwh": round(base_gas * winter_factor, 2),
                    }
                )


def write_emissions_factors() -> None:
    path = DATA_DIR / "emissions_factors.csv"
    fieldnames = ["fuel", "kg_co2e_per_kwh", "source", "notes"]
    rows = [
        {
            "fuel": "electricity",
            "kg_co2e_per_kwh": 0.207,
            "source": "prototype_sample_factor",
            "notes": "Starter grid-electricity factor for prototype calculations; replace with documented official factor for submission.",
        },
        {
            "fuel": "gas",
            "kg_co2e_per_kwh": 0.183,
            "source": "prototype_sample_factor",
            "notes": "Starter natural-gas factor for prototype calculations; replace with documented official factor for submission.",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
