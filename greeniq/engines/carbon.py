"""Carbon: ΔC = Σ_f ΔE_f × EF_f, f ∈ {electricity, gas} (PS2 §07).

ΔE_f = baseline kWh − after kWh, so a positive value is a saving and a negative value an
increase. Positive ΔC is an emissions reduction. Signs are never hidden or clipped.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..contract import Receipt
from .catalogue import emission_factors

CARBON_VERSION = "carbon-per-fuel/1.0"


class CarbonResult(BaseModel):
    electricity_kg: float
    gas_kg: float
    total_kg: float
    total_tonnes: float
    receipt: Receipt


def factor(fuel: str) -> float:
    return float(emission_factors()["factors"][fuel]["value"])


def emissions_kg(electricity_kwh: float, gas_kwh: float) -> float:
    """Annual emissions of purchased energy (kg CO2e/yr)."""
    return electricity_kwh * factor("electricity") + gas_kwh * factor("gas")


def carbon_reduction(delta_electricity_kwh: float, delta_gas_kwh: float, output: str = "carbon") -> CarbonResult:
    """``delta_*`` are savings (baseline − after); negative means consumption went up."""
    ef = emission_factors()
    e = delta_electricity_kwh * factor("electricity")
    g = delta_gas_kwh * factor("gas")
    return CarbonResult(
        electricity_kg=round(e, 1), gas_kg=round(g, 1), total_kg=round(e + g, 1), total_tonnes=round((e + g) / 1000, 2),
        receipt=Receipt(
            output=output, value=round(e + g, 1), unit="kg CO2e/yr (positive = reduction)",
            inputs={"delta_electricity_kwh": round(delta_electricity_kwh, 1), "delta_gas_kwh": round(delta_gas_kwh, 1),
                    "ef_electricity": factor("electricity"), "ef_gas": factor("gas")},
            method="ΔC = ΔE_elec × EF_elec + ΔE_gas × EF_gas", method_version=CARBON_VERSION,
            sources=[ef["factors"]["electricity"]["source"], ef["factors"]["gas"]["source"]],
            notes=["estimate, not a guarantee", "annual-average grid factor"],
        ),
    )
