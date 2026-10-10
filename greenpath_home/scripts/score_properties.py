#!/usr/bin/env python3
"""Score properties and print an auditable Green Home Score summary."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green_home.scoring import EnergyReading, PropertyRecord, score_property


DATA_DIR = ROOT / "data" / "sample"


def main() -> None:
    properties_path = DATA_DIR / "properties.csv"
    energy_path = DATA_DIR / "energy_usage.csv"

    if not properties_path.exists() or not energy_path.exists():
        raise SystemExit("Sample data missing. Run: python3 scripts/generate_sample_data.py")

    energy_by_property = read_energy_usage(energy_path)
    results = []

    for record in read_properties(properties_path):
        result = score_property(record, energy_by_property[record.property_id])
        results.append(result)

    print_scores(results)


def read_properties(path: Path) -> list[PropertyRecord]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = csv.DictReader(file)
        return [
            PropertyRecord(
                property_id=row["property_id"],
                floor_area_m2=float(row["floor_area_m2"]),
                energy_rating=row["energy_rating"],
                heating=row["heating"],
                insulation=row["insulation"],
                glazing=row["glazing"],
                solar=_parse_bool(row["solar"]),
                smart_controls=_parse_bool(row["smart_controls"]),
                property_type=row.get("property_type", ""),
                region=row.get("region", ""),
                current_value_gbp=_parse_optional_float(row.get("current_value_gbp", "")),
            )
            for row in rows
        ]


def read_energy_usage(path: Path) -> dict[str, list[EnergyReading]]:
    readings: dict[str, list[EnergyReading]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            readings[row["property_id"]].append(
                EnergyReading(
                    electricity_kwh=float(row["electricity_kwh"]),
                    gas_kwh=float(row["gas_kwh"]),
                )
            )
    return readings


def print_scores(results) -> None:
    for result in results:
        print(f"\n{result.property_id}: {result.score}/100 - {result.classification}")
        if result.purchased_energy_intensity_kwh_m2 is not None:
            print(
                "  Energy intensity: "
                f"{result.purchased_energy_intensity_kwh_m2} kWh/m2/year"
            )
        print("  Component contributions:")
        for component in result.components:
            print(
                "   - "
                f"{component.name}: {component.subscore}/100 x {component.weight:.0%} "
                f"= {component.contribution}"
            )
        if result.classification in {"Poor", "Very poor"}:
            print("  Key issues:")
            for issue in result.key_issues:
                print(f"   - {issue}")


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y"}


def _parse_optional_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    return float(value)


if __name__ == "__main__":
    main()
