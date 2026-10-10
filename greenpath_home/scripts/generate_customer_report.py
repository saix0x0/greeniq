#!/usr/bin/env python3
"""Generate the full customer-facing output required by the problem brief."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from calculate_carbon import read_emissions_factors
from green_home.carbon import calculate_carbon
from green_home.retrofits import recommend_retrofits
from green_home.scoring import score_property
from green_home.value import estimate_value_impact
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
        value = estimate_value_impact(record, score, plan)
        package_carbon = (
            calculate_carbon(plan.package_savings, factors)
            if plan.package_savings is not None
            else None
        )

        print_report(record, score, plan, package_carbon, value)


def print_report(record, score, plan, package_carbon, value) -> None:
    print(f"\n{'=' * 72}")
    print(f"Property {record.property_id}")
    print(f"{'=' * 72}")
    print(f"Green Home Score: {score.score}/100")
    print(f"Efficiency classification: {score.classification}")

    print("\nWhy this score:")
    for component in score.components:
        print(
            f"- {component.name}: {component.subscore}/100, "
            f"contribution {component.contribution} points. {component.reason}"
        )

    if score.classification in {"Poor", "Very poor"}:
        print("\nKey issues:")
        for issue in score.key_issues:
            print(f"- {issue}")

    print("\nRecommended improvements:")
    if not plan.recommendations:
        print("- No feasible retrofits identified from the current rules.")
    for recommendation in plan.recommendations:
        print(
            f"- {recommendation.retrofit} ({recommendation.suitability}): "
            f"electricity {recommendation.savings.electricity_kwh} kWh/year, "
            f"gas {recommendation.savings.gas_kwh} kWh/year. "
            f"{recommendation.reason}"
        )

    if plan.package_savings is None:
        print("\nPotential annual energy savings: unavailable")
    else:
        print(
            "\nPotential annual energy savings: "
            f"{plan.package_savings.net_kwh} kWh/year net "
            f"(electricity {plan.package_savings.electricity_kwh} kWh/year, "
            f"gas {plan.package_savings.gas_kwh} kWh/year)"
        )

    if package_carbon is None:
        print("Potential annual carbon reduction: unavailable")
    else:
        print(
            "Potential annual carbon reduction: "
            f"{package_carbon.net_tonnes_co2e} t CO2e/year "
            f"(electricity {package_carbon.electricity_kg_co2e} kg, "
            f"gas {package_carbon.gas_kg_co2e} kg)"
        )

    if value.potential_value_low_gbp is None:
        print("Potential property-value impact: unavailable")
    else:
        print(
            "Potential property-value impact: "
            f"+{value.uplift_percent_low:g}-{value.uplift_percent_high:g}% "
            f"(GBP {value.potential_value_low_gbp:,.0f}-"
            f"GBP {value.potential_value_high_gbp:,.0f})"
        )
        print(
            "Estimated rating after package: "
            f"{value.current_rating} -> {value.estimated_post_retrofit_rating}"
        )
    print(f"Value-impact limitation: {value.limitation}")


if __name__ == "__main__":
    main()
