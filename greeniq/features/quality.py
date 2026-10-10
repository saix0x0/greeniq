"""Data quality: conflicts between records and meters, stale EPCs, and what is missing.

Conflicts are never resolved silently. Each one is reported, explained, lowers confidence,
and states which value the engines used and why ("silence is not safety").
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..contract import Property, Resolved
from .annualise import AnnualFuel

QUALITY_VERSION = "data-quality/1.0"


class Conflict(BaseModel):
    code: str
    severity: Literal["high", "medium", "low"]
    message: str
    resolution: str


class Question(BaseModel):
    field: str
    importance: Literal["high", "medium", "low"]
    question: str
    why: str


def detect_conflicts(p: Property, inp: dict[str, Resolved], baseline: dict[str, AnnualFuel]) -> tuple[list[Conflict], str | None]:
    """Return (conflicts, effective heating system used for energy modelling)."""
    out: list[Conflict] = []
    recorded = inp["heating_system"].value if inp["heating_system"].known else None
    effective = recorded
    gas = baseline.get("gas")
    elec = baseline.get("electricity")
    gas_heat = gas.heating_kwh if gas and gas.heating_kwh is not None else None
    gas_total = gas.annual_kwh if gas and gas.annual_kwh is not None else None

    if recorded and not recorded.startswith("gas_boiler") and gas_total is not None and (
            (gas_heat or 0) > 2000 or gas_total > 4000):
        out.append(Conflict(
            code="heating_system_vs_gas_use", severity="high",
            message=(f"The record says {recorded.replace('_', ' ')}, but the gas meter shows about "
                     f"{gas_total:,.0f} kWh/yr with a clear winter heating pattern."),
            resolution=("Energy figures follow the meters (gas boiler heating assumed for modelling). "
                        "The heating system should be confirmed before acting on heating recommendations.")))
        effective = "gas_boiler_condensing"

    if recorded and recorded.startswith("gas_boiler") and gas is not None and gas.status in ("zero", "not_applicable") \
            and elec is not None and (elec.heating_kwh or 0) > 2500:
        out.append(Conflict(
            code="gas_boiler_without_gas_use", severity="high",
            message="The record says a gas boiler, but there is no gas use and electricity shows winter heating.",
            resolution="Energy figures follow the meters (electric heating assumed for modelling). Confirm the heating system."))
        effective = "electric_direct"

    if p.has_gas_connection is False and gas is not None and (gas.annual_kwh or 0) > 0:
        out.append(Conflict(code="gas_connection_mismatch", severity="medium",
                            message="Recorded as having no gas connection, but gas is metered.",
                            resolution="Metered gas is used; the gas-connection flag is treated as wrong."))

    if p.sap_score is not None and p.epc_band is not None:
        from ..score import sap_to_band
        if sap_to_band(p.sap_score) != p.epc_band:
            out.append(Conflict(code="epc_band_mismatch", severity="low",
                                message=f"SAP {p.sap_score} implies band {sap_to_band(p.sap_score)}, but band {p.epc_band} is recorded.",
                                resolution="The SAP number is used (it is more precise than the letter)."))

    stale = [r for r in p.retrofits_completed if p.epc_year is not None and r.month and int(r.month[:4]) >= p.epc_year]
    if stale:
        names = ", ".join(f"{r.measure_id.replace('_', ' ')} ({r.month})" for r in stale)
        out.append(Conflict(code="stale_epc", severity="medium",
                            message=f"The EPC ({p.epc_year}) predates work done since: {names}.",
                            resolution="The recorded rating is adjusted by the modelled effect of that work (estimated)."))

    area = inp["floor_area_m2"]
    if area.known and baseline and all(b.annual_kwh is not None for b in baseline.values()):
        total = sum(b.annual_kwh for b in baseline.values())
        intensity = total / area.value
        if total > 0 and (intensity < 20 or intensity > 700):
            out.append(Conflict(code="implausible_intensity", severity="medium",
                                message=f"{intensity:,.0f} kWh/m²/yr is outside the plausible range for a home.",
                                resolution="Check the floor area and meter records; the intensity score is kept but flagged."))
    return out, effective


_QUESTIONS = [
    ("sap_score", "high", "Do you have an Energy Performance Certificate? What is its rating?",
     "The EPC rating drives 25% of the Green Home Score."),
    ("floor_area_m2", "high", "What is the home's total floor area (m²)?",
     "Needed to measure energy use per m² fairly, whatever the home's size."),
    ("heating_system", "high", "How is the home heated (gas boiler, storage heaters, heat pump…)?",
     "Decides which upgrades make sense and how energy is split between gas and electricity."),
    ("meters", "high", "Can you share at least 6 months of electricity and gas readings, including some winter months?",
     "Real readings anchor every savings estimate."),
    ("age_band", "medium", "Roughly when was the home built?", "Used to infer wall type and insulation if unknown."),
    ("wall_type", "medium", "Are the external walls cavity or solid brick/stone?", "Decides which wall insulation applies."),
    ("wall_insulated", "medium", "Have the walls been insulated (cavity fill or solid-wall insulation)?",
     "Wall insulation is often the biggest heat-loss item."),
    ("loft_insulation_mm", "medium", "How deep is the loft insulation (mm)?", "Loft top-ups are cheap and effective."),
    ("glazing", "medium", "What kind of windows does the home have?", "Glazing is 10% of the score."),
    ("outdoor_space", "low", "Is there outdoor space for a heat pump unit?", "Required for an air source heat pump."),
    ("roof_orientation", "low", "Which way does the main roof face?", "Determines how much solar panels would generate."),
    ("controls", "low", "What heating controls do you have (thermostat, TRVs, smart thermostat)?",
     "Smart energy management is 5% of the score."),
    ("floor_insulated", "low", "Is the ground floor insulated?", "Part of the insulation component."),
]


def completeness(p: Property, inp: dict[str, Resolved], baseline: dict[str, AnnualFuel]) -> list[Question]:
    """Questions worth asking, most important first; missing before assumed."""
    out: list[Question] = []
    for field, imp, q, why in _QUESTIONS:
        if field == "meters":
            if any(b.status in ("insufficient", "no_data") for b in baseline.values()):
                out.append(Question(field=field, importance=imp, question=q, why=why))
            continue
        if field == "sap_score":
            if p.sap_score is None and p.epc_band is None:
                out.append(Question(field=field, importance=imp, question=q, why=why))
            continue
        if field == "roof_orientation":
            if p.property_type != "flat" and p.roof_orientation is None:
                out.append(Question(field=field, importance=imp, question=q, why=why))
            continue
        if field == "outdoor_space":
            if p.outdoor_space is None:
                out.append(Question(field=field, importance=imp, question=q, why=why))
            continue
        r = inp.get(field)
        if r is None:
            continue
        if r.basis == "missing":
            out.append(Question(field=field, importance=imp, question=q, why=why))
        elif r.basis == "assumed":
            out.append(Question(field=field, importance="low" if imp == "medium" else imp, question=q,
                                why=why + f" (currently assumed: {r.note})"))
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: rank[x.importance])
