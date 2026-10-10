import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from green_home.carbon import EmissionsFactors, calculate_carbon
from green_home.retrofits import FuelSavings


class CarbonTests(unittest.TestCase):
    def test_calculates_per_fuel_and_net_carbon(self):
        factors = EmissionsFactors(
            electricity_kg_co2e_per_kwh=0.2,
            gas_kg_co2e_per_kwh=0.18,
            source="test",
        )
        savings = FuelSavings(electricity_kwh=100, gas_kwh=1000)

        estimate = calculate_carbon(savings, factors)

        self.assertEqual(estimate.electricity_kg_co2e, 20)
        self.assertEqual(estimate.gas_kg_co2e, 180)
        self.assertEqual(estimate.net_kg_co2e, 200)
        self.assertEqual(estimate.net_tonnes_co2e, 0.2)

    def test_handles_electricity_increase_as_negative_saving(self):
        factors = EmissionsFactors(
            electricity_kg_co2e_per_kwh=0.2,
            gas_kg_co2e_per_kwh=0.18,
            source="test",
        )
        savings = FuelSavings(electricity_kwh=-300, gas_kwh=1000)

        estimate = calculate_carbon(savings, factors)

        self.assertEqual(estimate.electricity_kg_co2e, -60)
        self.assertEqual(estimate.gas_kg_co2e, 180)
        self.assertEqual(estimate.net_kg_co2e, 120)


if __name__ == "__main__":
    unittest.main()
