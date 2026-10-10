"""The synthetic "world": a transparent, seeded simulator of UK homes, meters and sales.

WHY THIS EXISTS
PS2 allows synthetic data but warns against arbitrary labels. So instead of inventing
labels, we simulate a plausible world with physics-lite heat loss, people, weather,
installers and a housing market, and then *observe* it the way a bank would: through
property records (with gaps and errors), monthly meter reads (with gaps) and sale prices.

INDEPENDENCE FROM THE ENGINES (important for honest evaluation)
GreenIQ's engines never import this module. The world contains hidden truth the engines
cannot see: occupant numbers and heating behaviour, under-heating of leaky homes
("prebound") that disappears after insulation (comfort take-back), installation quality,
the real spread of heat-pump efficiency, smart-thermostat effects that vary by household,
a location premium on prices, and record errors. Engines are evaluated against what the
world *measures* (meters, prices) and, for ranking, against the world's own counterfactual
oracle. Agreement with this world is evidence the pipeline works; it is NOT evidence of
real-world accuracy. Every constant below is disclosed in ``data/DATA_CARD.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

WORLD_VERSION = "greeniq-world/1.0"

# --- Calendar ------------------------------------------------------------------------------
MONTHS = pd.period_range("2023-10", "2026-09", freq="M")  # 36 months of meter history
BASELINE_MONTHS = MONTHS[-12:]  # the latest 12 months describe the home as it is now
INSTALL_WINDOW = MONTHS[12:24]  # historical retrofits happened 2024-10 .. 2025-09
DAYS = {p: p.days_in_month for p in MONTHS}

# --- Regions (synthetic constants, shaped like UK regional patterns; not official data) ---
REGIONS = {
    #             share  HDD normal  PV kWh/kWp  £/m² (2026)  gas-grid share
    "london":     (0.13, 1950, 950, 7000, 0.92),
    "south_east": (0.16, 2050, 980, 4300, 0.88),
    "south_west": (0.10, 1950, 1000, 3600, 0.80),
    "midlands":   (0.18, 2250, 900, 2800, 0.88),
    "north":      (0.24, 2400, 850, 2300, 0.90),
    "wales":      (0.06, 2200, 920, 2400, 0.78),
    "scotland":   (0.13, 2650, 800, 2300, 0.80),
}
# Normal-year share of heating degree days by calendar month (Jan..Dec), sums to 1.
HDD_MONTH_SHARE = np.array([15.5, 13.5, 12.5, 9.0, 5.5, 2.5, 1.2, 1.3, 3.0, 7.0, 11.5, 14.5])
HDD_MONTH_SHARE = HDD_MONTH_SHARE / HDD_MONTH_SHARE.sum()
PV_MONTH_SHARE = np.array([3, 5, 8, 11, 13, 13, 13, 11, 9, 6, 4, 3], dtype=float)
PV_MONTH_SHARE = PV_MONTH_SHARE / PV_MONTH_SHARE.sum()

AGE_BANDS = ["pre_1919", "1919_1944", "1945_1964", "1965_1980", "1981_2002", "post_2002"]
TYPES = ["detached", "semi_detached", "terraced", "bungalow", "flat"]

# SAP-2012-style pricing used only by the simulated EPC assessor (pence/kWh, approximate).
SAP_PRICE = {"gas": 3.48, "electricity": 13.19, "offpeak": 5.50}
SAP_DEFLATOR = 0.42
SAP_STANDARD_HDD = 2100.0

# Planted EPC price premiums relative to band D, informed by the order of magnitude in
# Fuerst et al. (DECC 2013; Energy Economics 2015). The value model can only recover these.
EPC_PREMIUM = {"A": 0.050, "B": 0.040, "C": 0.018, "D": 0.0, "E": -0.010, "F": -0.025, "G": -0.060}
TYPE_PRICE = {"detached": 1.12, "semi_detached": 1.0, "terraced": 0.95, "bungalow": 1.05, "flat": 0.92}
AGE_PRICE = {"pre_1919": 1.03, "1919_1944": 1.0, "1945_1964": 0.95, "1965_1980": 0.95,
             "1981_2002": 0.98, "post_2002": 1.04}

HEAT_SCALE = 0.86  # global calibration so the median gas home lands near Ofgem's TDCV


# --- Physics-lite heat loss ------------------------------------------------------------------

def _storeys(ptype: str) -> int:
    return 1 if ptype in ("bungalow", "flat") else 2


def heat_loss_coefficient(s: dict) -> float:
    """Heat loss coefficient (W/K) from geometry, U-values and air change rate."""
    tfa = s["floor_area_m2"]
    storeys = _storeys(s["property_type"])
    footprint = tfa / storeys
    perimeter = 4.0 * math.sqrt(footprint) * 1.05
    exposed = {"detached": 1.0, "semi_detached": 0.75, "terraced": s.get("terrace_exposure", 0.5),
               "bungalow": 1.0, "flat": 0.55}[s["property_type"]]
    gross_wall = perimeter * 2.5 * storeys * exposed
    window = 0.18 * tfa
    net_wall = max(gross_wall - window, 5.0)

    age_i = AGE_BANDS.index(s["age_band"])
    if s["wall_type"] == "solid":
        u_wall = 0.35 if s["wall_insulated"] else 2.1
    else:
        if s["wall_insulated"]:
            u_wall = 0.30 if age_i == 5 else (0.45 if age_i == 4 else 0.55)
        else:
            u_wall = 1.5 if age_i <= 2 else 1.0
    if s["wall_insulated"] and s.get("wall_quality") is not None and not s.get("wall_built_insulated", False):
        # installation quality: only part of the theoretical improvement is realised
        u_uninsulated = 2.1 if s["wall_type"] == "solid" else (1.5 if age_i <= 2 else 1.0)
        u_wall = u_uninsulated - s["wall_quality"] * (u_uninsulated - u_wall)

    roof = footprint if s["has_roof"] else 0.0
    u_roof = 1.0 / (0.43 + (s["loft_mm"] or 0) / 1000.0 / 0.04) if s["has_roof"] else 0.0
    floor = footprint if s["has_ground_floor"] else 0.0
    u_floor = 0.25 if s["floor_insulated"] else 0.7
    u_win = {"single": 4.8, "secondary": 2.4, "double_pre_2002": 2.8, "double_post_2002": 1.6, "triple": 1.0}[s["glazing"]]
    fabric = (net_wall * u_wall + roof * u_roof + floor * u_floor + window * u_win) * 1.10  # thermal bridging
    ach = [1.0, 0.9, 0.8, 0.7, 0.6, 0.45][age_i]
    if s["glazing"] in ("double_post_2002", "triple"):
        ach *= 0.92
    vent = 0.33 * ach * tfa * 2.5
    return fabric + vent


def prebound(hlc_per_m2: float) -> float:
    """Leaky homes are under-heated in practice (less heat than physics predicts)."""
    return float(np.clip(1.0 - 0.093 * (hlc_per_m2 - 1.5), 0.72, 1.0))


def heating_efficiency(s: dict, hlc_per_m2: float) -> float:
    hs = s["heating_system"]
    if hs == "gas_boiler_condensing":
        return max(0.70, 0.86 - 0.005 * max(0, s["boiler_age"] - 10) + s.get("eff_noise", 0.0))
    if hs == "gas_boiler_noncondensing":
        return max(0.60, 0.74 - 0.004 * max(0, s["boiler_age"] - 15) + s.get("eff_noise", 0.0))
    if hs in ("electric_direct", "electric_storage"):
        return 1.0
    scop = 3.35 - 0.9 * float(np.clip((hlc_per_m2 - 1.2) / 2.2, 0, 1)) + s.get("scop_noise", 0.0)
    if hs == "ground_source_heat_pump":
        scop += 0.45
    return max(2.0, scop)


CONTROL_FACTOR = {"none": 1.08, "programmer_thermostat": 1.0, "programmer_thermostat_trvs": 0.96,
                  "smart_thermostat": None, "smart_zoned": None}


def control_factor(s: dict) -> float:
    c = s["controls"]
    if c == "smart_thermostat":
        return 1.0 - s.get("smart_effect", 0.05)
    if c == "smart_zoned":
        return 0.96 - s.get("smart_effect", 0.05)
    return CONTROL_FACTOR[c]


def monthly_consumption(s: dict, h: dict, hdd: float, month_idx: int, days: int) -> tuple[float, float, dict]:
    """Expected purchased (electricity_import_kwh, gas_kwh) for one month, plus end uses."""
    if h["void"]:
        return 0.0, 0.0, {}
    tfa = s["floor_area_m2"]
    hlc = heat_loss_coefficient(s)
    hlc_m2 = hlc / tfa
    eff = heating_efficiency(s, hlc_m2)
    space_heat = hlc * hdd * 24 / 1000 * HEAT_SCALE * prebound(hlc_m2) * h["behaviour"] * control_factor(s)
    season = 1.12 if month_idx in (11, 0, 1, 2) else (0.9 if month_idx in (5, 6, 7) else 1.0)
    hot_water = (600 + 450 * h["occupants"]) / 365 * days * season
    appliances = (900 + 550 * h["occupants"] + 4 * tfa) * h["appliance_factor"] / 365 * days
    appliances *= 1.15 if month_idx in (10, 11, 0, 1) else (0.9 if month_idx in (5, 6, 7) else 1.0)

    gas = elec = 0.0
    hs = s["heating_system"]
    if hs.startswith("gas_boiler"):
        gas += (space_heat + hot_water) / eff
        elec += 150 / 365 * days  # pump and fan
    elif hs.endswith("heat_pump"):
        elec += space_heat / eff + hot_water / max(eff - 0.6, 1.8)
    else:
        elec += space_heat / eff + hot_water
    if h["gas_hob"] and s["has_gas"]:
        gas += 300 / 365 * days
    else:
        elec += 350 / 365 * days
    demand = elec + appliances

    gen = s["pv_kwp"] * h["pv_yield"] * PV_MONTH_SHARE[month_idx]
    self_cons = min(gen * (0.35 + 0.15 * h["daytime_home"]), 0.6 * demand)
    imports = demand - self_cons
    return imports, gas, {"space_heat": space_heat, "demand_elec": demand, "pv_gen": gen, "self_cons": self_cons}


def annual_normal(s: dict, h: dict) -> dict:
    """Oracle: expected annual consumption in a normal weather year (no meter noise)."""
    hdd_normal = REGIONS[s["region"]][1]
    tot_e = tot_g = 0.0
    for m in range(12):
        days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m]
        e, g, _ = monthly_consumption(s, h, hdd_normal * HDD_MONTH_SHARE[m], m, days)
        tot_e += e
        tot_g += g
    return {"electricity": tot_e, "gas": tot_g, "purchased": tot_e + tot_g}


# --- The simulated EPC assessor -------------------------------------------------------------

def sap_occupancy(tfa: float) -> float:
    x = tfa - 13.9
    return 1 + 1.76 * (1 - math.exp(-0.000349 * x * x)) + 0.0013 * x if tfa > 13.9 else 1.0


def true_sap(s: dict) -> float:
    """SAP-2012-style rating under standard occupancy and climate (cost-based, PV credited)."""
    tfa = s["floor_area_m2"]
    n = sap_occupancy(tfa)
    hlc = heat_loss_coefficient(s)
    hlc_m2 = hlc / tfa
    std = dict(s)
    std["boiler_age"] = s.get("boiler_age", 10)
    std_h = {"scop_noise": 0.0}
    eff = heating_efficiency({**std, **std_h, "eff_noise": 0.0}, hlc_m2)
    space = hlc * SAP_STANDARD_HDD * 24 / 1000 * HEAT_SCALE * control_factor({**s, "smart_effect": 0.05})
    hw = 600 + 450 * n
    la = 900 + 400 * n + 3 * tfa
    hs = s["heating_system"]
    cost = la * SAP_PRICE["electricity"]
    if hs.startswith("gas_boiler"):
        cost += (space + hw) / eff * SAP_PRICE["gas"] + 150 * SAP_PRICE["electricity"]
    elif hs == "electric_storage":
        cost += space * SAP_PRICE["offpeak"] + hw * SAP_PRICE["electricity"]
    elif hs == "electric_direct":
        cost += (space + hw) * SAP_PRICE["electricity"]
    else:
        cost += (space / eff + hw / max(eff - 0.6, 1.8)) * SAP_PRICE["electricity"]
    cost -= s["pv_kwp"] * 900 * SAP_PRICE["electricity"] * {"south": 1.0, "east_west": 0.85, "north": 0.6}.get(
        s.get("roof_orientation") or "east_west", 0.85)
    ecf = SAP_DEFLATOR * max(cost, 1.0) / 100.0 / (tfa + 45)
    sap = 117 - 121 * math.log10(ecf) if ecf >= 3.5 else 100 - 13.95 * ecf
    return float(np.clip(sap, 1, 120))


def sap_band(sap: float) -> str:
    for t, b in [(92, "A"), (81, "B"), (69, "C"), (55, "D"), (39, "E"), (21, "F")]:
        if sap >= t:
            return b
    return "G"


# --- Retrofits as they really happen (with quality and comfort take-back) -----------------

PV_SIZE = {"detached": 4.0, "semi_detached": 3.5, "terraced": 3.0, "bungalow": 3.5, "flat": 0.0}


def truly_feasible(s: dict) -> dict[str, tuple[bool, str]]:
    """Ground-truth feasibility, judged on the TRUE state (records may be wrong)."""
    out = {}
    out["loft_insulation"] = (s["has_roof"] and (s["loft_mm"] or 0) < 200,
                              "no roof space" if not s["has_roof"] else "loft already at 200 mm or more")
    out["cavity_wall_insulation"] = (s["wall_type"] == "cavity" and not s["wall_insulated"], "not an unfilled cavity")
    out["solid_wall_insulation"] = (s["wall_type"] == "solid" and not s["wall_insulated"], "not an uninsulated solid wall")
    out["glazing_upgrade"] = (s["glazing"] in ("single", "secondary", "double_pre_2002"), "glazing already modern")
    hp_ok = (not s["heating_system"].endswith("heat_pump")) and s["outdoor_space"]
    out["air_source_heat_pump"] = (hp_ok, "no outdoor space or already a heat pump")
    pv_ok = s["property_type"] != "flat" and s["pv_kwp"] == 0 and s.get("roof_orientation") != "north" \
        and not s["listed"]
    out["solar_pv"] = (pv_ok, "flat, north-facing, listed or already has PV")
    out["smart_controls"] = (s["controls"] not in ("smart_thermostat", "smart_zoned")
                             and s["heating_system"] not in ("electric_storage", "electric_direct"),
                             "already smart or no wet/heat-pump system")
    return {k: (bool(v[0]), "" if v[0] else v[1]) for k, v in out.items()}


def apply_measure(s: dict, h: dict, measure: str) -> dict:
    """Return the TRUE state after a measure, as a real installer would leave it."""
    t = dict(s)
    if measure == "loft_insulation":
        t["loft_mm"] = 270
    elif measure in ("cavity_wall_insulation", "solid_wall_insulation"):
        t["wall_insulated"] = True
        t["wall_quality"] = h["install_quality"]
    elif measure == "glazing_upgrade":
        t["glazing"] = "double_post_2002"
    elif measure == "air_source_heat_pump":
        t["heating_system"] = "air_source_heat_pump"
        t["scop_noise"] = h["scop_noise"]
    elif measure == "solar_pv":
        t["pv_kwp"] = PV_SIZE[s["property_type"]]
    elif measure == "smart_controls":
        t["controls"] = "smart_thermostat"
        t["smart_effect"] = h["smart_effect"]
    return t


# --- World generation ---------------------------------------------------------------------

@dataclass
class World:
    customers: pd.DataFrame
    properties: pd.DataFrame  # the RECORDED view (gaps, errors, stale EPCs)
    meter_readings: pd.DataFrame
    weather: pd.DataFrame
    weather_normals: pd.DataFrame
    sales: pd.DataFrame
    market_index: pd.DataFrame
    retrofit_history: pd.DataFrame
    hidden: pd.DataFrame  # TRUE state + hidden variables; evaluation only


def _choice(rng, options: dict):
    keys = list(options)
    p = np.array(list(options.values()), dtype=float)
    return keys[rng.choice(len(keys), p=p / p.sum())]


def _true_home(rng, pid: str, cid: str, region: str) -> tuple[dict, dict]:
    ptype = _choice(rng, {"detached": .17, "semi_detached": .26, "terraced": .28, "bungalow": .08, "flat": .21})
    age_w = {"pre_1919": .20, "1919_1944": .16, "1945_1964": .19, "1965_1980": .20, "1981_2002": .15, "post_2002": .10}
    if ptype == "flat":
        age_w.update({"pre_1919": .12, "1965_1980": .22, "1981_2002": .2, "post_2002": .2})
    age = _choice(rng, age_w)
    ai = AGE_BANDS.index(age)
    med = {"detached": 140, "semi_detached": 88, "terraced": 80, "bungalow": 78, "flat": 60}[ptype]
    tfa = float(np.clip(rng.lognormal(math.log(med), 0.22), 28, 520))
    pos = _choice(rng, {"ground": .35, "mid": .35, "top": .30}) if ptype == "flat" else None

    wall_type = "solid" if (ai == 0 and rng.random() < .92) or (ai == 1 and rng.random() < .35) else "cavity"
    built_ins = wall_type == "cavity" and ai >= 4
    if wall_type == "cavity":
        wall_ins = built_ins or rng.random() < .65
    else:
        wall_ins = rng.random() < .10
    has_roof = ptype != "flat" or pos == "top"
    has_ground = ptype != "flat" or pos == "ground"
    if has_roof:
        loft = 270 if ai == 5 and rng.random() < .7 else int(_choice(rng, {0: .04, 25: .06, 50: .08, 100: .22, 150: .20, 200: .18, 270: .22}))
        if ai == 5:
            loft = max(loft, 200)
    else:
        loft = None
    floor_ins = rng.random() < [.08, .08, .08, .08, .40, .95][ai]
    if ai == 5:
        glazing = _choice(rng, {"double_post_2002": .85, "triple": .15})
    else:
        single = .12 if ai == 0 else .04
        glazing = _choice(rng, {"single": single, "secondary": .05 if ai == 0 else .01,
                                "double_pre_2002": .55, "double_post_2002": .40 - single})

    has_gas = rng.random() < REGIONS[region][4] * (0.78 if ptype == "flat" else 1.0)
    boiler_age = int(rng.integers(0, 31))
    if has_gas:
        if rng.random() < .025:
            heating = "air_source_heat_pump"
        elif boiler_age <= 19 or rng.random() < .2:
            heating = "gas_boiler_condensing"
        else:
            heating = "gas_boiler_noncondensing"
    else:
        heating = _choice(rng, {"electric_storage": .50, "electric_direct": .28, "air_source_heat_pump": .17,
                                "ground_source_heat_pump": .05})
        if ptype == "flat" and heating == "ground_source_heat_pump":
            heating = "electric_storage"
    if heating in ("electric_storage", "electric_direct"):
        controls = _choice(rng, {"none": .35, "programmer_thermostat": .55, "programmer_thermostat_trvs": .10})
    else:
        controls = _choice(rng, {"none": .06, "programmer_thermostat": .42, "programmer_thermostat_trvs": .28,
                                 "smart_thermostat": .19, "smart_zoned": .05})
    orient = _choice(rng, {"south": .3, "east_west": .5, "north": .2}) if has_roof and ptype != "flat" else None
    pv = 0.0
    if ptype != "flat" and orient != "north" and rng.random() < (.06 + .06 * (ai == 5)):
        pv = round(float(rng.uniform(2.0, 4.5)), 1)
    listed = rng.random() < [.18, .06, .01, .01, .01, .0][ai]
    outdoor = rng.random() < (0.97 if ptype != "flat" else (0.5 if pos == "ground" else 0.08))

    s = dict(property_id=pid, customer_id=cid, region=region, property_type=ptype, flat_position=pos, age_band=age,
             floor_area_m2=round(tfa, 1), wall_type=wall_type, wall_insulated=wall_ins, wall_built_insulated=built_ins,
             has_roof=has_roof, has_ground_floor=has_ground, loft_mm=loft, floor_insulated=floor_ins,
             glazing=glazing, heating_system=heating, boiler_age=boiler_age, has_gas=has_gas, controls=controls,
             pv_kwp=pv, roof_orientation=orient, roof_shading=_choice(rng, {"low": .6, "medium": .3, "high": .1}) if orient else None,
             listed=listed, outdoor_space=outdoor, terrace_exposure=0.5 if rng.random() < .7 else 0.75,
             eff_noise=float(rng.normal(0, 0.03)), scop_noise=float(rng.normal(0, 0.25)),
             smart_effect=float(rng.uniform(0.0, 0.10)), wall_quality=None)
    if s["heating_system"].endswith("heat_pump"):
        pass
    shade = {"low": 1.0, "medium": 0.85, "high": 0.65}.get(s["roof_shading"] or "low", 1.0)
    orient_f = {"south": 1.0, "east_west": 0.85, "north": 0.6}.get(orient or "east_west", 0.85)
    occupants = int(_choice(rng, {1: .29, 2: .35, 3: .15, 4: .14, 5: .07}))
    h = dict(occupants=occupants, behaviour=float(rng.lognormal(0, 0.18)),
             appliance_factor=float(rng.lognormal(0, 0.20)), daytime_home=bool(rng.random() < .35),
             gas_hob=bool(rng.random() < .6), install_quality=float(rng.uniform(0.6, 1.0)),
             scop_noise=s["scop_noise"], smart_effect=s["smart_effect"],
             pv_yield=REGIONS[region][2] * orient_f * shade, loc_quality=float(rng.lognormal(0, 0.15)),
             void=bool(rng.random() < .008))
    return s, h


def _observe(rng, s: dict, sap_recorded: float | None, epc_year: int | None, hp_error: bool) -> dict:
    """Turn a TRUE state into the RECORDED property row (missing fields, errors)."""
    def maybe(v, p):
        return None if rng.random() < p else v

    rec = dict(
        property_id=s["property_id"], customer_id=s["customer_id"], region=s["region"],
        property_type=s["property_type"], flat_position=s["flat_position"],
        age_band=maybe(s["age_band"], .04), floor_area_m2=maybe(s["floor_area_m2"], .03),
        wall_type=maybe(s["wall_type"], .12), wall_insulated=maybe(s["wall_insulated"], .15),
        has_loft=None, loft_insulation_mm=maybe(s["loft_mm"], .18) if s["has_roof"] else None,
        floor_insulated=maybe(s["floor_insulated"], .35) if s["has_ground_floor"] else None,
        glazing=maybe(s["glazing"], .06),
        heating_system="air_source_heat_pump" if hp_error else maybe(s["heating_system"], .02),
        boiler_age_years=maybe(s["boiler_age"], .2) if s["heating_system"].startswith("gas_boiler") and not hp_error else None,
        has_gas_connection=maybe(s["has_gas"], .05), controls=maybe(s["controls"], .10),
        solar_pv_kwp=maybe(s["pv_kwp"], .05), roof_orientation=maybe(s["roof_orientation"], .10),
        roof_shading=maybe(s["roof_shading"], .10),
        epc_band=None, sap_score=None, epc_year=None,
        listed_or_conservation=maybe(s["listed"], .10), outdoor_space=maybe(s["outdoor_space"], .15),
    )
    if sap_recorded is not None and rng.random() > .12:
        rec["epc_band"] = sap_band(sap_recorded)
        rec["sap_score"] = None if rng.random() < .05 else int(round(sap_recorded))
        rec["epc_year"] = epc_year
    if s["property_type"] == "flat" and rng.random() < .05:
        rec["flat_position"] = None
    return rec


def generate_world(n_properties: int = 3000, seed: int = 42) -> World:
    rng = np.random.default_rng(seed)
    regions = list(REGIONS)
    region_p = np.array([REGIONS[r][0] for r in regions])
    region_p /= region_p.sum()

    # Weather: actual monthly HDD per region (normal × year factor × month noise).
    weather_rows, normals_rows = [], []
    year_factor = {(r, y): float(rng.normal(1.0, 0.07)) for r in regions for y in (2023, 2024, 2025, 2026)}
    for r in regions:
        for m in range(12):
            normals_rows.append(dict(region=r, calendar_month=m + 1, hdd_normal=round(REGIONS[r][1] * HDD_MONTH_SHARE[m], 2)))
        for p in MONTHS:
            heating_year = p.year if p.month >= 10 else p.year - 1
            hdd = REGIONS[r][1] * HDD_MONTH_SHARE[p.month - 1] * year_factor[(r, heating_year)] * float(rng.normal(1, 0.08))
            weather_rows.append(dict(region=r, month=str(p), hdd=round(max(hdd, 0.0), 2)))
    weather = pd.DataFrame(weather_rows)
    hdd_lookup = {(w.region, w.month): w.hdd for w in weather.itertuples()}

    # Market index (synthetic HPI-like), 2026 = 1.0 reference in each region.
    idx_rows = []
    for r in regions:
        g = 0.036 if r == "london" else 0.028
        for y in range(2011, 2027):
            v = (1 + g) ** (y - 2026) * (0.97 if y >= 2023 else 1.0) / 0.97
            idx_rows.append(dict(region=r, year=y, index=round(v, 4)))
    market_index = pd.DataFrame(idx_rows)
    idx_lookup = {(m.region, m.year): m.index for m in market_index.itertuples()}

    customers, recorded, hidden_rows, meter_rows, sales_rows, retro_rows = [], [], [], [], [], []
    pid_n = 0
    cid_n = 0
    while pid_n < n_properties:
        cid_n += 1
        cid = f"C{cid_n:05d}"
        region = regions[rng.choice(len(regions), p=region_p)]
        customers.append(dict(customer_id=cid, region=region))
        n_props = int(_choice(rng, {1: .82, 2: .12, 3: .04, 4: .02}))
        for _ in range(n_props):
            if pid_n >= n_properties:
                break
            pid_n += 1
            pid = f"P{pid_n:05d}"
            s, h = _true_home(rng, pid, cid, region)

            # Historical retrofit (some homes did one measure during the meter window).
            install = None
            s_before = dict(s)
            feas = truly_feasible(s)
            if rng.random() < .18 and not h["void"]:
                options = {k: w for k, w in {"loft_insulation": .25, "cavity_wall_insulation": .20, "smart_controls": .20,
                                              "solar_pv": .12, "glazing_upgrade": .10, "air_source_heat_pump": .08,
                                              "solid_wall_insulation": .05}.items() if feas[k][0]}
                if options:
                    measure = _choice(rng, options)
                    install = INSTALL_WINDOW[int(rng.integers(0, len(INSTALL_WINDOW)))]
                    s = apply_measure(s, h, measure)
                    if measure == "air_source_heat_pump" and not s["has_gas"]:
                        pass
                    retro_rows.append(dict(property_id=pid, measure_id=measure, install_month=str(install)))

            # EPC lodged some time 2010-2025; stale if lodged before the retrofit.
            epc_year = int(rng.integers(2010, 2026))
            sap_now, sap_before = true_sap(s), true_sap(s_before)
            stale = install is not None and epc_year <= install.year
            sap_rec = (sap_before if stale else sap_now) + float(rng.normal(0, 2.5))
            hp_error = s["heating_system"].startswith("gas_boiler") and rng.random() < .012
            recorded.append(_observe(rng, s, float(np.clip(sap_rec, 1, 120)), epc_year, hp_error))

            # Monthly meter reads.
            coverage = _choice(rng, {"full": .93, "recent_only": .05, "none": .02})
            first = 0 if coverage == "full" else (36 - int(rng.integers(3, 6)) if coverage == "recent_only" else 36)
            for i, p in enumerate(MONTHS):
                state = s if (install is None or p >= install) else s_before
                e, g, _ = monthly_consumption(state, h, hdd_lookup[(region, str(p))], p.month - 1, DAYS[p])
                if i < first:
                    continue
                miss = rng.random() < .04
                noise = rng.lognormal(0, 0.04, size=2)
                meter_rows.append(dict(property_id=pid, month=str(p), fuel="electricity",
                                       kwh=None if miss else round(e * noise[0], 1)))
                if s["has_gas"]:
                    meter_rows.append(dict(property_id=pid, month=str(p), fuel="gas",
                                           kwh=None if miss else round(g * noise[1], 1)))

            # Sales history and current true value.
            base_value = (REGIONS[region][3] * s["floor_area_m2"] ** 0.85 * 90 ** 0.15 * TYPE_PRICE[s["property_type"]]
                          * AGE_PRICE[s["age_band"]] * h["loc_quality"])
            for _ in range(int(rng.poisson(0.9))):
                year = int(rng.integers(2011, 2027))
                month = int(rng.integers(1, 13)) if year < 2026 else int(rng.integers(1, 10))
                sap_sale = (sap_before if (install is None or year < install.year) else sap_now) + float(rng.normal(0, 2.5))
                band = sap_band(sap_sale)
                price = base_value * (1 + EPC_PREMIUM[band]) * idx_lookup[(region, year)] * float(rng.lognormal(0, 0.05))
                sales_rows.append(dict(property_id=pid, sale_date=f"{year}-{month:02d}", price=int(round(price, -2)),
                                       epc_band_at_sale=band, sap_at_sale=int(round(np.clip(sap_sale, 1, 120)))))

            hidden_rows.append(dict(
                property_id=pid, customer_id=cid, **{f"true_{k}": v for k, v in s.items() if k not in ("property_id", "customer_id")},
                **h, true_sap_now=round(sap_now, 2), epc_stale=stale, recorded_heating_error=hp_error,
                true_value_2026=int(round(base_value * (1 + EPC_PREMIUM[sap_band(sap_now)]), -2)),
            ))

    return World(
        customers=pd.DataFrame(customers),
        properties=pd.DataFrame(recorded),
        meter_readings=pd.DataFrame(meter_rows),
        weather=weather,
        weather_normals=pd.DataFrame(normals_rows),
        sales=pd.DataFrame(sales_rows),
        market_index=market_index,
        retrofit_history=pd.DataFrame(retro_rows, columns=["property_id", "measure_id", "install_month"]),
        hidden=pd.DataFrame(hidden_rows),
    )


def hidden_state(row: dict) -> tuple[dict, dict]:
    """Rebuild (true state, hidden variables) from a row of ``hidden.csv`` for the oracle."""
    s = {k[5:]: v for k, v in row.items() if k.startswith("true_") and k not in ("true_sap_now", "true_value_2026")}
    s["property_id"] = row["property_id"]
    s["region"] = row.get("true_region", row.get("region"))
    for k in ("loft_mm", "flat_position", "roof_orientation", "roof_shading", "wall_quality"):
        if k in s and isinstance(s[k], float) and math.isnan(s[k]):
            s[k] = None
    h = {k: row[k] for k in ("occupants", "behaviour", "appliance_factor", "daytime_home", "gas_hob", "install_quality",
                             "scop_noise", "smart_effect", "pv_yield", "loc_quality", "void")}
    return s, h
