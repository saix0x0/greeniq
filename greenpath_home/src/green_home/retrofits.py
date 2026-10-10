"""Rule-based retrofit recommendation and savings estimates.

The model is deterministic and uses documented assumptions. It is deliberately
separate from any LLM layer, so generated explanations can be grounded in these
computed outputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import PropertyRecord, ScoreResult


@dataclass(frozen=True)
class FuelSavings:
    electricity_kwh: float
    gas_kwh: float

    @property
    def net_kwh(self) -> float:
        return round(self.electricity_kwh + self.gas_kwh, 2)


@dataclass(frozen=True)
class RetrofitRecommendation:
    retrofit: str
    priority: int
    suitability: str
    savings: FuelSavings
    reason: str


@dataclass(frozen=True)
class RetrofitPlan:
    property_id: str
    recommendations: list[RetrofitRecommendation]
    package_savings: FuelSavings | None
    improvement_potential_percent: float | None


def recommend_retrofits(
    property_record: PropertyRecord,
    score_result: ScoreResult,
) -> RetrofitPlan:
    """Return feasible retrofits in interaction-aware priority order."""
    if score_result.annual_electricity_kwh is None or score_result.annual_gas_kwh is None:
        return RetrofitPlan(
            property_id=property_record.property_id,
            recommendations=[],
            package_savings=None,
            improvement_potential_percent=None,
        )

    recommendations = _individual_recommendations(property_record, score_result)
    package_savings = _package_savings(property_record, score_result, recommendations)
    baseline = score_result.annual_electricity_kwh + score_result.annual_gas_kwh
    improvement = None
    if baseline > 0 and package_savings is not None:
        improvement = round(100 * package_savings.net_kwh / baseline, 1)

    return RetrofitPlan(
        property_id=property_record.property_id,
        recommendations=recommendations,
        package_savings=package_savings,
        improvement_potential_percent=improvement,
    )


def _individual_recommendations(
    property_record: PropertyRecord,
    score_result: ScoreResult,
) -> list[RetrofitRecommendation]:
    electricity = score_result.annual_electricity_kwh or 0
    gas = score_result.annual_gas_kwh or 0
    recommendations: list[RetrofitRecommendation] = []

    insulation = property_record.insulation.lower()
    if insulation in {"none", "poor", "partial"}:
        rate = 0.16 if insulation in {"none", "poor"} else 0.12
        recommendations.append(
            RetrofitRecommendation(
                retrofit="Roof or loft insulation",
                priority=1,
                suitability="High" if insulation in {"none", "poor"} else "Medium",
                savings=FuelSavings(electricity_kwh=0, gas_kwh=round(gas * rate, 2)),
                reason=f"Current insulation is {property_record.insulation}; reducing heat loss should come before heating upgrades.",
            )
        )

    glazing = property_record.glazing.lower()
    if glazing in {"single", "secondary"}:
        rate = 0.10 if glazing == "single" else 0.08
        recommendations.append(
            RetrofitRecommendation(
                retrofit="Double glazing",
                priority=2,
                suitability="High" if glazing == "single" else "Medium",
                savings=FuelSavings(electricity_kwh=0, gas_kwh=round(gas * rate, 2)),
                reason=f"Current glazing is {property_record.glazing}; better glazing can reduce heating demand.",
            )
        )

    heating = property_record.heating.lower()
    if heating in {"gas_boiler", "oil_boiler", "electric_resistance"}:
        gas_replaced = gas * 0.80 if heating in {"gas_boiler", "oil_boiler"} else 0
        electricity_increase = gas_replaced / 3.0
        suitability = "Medium" if insulation in {"none", "poor", "partial"} else "High"
        recommendations.append(
            RetrofitRecommendation(
                retrofit="Heat pump",
                priority=3,
                suitability=suitability,
                savings=FuelSavings(
                    electricity_kwh=round(-electricity_increase, 2),
                    gas_kwh=round(gas_replaced, 2),
                ),
                reason="The current heating system can be replaced, but fabric upgrades should be considered first.",
            )
        )

    if not property_record.solar:
        recommendations.append(
            RetrofitRecommendation(
                retrofit="Solar panels",
                priority=4,
                suitability="Medium",
                savings=FuelSavings(electricity_kwh=round(electricity * 0.30, 2), gas_kwh=0),
                reason="No solar generation is recorded; solar can reduce grid electricity imports.",
            )
        )

    if not property_record.smart_controls:
        recommendations.append(
            RetrofitRecommendation(
                retrofit="Smart thermostat",
                priority=5,
                suitability="Medium",
                savings=FuelSavings(electricity_kwh=0, gas_kwh=round(gas * 0.07, 2)),
                reason="No smart controls are recorded; smarter scheduling can reduce heating waste.",
            )
        )

    return sorted(recommendations, key=lambda recommendation: recommendation.priority)


def _package_savings(
    property_record: PropertyRecord,
    score_result: ScoreResult,
    recommendations: list[RetrofitRecommendation],
) -> FuelSavings | None:
    if not recommendations:
        return FuelSavings(electricity_kwh=0, gas_kwh=0)

    baseline_electricity = score_result.annual_electricity_kwh
    baseline_gas = score_result.annual_gas_kwh
    if baseline_electricity is None or baseline_gas is None:
        return None

    electricity_after = baseline_electricity
    gas_after = baseline_gas

    for recommendation in recommendations:
        if recommendation.retrofit == "Roof or loft insulation":
            rate = 0.16 if property_record.insulation.lower() in {"none", "poor"} else 0.12
            gas_after *= 1 - rate
        elif recommendation.retrofit == "Double glazing":
            rate = 0.10 if property_record.glazing.lower() == "single" else 0.08
            gas_after *= 1 - rate
        elif recommendation.retrofit == "Heat pump":
            replaced_gas = gas_after * 0.80
            gas_after -= replaced_gas
            electricity_after += replaced_gas / 3.0
        elif recommendation.retrofit == "Solar panels":
            electricity_after *= 0.70
        elif recommendation.retrofit == "Smart thermostat":
            gas_after *= 0.93

    return FuelSavings(
        electricity_kwh=round(baseline_electricity - electricity_after, 2),
        gas_kwh=round(baseline_gas - gas_after, 2),
    )
