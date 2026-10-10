"""GreenIQ's own reduced-data heat-loss model (RdSAP-style, deliberately simple).

Used for three things only:
1. the *fraction* of space-heating demand a fabric measure removes (ΔHLC / HLC), applied
   to the home's metered heating, so savings stay anchored on real consumption;
2. heat-pump efficiency, which depends on heat loss per m² at installation time;
3. a physics-only consumption estimate when no usable meter data exists.

It uses published typical U-values and standard geometry assumptions. It knows nothing
about occupants, behaviour, installation quality or the simulator's internals.
"""

from __future__ import annotations

import math

from ..contract import AGE_BANDS, Resolved

PHYSICS_VERSION = "rdsap-lite/1.0"

U_WINDOW = {"single": 4.8, "secondary": 2.4, "double_pre_2002": 2.8, "double_post_2002": 1.6, "triple": 1.0}
ACH_BY_AGE = [0.9, 0.85, 0.75, 0.65, 0.55, 0.45]
EXPOSURE = {"detached": 1.0, "semi_detached": 0.75, "terraced": 0.5, "bungalow": 1.0, "flat": 0.5}
WINDOW_FRACTION = 0.18  # glazed area as a fraction of floor area
STOREY_HEIGHT = 2.5


def u_wall(wall_type: str, insulated: bool, age_band: str) -> float:
    if wall_type == "solid":
        return 0.35 if insulated else 2.0
    if insulated:
        return 0.45 if age_band in ("1981_2002", "post_2002") else 0.5
    return 1.4


def u_roof(loft_mm: float) -> float:
    return 1.0 / (0.4 + loft_mm / 40.0)  # 0 mm ≈ 2.5 W/m²K, 270 mm ≈ 0.14


def physical_state(p_type: str, inp: dict[str, Resolved]) -> dict:
    """Plain values for the physics model; unknowns fall back to conservative mid-stock values."""
    def val(key, fallback):
        r = inp.get(key)
        return r.value if r is not None and r.known and r.value is not None else fallback

    age = val("age_band", "1945_1964")
    return dict(
        property_type=p_type,
        age_band=age,
        floor_area_m2=float(val("floor_area_m2", 85.0)),
        wall_type=val("wall_type", "cavity"),
        wall_insulated=bool(val("wall_insulated", False)),
        has_loft=bool(val("has_loft", True)),
        loft_mm=float(val("loft_insulation_mm", 100) or 0) if val("has_loft", True) else 0.0,
        has_ground_floor=bool(val("has_ground_floor", True)),
        floor_insulated=bool(val("floor_insulated", False)),
        glazing=val("glazing", "double_pre_2002"),
        ach_factor=1.0,
    )


def envelope(s: dict) -> dict:
    tfa = s["floor_area_m2"]
    storeys = 1 if s["property_type"] in ("bungalow", "flat") else 2
    footprint = tfa / storeys
    perimeter = 4.0 * math.sqrt(footprint)
    gross_wall = perimeter * STOREY_HEIGHT * storeys * EXPOSURE[s["property_type"]]
    window = WINDOW_FRACTION * tfa
    return dict(wall=max(gross_wall - window, 5.0), window=window,
                roof=footprint if s["has_loft"] else 0.0, floor=footprint if s["has_ground_floor"] else 0.0,
                volume=tfa * STOREY_HEIGHT)


def heat_loss_coefficient(s: dict) -> float:
    """Heat loss coefficient (W/K) = Σ U·A + ventilation."""
    a = envelope(s)
    fabric = (a["wall"] * u_wall(s["wall_type"], s["wall_insulated"], s["age_band"])
              + a["roof"] * (u_roof(s["loft_mm"]) if s["has_loft"] else 0.0)
              + a["floor"] * (0.25 if s["floor_insulated"] else 0.6)
              + a["window"] * U_WINDOW[s["glazing"]])
    ach = ACH_BY_AGE[AGE_BANDS.index(s["age_band"])] * s["ach_factor"]
    return fabric + 0.33 * ach * a["volume"]


def hlc_per_m2(s: dict) -> float:
    return heat_loss_coefficient(s) / s["floor_area_m2"]
