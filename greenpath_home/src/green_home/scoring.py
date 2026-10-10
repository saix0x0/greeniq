"""Auditable Green Home Score calculator.

The score is deterministic and intentionally separate from any LLM layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


COMPONENT_WEIGHTS: dict[str, float] = {
    "energy_efficiency": 0.25,
    "energy_consumption_intensity": 0.20,
    "insulation": 0.15,
    "heating_system": 0.15,
    "windows_and_glazing": 0.10,
    "renewable_energy": 0.10,
    "smart_energy_management": 0.05,
}

ENERGY_RATING_SCORES = {
    "A": 100,
    "B": 85,
    "C": 70,
    "D": 55,
    "E": 40,
    "F": 25,
    "G": 10,
}

INSULATION_SCORES = {
    "excellent": 100,
    "good": 75,
    "partial": 45,
    "poor": 20,
    "none": 0,
}

HEATING_SCORES = {
    "heat_pump": 95,
    "district_heating": 80,
    "modern_gas_boiler": 65,
    "gas_boiler": 45,
    "electric_resistance": 30,
    "oil_boiler": 20,
}

GLAZING_SCORES = {
    "triple": 100,
    "double": 75,
    "secondary": 50,
    "single": 20,
}


@dataclass(frozen=True)
class PropertyRecord:
    property_id: str
    floor_area_m2: float
    energy_rating: str
    heating: str
    insulation: str
    glazing: str
    solar: bool
    smart_controls: bool
    property_type: str = ""
    region: str = ""
    current_value_gbp: float | None = None


@dataclass(frozen=True)
class EnergyReading:
    electricity_kwh: float
    gas_kwh: float


@dataclass(frozen=True)
class ComponentScore:
    name: str
    weight: float
    subscore: float
    contribution: float
    reason: str


@dataclass(frozen=True)
class ScoreResult:
    property_id: str
    score: int
    classification: str
    components: list[ComponentScore]
    annual_electricity_kwh: float | None
    annual_gas_kwh: float | None
    purchased_energy_intensity_kwh_m2: float | None
    key_issues: list[str]


def classify_score(score: int) -> str:
    if score >= 80:
        return "Highly efficient"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Moderate"
    if score >= 30:
        return "Poor"
    return "Very poor"


def score_property(
    property_record: PropertyRecord,
    energy_readings: Iterable[EnergyReading],
) -> ScoreResult:
    readings = list(energy_readings)
    annual_electricity = _annualise([reading.electricity_kwh for reading in readings])
    annual_gas = _annualise([reading.gas_kwh for reading in readings])
    intensity = _energy_intensity(
        annual_electricity,
        annual_gas,
        property_record.floor_area_m2,
    )

    component_inputs = {
        "energy_efficiency": _score_energy_rating(property_record.energy_rating),
        "energy_consumption_intensity": _score_energy_intensity(intensity),
        "insulation": _lookup_score(INSULATION_SCORES, property_record.insulation),
        "heating_system": _lookup_score(HEATING_SCORES, property_record.heating),
        "windows_and_glazing": _lookup_score(GLAZING_SCORES, property_record.glazing),
        "renewable_energy": 100 if property_record.solar else 0,
        "smart_energy_management": 100 if property_record.smart_controls else 0,
    }

    components = [
        ComponentScore(
            name=name,
            weight=weight,
            subscore=component_inputs[name],
            contribution=round(component_inputs[name] * weight, 2),
            reason=_component_reason(name, component_inputs[name], property_record, intensity),
        )
        for name, weight in COMPONENT_WEIGHTS.items()
    ]

    raw_score = sum(component.contribution for component in components)
    rounded_score = round(raw_score)

    return ScoreResult(
        property_id=property_record.property_id,
        score=rounded_score,
        classification=classify_score(rounded_score),
        components=components,
        annual_electricity_kwh=annual_electricity,
        annual_gas_kwh=annual_gas,
        purchased_energy_intensity_kwh_m2=intensity,
        key_issues=_key_issues(property_record, intensity, components),
    )


def _annualise(values: list[float]) -> float | None:
    clean_values = [value for value in values if value >= 0]
    if not clean_values:
        return None
    return round(sum(clean_values) * 12 / len(clean_values), 2)


def _energy_intensity(
    annual_electricity: float | None,
    annual_gas: float | None,
    floor_area_m2: float,
) -> float | None:
    if floor_area_m2 <= 0 or annual_electricity is None or annual_gas is None:
        return None
    return round((annual_electricity + annual_gas) / floor_area_m2, 2)


def _score_energy_rating(rating: str) -> int:
    return ENERGY_RATING_SCORES.get(rating.strip().upper(), 0)


def _score_energy_intensity(intensity: float | None) -> int:
    if intensity is None:
        return 0
    if intensity <= 70:
        return 100
    if intensity <= 110:
        return 85
    if intensity <= 160:
        return 65
    if intensity <= 220:
        return 45
    if intensity <= 300:
        return 25
    return 10


def _lookup_score(mapping: dict[str, int], value: str) -> int:
    return mapping.get(value.strip().lower(), 0)


def _component_reason(
    name: str,
    subscore: float,
    property_record: PropertyRecord,
    intensity: float | None,
) -> str:
    if name == "energy_efficiency":
        return f"Recorded energy rating is {property_record.energy_rating.upper()}."
    if name == "energy_consumption_intensity":
        if intensity is None:
            return "Annualised energy intensity is unavailable."
        return f"Annualised purchased energy intensity is {intensity} kWh/m2/year."
    if name == "insulation":
        return f"Insulation state is {property_record.insulation}."
    if name == "heating_system":
        return f"Main heating system is {property_record.heating}."
    if name == "windows_and_glazing":
        return f"Glazing state is {property_record.glazing}."
    if name == "renewable_energy":
        return "Solar panels are installed." if subscore == 100 else "No solar panels recorded."
    if name == "smart_energy_management":
        return "Smart controls are installed." if subscore == 100 else "No smart controls recorded."
    return "Component scored from documented mapping."


def _key_issues(
    property_record: PropertyRecord,
    intensity: float | None,
    components: list[ComponentScore],
) -> list[str]:
    issues: list[str] = []
    if property_record.energy_rating.upper() in {"E", "F", "G"}:
        issues.append(f"Low energy rating ({property_record.energy_rating.upper()})")
    if intensity is None:
        issues.append("Energy intensity unavailable")
    elif intensity > 220:
        issues.append(f"High energy use per m2 ({intensity} kWh/m2/year)")
    if property_record.insulation.lower() in {"poor", "none"}:
        issues.append(f"Weak insulation ({property_record.insulation})")
    if property_record.heating.lower() in {"gas_boiler", "oil_boiler", "electric_resistance"}:
        issues.append(f"Less efficient heating system ({property_record.heating})")
    if property_record.glazing.lower() == "single":
        issues.append("Single glazing")
    if not property_record.solar:
        issues.append("No renewable generation recorded")
    if not property_record.smart_controls:
        issues.append("No smart energy controls recorded")

    if not issues:
        low_components = [component for component in components if component.subscore < 50]
        issues.extend(component.name.replace("_", " ") for component in low_components)
    return issues
