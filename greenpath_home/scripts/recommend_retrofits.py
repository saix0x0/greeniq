#!/usr/bin/env python3
"""Recommend feasible retrofits for sample properties."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from green_home.retrofits import recommend_retrofits
from green_home.scoring import score_property
from score_properties import DATA_DIR, read_energy_usage, read_properties


def main() -> None:
    properties_path = DATA_DIR / "properties.csv"
    energy_path = DATA_DIR / "energy_usage.csv"

    if not properties_path.exists() or not energy_path.exists():
        raise SystemExit("Sample data missing. Run: python3 scripts/generate_sample_data.py")

    energy_by_property = read_energy_usage(energy_path)
    for record in read_properties(properties_path):
        score = score_property(record, energy_by_property[record.property_id])
        plan = recommend_retrofits(record, score)
        print_plan(score.classification, plan)


def print_plan(classification, plan) -> None:
    print(f"\n{plan.property_id}: retrofit plan ({classification})")
    if not plan.recommendations:
        print("  No feasible retrofits identified from the current rules.")
        return

    for recommendation in plan.recommendations:
        print(
            "  "
            f"{recommendation.priority}. {recommendation.retrofit} "
            f"- {recommendation.suitability} suitability"
        )
        print(
            "     Estimated savings: "
            f"electricity {recommendation.savings.electricity_kwh} kWh/year, "
            f"gas {recommendation.savings.gas_kwh} kWh/year, "
            f"net {recommendation.savings.net_kwh} kWh/year"
        )
        print(f"     Reason: {recommendation.reason}")

    if plan.package_savings is not None:
        print(
            "  Package estimate: "
            f"electricity {plan.package_savings.electricity_kwh} kWh/year, "
            f"gas {plan.package_savings.gas_kwh} kWh/year, "
            f"net {plan.package_savings.net_kwh} kWh/year"
        )
    if plan.improvement_potential_percent is not None:
        print(f"  Improvement potential: {plan.improvement_potential_percent}%")


if __name__ == "__main__":
    main()
