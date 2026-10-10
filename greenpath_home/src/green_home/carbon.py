"""Carbon impact calculations from per-fuel energy savings."""

from __future__ import annotations

from dataclasses import dataclass

from .retrofits import FuelSavings


@dataclass(frozen=True)
class EmissionsFactors:
    electricity_kg_co2e_per_kwh: float
    gas_kg_co2e_per_kwh: float
    source: str


@dataclass(frozen=True)
class CarbonEstimate:
    electricity_kg_co2e: float
    gas_kg_co2e: float
    net_kg_co2e: float
    net_tonnes_co2e: float
    source: str


def calculate_carbon(savings: FuelSavings, factors: EmissionsFactors) -> CarbonEstimate:
    """Convert electricity and gas savings into kg and tonnes CO2e.

    Positive values are emissions reductions. Negative values are emissions
    increases, for example when a heat pump increases electricity use.
    """
    electricity_kg = savings.electricity_kwh * factors.electricity_kg_co2e_per_kwh
    gas_kg = savings.gas_kwh * factors.gas_kg_co2e_per_kwh
    net_kg = electricity_kg + gas_kg

    return CarbonEstimate(
        electricity_kg_co2e=round(electricity_kg, 2),
        gas_kg_co2e=round(gas_kg, 2),
        net_kg_co2e=round(net_kg, 2),
        net_tonnes_co2e=round(net_kg / 1000, 3),
        source=factors.source,
    )
