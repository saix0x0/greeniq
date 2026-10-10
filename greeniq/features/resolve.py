"""Resolve a recorded ``Property`` into inputs the engines can use, each tagged with its basis.

Unknown fabric details get documented age-band defaults, as reduced-data EPC
assessments (RdSAP) do; those values are tagged ``assumed`` and lower the confidence
of everything computed from them. Fields with no defensible default stay ``missing``.
The defaults are deliberately conservative and are listed in ``docs/SCORING_METHOD.md``.
"""

from __future__ import annotations

from ..contract import Property, Resolved

DEFAULTS_VERSION = "age-band-defaults/1.0"

_NEWER = ("1981_2002", "post_2002")

# Loft depth (mm) assumed when a loft exists but its insulation is unknown.
DEFAULT_LOFT_MM = {
    "pre_1919": 100, "1919_1944": 100, "1945_1964": 100, "1965_1980": 100, "1981_2002": 150, "post_2002": 250,
}


def _obs(value) -> Resolved:
    return Resolved(value=value, basis="observed")


def _missing(note: str) -> Resolved:
    return Resolved(value=None, basis="missing", note=note)


def resolve_inputs(p: Property) -> dict[str, Resolved]:
    """Return the physical inputs used by the score and energy engines."""
    r: dict[str, Resolved] = {}
    age = p.age_band
    is_flat = p.property_type == "flat"

    r["age_band"] = _obs(age) if age else _missing("construction age unknown")
    r["floor_area_m2"] = _obs(p.floor_area_m2) if p.floor_area_m2 else _missing("floor area unknown")

    # Loft: a ground or mid-floor flat has another dwelling above it.
    if p.has_loft is not None:
        r["has_loft"] = _obs(p.has_loft)
    elif is_flat and p.flat_position in ("ground", "mid"):
        r["has_loft"] = Resolved(value=False, basis="derived", note=f"{p.flat_position}-floor flat: dwelling above")
    elif is_flat and p.flat_position is None:
        r["has_loft"] = _missing("flat position unknown, so loft access unknown")
    else:
        r["has_loft"] = Resolved(value=True, basis="derived", note="houses, bungalows and top-floor flats have a roof space")

    # Ground floor: only ground-floor flats and houses lose heat through a ground floor.
    if is_flat and p.flat_position in ("mid", "top"):
        r["has_ground_floor"] = Resolved(value=False, basis="derived", note=f"{p.flat_position}-floor flat")
    elif is_flat and p.flat_position is None:
        r["has_ground_floor"] = _missing("flat position unknown")
    else:
        r["has_ground_floor"] = Resolved(value=True, basis="derived")

    # Walls.
    if p.wall_type:
        r["wall_type"] = _obs(p.wall_type)
    elif age:
        wt = "solid" if age == "pre_1919" else "cavity"
        r["wall_type"] = Resolved(value=wt, basis="assumed", note=f"age-band default for {age}")
    else:
        r["wall_type"] = _missing("wall type unknown")

    if p.wall_insulated is not None:
        r["wall_insulated"] = _obs(p.wall_insulated)
    elif age and r["wall_type"].known:
        ins = r["wall_type"].value == "cavity" and age in _NEWER
        r["wall_insulated"] = Resolved(value=ins, basis="assumed", note=f"age-band default for {age}")
    else:
        r["wall_insulated"] = _missing("wall insulation unknown")

    # Loft insulation depth.
    if r["has_loft"].known and r["has_loft"].value is False:
        r["loft_insulation_mm"] = Resolved(value=None, basis="not_applicable", note="no loft")
    elif p.loft_insulation_mm is not None:
        r["loft_insulation_mm"] = _obs(p.loft_insulation_mm)
    elif age and r["has_loft"].known:
        r["loft_insulation_mm"] = Resolved(value=DEFAULT_LOFT_MM[age], basis="assumed", note=f"age-band default for {age}")
    else:
        r["loft_insulation_mm"] = _missing("loft insulation depth unknown")

    # Floor insulation.
    if r["has_ground_floor"].known and r["has_ground_floor"].value is False:
        r["floor_insulated"] = Resolved(value=None, basis="not_applicable", note="no ground floor")
    elif p.floor_insulated is not None:
        r["floor_insulated"] = _obs(p.floor_insulated)
    elif age:
        r["floor_insulated"] = Resolved(value=age == "post_2002", basis="assumed", note=f"age-band default for {age}")
    else:
        r["floor_insulated"] = _missing("floor insulation unknown")

    # Glazing: most UK homes are double glazed; age decides which vintage we assume.
    if p.glazing:
        r["glazing"] = _obs(p.glazing)
    elif age:
        g = "double_post_2002" if age == "post_2002" else "double_pre_2002"
        r["glazing"] = Resolved(value=g, basis="assumed", note=f"age-band default for {age}")
    else:
        r["glazing"] = _missing("glazing unknown")

    # Heating: too important to assume.
    r["heating_system"] = _obs(p.heating_system) if p.heating_system else _missing("heating system unknown")
    if p.heating_system in ("gas_boiler_condensing", "gas_boiler_noncondensing"):
        if p.boiler_age_years is not None:
            r["boiler_age_years"] = _obs(p.boiler_age_years)
        else:
            r["boiler_age_years"] = Resolved(value=12, basis="assumed", note="boiler age unknown; assumed 12 years")
    else:
        r["boiler_age_years"] = Resolved(value=None, basis="not_applicable")

    r["controls"] = (
        _obs(p.controls) if p.controls
        else Resolved(value="programmer_thermostat", basis="assumed", note="most common UK control set assumed")
    )
    r["solar_pv_kwp"] = (
        _obs(p.solar_pv_kwp) if p.solar_pv_kwp is not None
        else Resolved(value=0.0, basis="assumed", note="no solar PV recorded")
    )
    return r
