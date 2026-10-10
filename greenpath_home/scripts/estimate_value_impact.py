#!/usr/bin/env python3
"""Estimate indicative property-value impact for retrofit plans."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from green_home.retrofits import recommend_retrofits
from green_home.scoring import score_property
from green_home.value import estimate_value_impact
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
        estimate = estimate_value_impact(record, score, plan)
        print_estimate(estimate)


def print_estimate(estimate) -> None:
    print(f"\n{estimate.property_id}: property-value impact")
    print(
        "  Rating change: "
        f"{estimate.current_rating} -> {estimate.estimated_post_retrofit_rating} "
        f"({estimate.rating_band_improvement} band improvement)"
    )
    if estimate.baseline_value_gbp is None:
        print("  Baseline value unavailable; potential value range unavailable.")
    else:
        print(f"  Current value: GBP {estimate.baseline_value_gbp:,.0f}")
        print(
            "  Indicative uplift: "
            f"{estimate.uplift_percent_low:g}-{estimate.uplift_percent_high:g}%"
        )
        print(
            "  Potential value: "
            f"GBP {estimate.potential_value_low_gbp:,.0f}-"
            f"GBP {estimate.potential_value_high_gbp:,.0f}"
        )
    print(f"  Basis: {estimate.basis}")
    print(f"  Limitation: {estimate.limitation}")


if __name__ == "__main__":
    main()
