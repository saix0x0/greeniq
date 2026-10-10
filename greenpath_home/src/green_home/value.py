"""Indicative property-value impact estimates."""

from __future__ import annotations

from dataclasses import dataclass

from .retrofits import RetrofitPlan
from .scoring import PropertyRecord, ScoreResult


RATING_ORDER = ["G", "F", "E", "D", "C", "B", "A"]
UPLIFT_BY_BANDS = {
    0: (0.0, 1.0),
    1: (1.0, 3.0),
    2: (2.0, 5.0),
    3: (4.0, 8.0),
}


@dataclass(frozen=True)
class ValueImpactEstimate:
    property_id: str
    baseline_value_gbp: float | None
    current_rating: str
    estimated_post_retrofit_rating: str
    rating_band_improvement: int
    uplift_percent_low: float | None
    uplift_percent_high: float | None
    potential_value_low_gbp: float | None
    potential_value_high_gbp: float | None
    basis: str
    limitation: str


def estimate_value_impact(
    property_record: PropertyRecord,
    score_result: ScoreResult,
    retrofit_plan: RetrofitPlan,
) -> ValueImpactEstimate:
    current_rating = property_record.energy_rating.strip().upper()
    post_rating = _estimate_post_retrofit_rating(current_rating, retrofit_plan)
    band_improvement = _rating_band_improvement(current_rating, post_rating)
    uplift_low, uplift_high = _uplift_range(band_improvement)

    if property_record.current_value_gbp is None:
        value_low = None
        value_high = None
    else:
        value_low = round(property_record.current_value_gbp * (1 + uplift_low / 100), 2)
        value_high = round(property_record.current_value_gbp * (1 + uplift_high / 100), 2)

    return ValueImpactEstimate(
        property_id=property_record.property_id,
        baseline_value_gbp=property_record.current_value_gbp,
        current_rating=current_rating,
        estimated_post_retrofit_rating=post_rating,
        rating_band_improvement=band_improvement,
        uplift_percent_low=uplift_low,
        uplift_percent_high=uplift_high,
        potential_value_low_gbp=value_low,
        potential_value_high_gbp=value_high,
        basis=_basis(property_record, score_result, retrofit_plan),
        limitation=(
            "Indicative estimate based on documented prototype rules; it is not "
            "a guaranteed or proven causal increase in sale value."
        ),
    )


def _estimate_post_retrofit_rating(current_rating: str, retrofit_plan: RetrofitPlan) -> str:
    if current_rating not in RATING_ORDER:
        return current_rating

    package_savings = retrofit_plan.package_savings
    improvement = retrofit_plan.improvement_potential_percent
    if package_savings is None or improvement is None:
        return current_rating

    retrofit_names = {item.retrofit for item in retrofit_plan.recommendations}
    bands = 0
    if improvement >= 20:
        bands += 1
    if improvement >= 45:
        bands += 1
    if {"Roof or loft insulation", "Double glazing", "Heat pump"}.issubset(retrofit_names):
        bands += 1
    if "Solar panels" in retrofit_names and improvement >= 30:
        bands += 1

    current_index = RATING_ORDER.index(current_rating)
    new_index = min(current_index + bands, len(RATING_ORDER) - 1)
    return RATING_ORDER[new_index]


def _rating_band_improvement(current_rating: str, post_rating: str) -> int:
    if current_rating not in RATING_ORDER or post_rating not in RATING_ORDER:
        return 0
    return max(0, RATING_ORDER.index(post_rating) - RATING_ORDER.index(current_rating))


def _uplift_range(bands: int) -> tuple[float, float]:
    if bands >= 3:
        return UPLIFT_BY_BANDS[3]
    return UPLIFT_BY_BANDS[bands]


def _basis(
    property_record: PropertyRecord,
    score_result: ScoreResult,
    retrofit_plan: RetrofitPlan,
) -> str:
    location = property_record.region or "unknown region"
    property_type = property_record.property_type or "unknown property type"
    improvement = retrofit_plan.improvement_potential_percent
    improvement_text = "unavailable" if improvement is None else f"{improvement}%"
    return (
        f"Compared the current rating {property_record.energy_rating.upper()} with an "
        f"estimated post-retrofit rating using package improvement potential "
        f"({improvement_text}), property type ({property_type}), region ({location}), "
        f"and current score ({score_result.score}/100)."
    )
