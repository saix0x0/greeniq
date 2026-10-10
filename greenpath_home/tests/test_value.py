import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green_home.retrofits import recommend_retrofits
from green_home.scoring import EnergyReading, PropertyRecord, score_property
from green_home.value import estimate_value_impact


class ValueImpactTests(unittest.TestCase):
    def test_estimates_value_range_from_rating_improvement(self):
        record = PropertyRecord(
            property_id="P1",
            floor_area_m2=80,
            energy_rating="E",
            heating="gas_boiler",
            insulation="poor",
            glazing="single",
            solar=False,
            smart_controls=False,
            property_type="terraced",
            region="London",
            current_value_gbp=350000,
        )
        score = score_property(record, [EnergyReading(400, 1000) for _ in range(12)])
        plan = recommend_retrofits(record, score)

        estimate = estimate_value_impact(record, score, plan)

        self.assertGreaterEqual(estimate.rating_band_improvement, 2)
        self.assertGreater(estimate.potential_value_low_gbp, record.current_value_gbp)
        self.assertGreater(estimate.potential_value_high_gbp, estimate.potential_value_low_gbp)

    def test_missing_current_value_keeps_value_range_unavailable(self):
        record = PropertyRecord(
            property_id="P2",
            floor_area_m2=90,
            energy_rating="C",
            heating="modern_gas_boiler",
            insulation="good",
            glazing="double",
            solar=True,
            smart_controls=True,
        )
        score = score_property(record, [EnergyReading(300, 500) for _ in range(12)])
        plan = recommend_retrofits(record, score)

        estimate = estimate_value_impact(record, score, plan)

        self.assertIsNone(estimate.baseline_value_gbp)
        self.assertIsNone(estimate.potential_value_low_gbp)
        self.assertIsNone(estimate.potential_value_high_gbp)


if __name__ == "__main__":
    unittest.main()
