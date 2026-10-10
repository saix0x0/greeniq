"""Green Home Score mappings: the PS2-fixed weights and our documented sub-score tables.

Everything here is *data*. ``greeniq/score.py`` only interpolates and sums it.
The full rationale for each table is in ``docs/SCORING_METHOD.md``.

Monotonicity is guaranteed by construction and enforced by tests:
- numeric inputs use piecewise-linear interpolation through monotone knots;
- categorical inputs use ladders listed from worst to best, whose scores never decrease.
"""

from __future__ import annotations

MAPPING_VERSION = "score-mappings/1.1"

# --- PS2-fixed (not ours to change) -------------------------------------------------
WEIGHTS: dict[str, float] = {
    "energy_efficiency": 0.25,
    "consumption_intensity": 0.20,
    "insulation": 0.15,
    "heating_system": 0.15,
    "glazing": 0.10,
    "renewables": 0.10,
    "smart_controls": 0.05,
}

LABELS: dict[str, str] = {
    "energy_efficiency": "Energy efficiency",
    "consumption_intensity": "Energy consumption intensity",
    "insulation": "Insulation",
    "heating_system": "Heating system",
    "glazing": "Windows and glazing",
    "renewables": "Renewable energy",
    "smart_controls": "Smart energy management",
}

# (lower bound inclusive, upper bound inclusive, label), applied to the rounded integer score.
BANDS: list[tuple[int, int, str]] = [
    (80, 100, "Highly efficient"),
    (65, 79, "Good"),
    (50, 64, "Moderate"),
    (30, 49, "Poor"),
    (0, 29, "Very poor"),
]
POOR_BANDS = ("Poor", "Very poor")

# --- Energy efficiency (25%): the recorded EPC rating -------------------------------
# A SAP score (1-100+) is already a 0-100 efficiency scale, so it maps one-to-one
# (clamped). When only the band letter is known we use the band's midpoint.
EPC_BAND_MIDPOINT: dict[str, float] = {
    "G": 10.5, "F": 29.5, "E": 46.5, "D": 61.5, "C": 74.5, "B": 86.0, "A": 96.0,
}
# Official EPC band thresholds on the SAP scale (A 92+, B 81-91, ... G 1-20).
SAP_BANDS: list[tuple[int, str]] = [(92, "A"), (81, "B"), (69, "C"), (55, "D"), (39, "E"), (21, "F"), (1, "G")]

# --- Consumption intensity (20%): annualised purchased energy per m² ----------------
# kWh/m²/yr → sub-score. Decreasing: more energy per m² never scores higher.
# Calibration anchor (v1.1): a typical UK home should land mid-'Moderate'.
# Anchors: a typical UK dual-fuel home (11,500 kWh gas + 2,700 kWh electricity, Ofgem
# TDCV) over ~90 m² is ≈158 kWh/m² and lands mid-scale; well-insulated heat-pump homes
# run at ≈40-60 kWh/m²; poorly insulated older homes exceed 275.
INTENSITY_KNOTS: list[tuple[float, float]] = [
    (40.0, 100.0), (100.0, 80.0), (150.0, 63.0), (200.0, 47.0), (275.0, 28.0), (400.0, 5.0), (500.0, 0.0),
]

# --- Insulation (15%): walls, roof/loft and floor --------------------------------
# Internal element weights. Elements that do not apply (no loft because another
# dwelling is above; no ground floor in an upper flat) are dropped and the remaining
# element weights are renormalised, so a flat is not penalised for a loft it lacks.
INSULATION_ELEMENT_WEIGHTS: dict[str, float] = {"walls": 0.50, "loft": 0.35, "floor": 0.15}
# (wall_type, insulated) → score. Ordering within a wall type: insulated ≥ uninsulated.
WALL_SCORES: dict[tuple[str, bool], float] = {
    ("solid", False): 0.0,     # U ≈ 2.1 W/m²K
    ("cavity", False): 30.0,   # U ≈ 1.5
    ("cavity", True): 80.0,    # U ≈ 0.5
    ("solid", True): 90.0,     # U ≈ 0.3 with internal/external wall insulation
}
# Loft insulation depth (mm) → score; 270 mm is the current recommended depth.
LOFT_KNOTS: list[tuple[float, float]] = [
    (0.0, 0.0), (25.0, 10.0), (50.0, 25.0), (100.0, 55.0), (150.0, 75.0), (200.0, 90.0), (270.0, 100.0),
]
FLOOR_SCORES: dict[bool, float] = {False: 0.0, True: 100.0}

# --- Heating system (15%) ------------------------------------------------------------
# Ladder from worst to best. A single ordering is a judgement call (cost vs carbon), so
# it is stated explicitly: heat pumps lead on both carbon and running cost; condensing
# gas is cheap to run but fossil; storage heaters are grid-carbon but expensive;
# non-condensing boilers waste 20-30% of their fuel; direct electric is the costliest heat.
# Rungs never overlap: even with the maximum boiler-age penalty (12), a gas rung stays
# above the rung below it (non-condensing 30-12=18 > 15; condensing 62-12=50 > 40).
# A property-based test found the overlap when direct electric was set to 20.
HEATING_LADDER: list[tuple[str, float]] = [
    ("electric_direct", 15.0),
    ("gas_boiler_noncondensing", 30.0),
    ("electric_storage", 40.0),
    ("gas_boiler_condensing", 62.0),
    ("air_source_heat_pump", 92.0),
    ("ground_source_heat_pump", 100.0),
]
# Gas boilers lose points with age (efficiency degrades, components wear).
# Penalty is non-decreasing in age, so a newer boiler never scores lower.
BOILER_AGE_PENALTY_KNOTS: list[tuple[float, float]] = [(0.0, 0.0), (10.0, 0.0), (20.0, 10.0), (30.0, 12.0)]

# --- Windows and glazing (10%) -----------------------------------------------------------
GLAZING_LADDER: list[tuple[str, float]] = [
    ("single", 0.0),
    ("secondary", 45.0),
    ("double_pre_2002", 70.0),
    ("double_post_2002", 85.0),
    ("triple", 100.0),
]

# --- Renewable energy (10%): installed solar PV capacity -----------------------------
# kWp → score. ~3.5-4 kWp is a typical full domestic array.
# Heat pumps are scored under "Heating system" only, to avoid counting them twice.
PV_KNOTS: list[tuple[float, float]] = [(0.0, 0.0), (1.0, 30.0), (2.0, 55.0), (3.0, 75.0), (4.0, 100.0)]

# --- Smart energy management (5%) ----------------------------------------------------
CONTROLS_LADDER: list[tuple[str, float]] = [
    ("none", 0.0),
    ("programmer_thermostat", 40.0),
    ("programmer_thermostat_trvs", 60.0),
    ("smart_thermostat", 80.0),
    ("smart_zoned", 100.0),
]

# Which retrofit measures can lift each component (used to link issues to the plan).
IMPROVED_BY: dict[str, list[str]] = {
    "energy_efficiency": ["loft_insulation", "cavity_wall_insulation", "solid_wall_insulation",
                          "glazing_upgrade", "air_source_heat_pump", "solar_pv", "smart_controls"],
    "consumption_intensity": ["loft_insulation", "cavity_wall_insulation", "solid_wall_insulation",
                              "glazing_upgrade", "air_source_heat_pump", "solar_pv", "smart_controls"],
    "insulation": ["loft_insulation", "cavity_wall_insulation", "solid_wall_insulation"],
    "heating_system": ["air_source_heat_pump"],
    "glazing": ["glazing_upgrade"],
    "renewables": ["solar_pv"],
    "smart_controls": ["smart_controls"],
}
