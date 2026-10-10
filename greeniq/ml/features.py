"""Model features: built ONLY from fields available at prediction time.

Leakage rules (tested in tests/test_ml.py):
- never read meter readings, annual energy, sale prices, current values or anything
  computed from them;
- missing values stay missing (NaN): the gradient-boosting models handle them natively,
  so nothing is silently imputed to zero;
- the same function serves training and inference, so features cannot drift between them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config.score_mappings import EPC_BAND_MIDPOINT
from ..contract import AGE_BANDS, Property
from ..engines import physics
from ..features.resolve import resolve_inputs

FEATURE_VERSION = "features/1.0"

CATEGORIES: dict[str, list[str]] = {
    "region": ["london", "south_east", "south_west", "midlands", "north", "wales", "scotland"],
    "property_type": ["detached", "semi_detached", "terraced", "bungalow", "flat"],
    "flat_position": ["ground", "mid", "top"],
    "wall_type": ["solid", "cavity"],
    "heating_system": ["gas_boiler_noncondensing", "gas_boiler_condensing", "electric_storage", "electric_direct",
                       "air_source_heat_pump", "ground_source_heat_pump"],
    "roof_orientation": ["south", "east_west", "north"],
}
ORDINALS: dict[str, list[str]] = {
    "glazing": ["single", "secondary", "double_pre_2002", "double_post_2002", "triple"],
    "controls": ["none", "programmer_thermostat", "programmer_thermostat_trvs", "smart_thermostat", "smart_zoned"],
}
NUMERIC = ["age_index", "floor_area_m2", "wall_insulated", "loft_insulation_mm", "floor_insulated", "boiler_age_years",
           "has_gas_connection", "solar_pv_kwp", "sap", "listed_or_conservation", "outdoor_space",
           "physics_hlc", "physics_hlc_per_m2"]
FEATURES = list(CATEGORIES) + list(ORDINALS) + NUMERIC
# Value model: the same characteristics, but the rating is the one in force at the sale.
FORBIDDEN = {"meter_readings", "price", "current_value", "annual_kwh", "sale_date"}


def _num(v):
    return np.nan if v is None else float(v)


def feature_row(p: Property, sap_override: float | None = None) -> dict:
    """One feature row for a home. ``sap_override`` lets the value model use the SAP at sale."""
    r = {}
    for c, cats in CATEGORIES.items():
        v = getattr(p, c)
        r[c] = float(cats.index(v)) if v in cats else np.nan
    for c, levels in ORDINALS.items():
        v = getattr(p, c)
        r[c] = float(levels.index(v)) if v in levels else np.nan
    r["age_index"] = float(AGE_BANDS.index(p.age_band)) if p.age_band else np.nan
    r["floor_area_m2"] = _num(p.floor_area_m2)
    r["wall_insulated"] = _num(p.wall_insulated)
    r["loft_insulation_mm"] = _num(p.loft_insulation_mm)
    r["floor_insulated"] = _num(p.floor_insulated)
    r["boiler_age_years"] = _num(p.boiler_age_years)
    r["has_gas_connection"] = _num(p.has_gas_connection)
    r["solar_pv_kwp"] = _num(p.solar_pv_kwp)
    if sap_override is not None:
        r["sap"] = float(sap_override)
    elif p.sap_score is not None:
        r["sap"] = float(p.sap_score)
    elif p.epc_band is not None:
        r["sap"] = EPC_BAND_MIDPOINT[p.epc_band]
    else:
        r["sap"] = np.nan
    r["listed_or_conservation"] = _num(p.listed_or_conservation)
    r["outdoor_space"] = _num(p.outdoor_space)
    # Engineered: the engine's own heat-loss estimate (uses documented defaults for unknowns).
    if p.floor_area_m2 is not None:
        phys = physics.physical_state(p.property_type, resolve_inputs(p))
        hlc = physics.heat_loss_coefficient(phys)
        r["physics_hlc"], r["physics_hlc_per_m2"] = hlc, hlc / phys["floor_area_m2"]
    else:
        r["physics_hlc"] = r["physics_hlc_per_m2"] = np.nan
    return r


def feature_frame(props: list[Property], sap_overrides: list[float | None] | None = None) -> pd.DataFrame:
    rows = [feature_row(p, None if sap_overrides is None else sap_overrides[i]) for i, p in enumerate(props)]
    return pd.DataFrame(rows, columns=FEATURES)


def categorical_mask() -> list[bool]:
    return [f in CATEGORIES for f in FEATURES]
