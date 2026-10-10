#!/usr/bin/env python3
"""Calculate carbon impact for recommended retrofit plans."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from green_home.carbon import EmissionsFactors, calculate_carbon
from green_home.retrofits import recommend_retrofits
from green_home.scoring import score_property
from score_properties import DATA_DIR, read_energy_usage, read_properties


def main() -> None:
    properties_path = DATA_DIR / "properties.csv"
    energy_path = DATA_DIR / "energy_usage.csv"
    factors_path = DATA_DIR / "emissions_factors.csv"

    if not properties_path.exists() or not energy_path.exists() or not factors_path.exists():
        raise SystemExit("Sample data missing. Run: python3 scripts/generate_sample_data.py")

    factors = read_emissions_factors(factors_path)
    energy_by_property = read_energy_usage(energy_path)

    for record in read_properties(properties_path):
        score = score_property(record, energy_by_property[record.property_id])
        plan = recommend_retrofits(record, score)
        print_carbon_plan(score.classification, plan, factors)


def read_emissions_factors(path: Path) -> EmissionsFactors:
    factors: dict[str, float] = {}
    sources: set[str] = set()
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            fuel = row["fuel"].strip().lower()
            factors[fuel] = float(row["kg_co2e_per_kwh"])
            sources.add(row["source"])

    missing = {"electricity", "gas"} - set(factors)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Missing emissions factors for: {missing_text}")

    return EmissionsFactors(
        electricity_kg_co2e_per_kwh=factors["electricity"],
        gas_kg_co2e_per_kwh=factors["gas"],
        source=", ".join(sorted(sources)),
    )


def print_carbon_plan(classification, plan, factors) -> None:
    print(f"\n{plan.property_id}: carbon estimate ({classification})")
    if not plan.recommendations:
        print("  No feasible retrofit savings to convert into carbon impact.")
        return

    for recommendation in plan.recommendations:
        estimate = calculate_carbon(recommendation.savings, factors)
        print(f"  {recommendation.priority}. {recommendation.retrofit}")
        print(
            "     Carbon impact: "
            f"electricity {estimate.electricity_kg_co2e} kg CO2e/year, "
            f"gas {estimate.gas_kg_co2e} kg CO2e/year, "
            f"net {estimate.net_kg_co2e} kg CO2e/year "
            f"({estimate.net_tonnes_co2e} t CO2e/year)"
        )

    if plan.package_savings is not None:
        package = calculate_carbon(plan.package_savings, factors)
        print(
            "  Package carbon estimate: "
            f"electricity {package.electricity_kg_co2e} kg CO2e/year, "
            f"gas {package.gas_kg_co2e} kg CO2e/year, "
            f"net {package.net_kg_co2e} kg CO2e/year "
            f"({package.net_tonnes_co2e} t CO2e/year)"
        )
        print(f"  Emissions factor source: {package.source}")


if __name__ == "__main__":
    main()
