#!/usr/bin/env python3
"""List poor homes and rank them by retrofit improvement potential."""

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
    ranked = []
    for record in read_properties(properties_path):
        score = score_property(record, energy_by_property[record.property_id])
        if score.classification not in {"Poor", "Very poor"}:
            continue
        plan = recommend_retrofits(record, score)
        ranked.append((record, score, plan))

    ranked.sort(
        key=lambda item: item[2].improvement_potential_percent
        if item[2].improvement_potential_percent is not None
        else -1,
        reverse=True,
    )

    if not ranked:
        print("No Poor or Very poor homes found.")
        return

    print("Poor and Very poor homes ranked by improvement potential:")
    for index, (_record, score, plan) in enumerate(ranked, start=1):
        potential = plan.improvement_potential_percent
        potential_text = "unavailable" if potential is None else f"{potential}%"
        print(f"\n{index}. {score.property_id}: {score.score}/100 - {score.classification}")
        print(f"   Improvement potential: {potential_text}")
        print("   Key issues:")
        for issue in score.key_issues:
            print(f"   - {issue}")


if __name__ == "__main__":
    main()
