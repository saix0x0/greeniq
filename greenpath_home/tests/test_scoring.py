import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green_home.scoring import EnergyReading, PropertyRecord, classify_score, score_property


class ScoringTests(unittest.TestCase):
    def test_classification_boundaries(self):
        self.assertEqual(classify_score(80), "Highly efficient")
        self.assertEqual(classify_score(65), "Good")
        self.assertEqual(classify_score(50), "Moderate")
        self.assertEqual(classify_score(30), "Poor")
        self.assertEqual(classify_score(29), "Very poor")

    def test_low_quality_property_is_flagged_poor(self):
        record = PropertyRecord(
            property_id="P1",
            floor_area_m2=80,
            energy_rating="E",
            heating="gas_boiler",
            insulation="poor",
            glazing="single",
            solar=False,
            smart_controls=False,
        )
        readings = [EnergyReading(electricity_kwh=400, gas_kwh=1000) for _ in range(12)]

        result = score_property(record, readings)

        self.assertEqual(result.classification, "Poor")
        self.assertIn("Single glazing", result.key_issues)
        self.assertEqual(len(result.components), 7)

    def test_better_energy_rating_does_not_lower_score(self):
        readings = [EnergyReading(electricity_kwh=250, gas_kwh=350) for _ in range(12)]
        base = PropertyRecord(
            property_id="P1",
            floor_area_m2=100,
            energy_rating="D",
            heating="modern_gas_boiler",
            insulation="good",
            glazing="double",
            solar=True,
            smart_controls=True,
        )
        better = PropertyRecord(
            property_id="P2",
            floor_area_m2=100,
            energy_rating="C",
            heating="modern_gas_boiler",
            insulation="good",
            glazing="double",
            solar=True,
            smart_controls=True,
        )

        self.assertGreaterEqual(
            score_property(better, readings).score,
            score_property(base, readings).score,
        )


if __name__ == "__main__":
    unittest.main()
