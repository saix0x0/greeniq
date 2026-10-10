import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green_home.retrofits import recommend_retrofits
from green_home.scoring import EnergyReading, PropertyRecord, score_property


class RetrofitTests(unittest.TestCase):
    def test_recommends_only_feasible_missing_upgrades(self):
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
        score = score_property(record, [EnergyReading(400, 1000) for _ in range(12)])

        plan = recommend_retrofits(record, score)
        retrofits = [recommendation.retrofit for recommendation in plan.recommendations]

        self.assertEqual(
            retrofits,
            [
                "Roof or loft insulation",
                "Double glazing",
                "Heat pump",
                "Solar panels",
                "Smart thermostat",
            ],
        )
        self.assertLess(
            next(r for r in plan.recommendations if r.retrofit == "Heat pump").savings.electricity_kwh,
            0,
        )

    def test_does_not_recommend_existing_upgrades(self):
        record = PropertyRecord(
            property_id="P2",
            floor_area_m2=90,
            energy_rating="B",
            heating="heat_pump",
            insulation="excellent",
            glazing="triple",
            solar=True,
            smart_controls=True,
        )
        score = score_property(record, [EnergyReading(250, 0) for _ in range(12)])

        plan = recommend_retrofits(record, score)

        self.assertEqual(plan.recommendations, [])
        self.assertEqual(plan.package_savings.net_kwh, 0)

    def test_package_savings_are_not_simple_sum(self):
        record = PropertyRecord(
            property_id="P3",
            floor_area_m2=100,
            energy_rating="F",
            heating="gas_boiler",
            insulation="none",
            glazing="single",
            solar=False,
            smart_controls=False,
        )
        score = score_property(record, [EnergyReading(300, 1200) for _ in range(12)])

        plan = recommend_retrofits(record, score)
        individual_sum = sum(r.savings.net_kwh for r in plan.recommendations)

        self.assertNotEqual(plan.package_savings.net_kwh, individual_sum)
        self.assertGreater(plan.improvement_potential_percent, 0)


if __name__ == "__main__":
    unittest.main()
