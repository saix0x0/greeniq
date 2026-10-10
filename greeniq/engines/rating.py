"""SAP-style rating model: estimate a missing EPC rating and the rating after retrofits.

Uses the public SAP 2012 cost-based rating formula under *standard* occupancy and climate:
    ECF = 0.42 × annual cost (£) / (floor area + 45)
    SAP = 117 − 121·log10(ECF)  if ECF ≥ 3.5,  else  100 − 13.95·ECF
with SAP-2012-style unit prices. This is an approximation for estimating *changes*, not
an accredited SAP calculation. When a recorded rating exists, we anchor on it and add
the modelled change, so the model's own bias cancels out.
"""

from __future__ import annotations

import copy
import math

from . import physics
from .energy import EnergyState, sap_occupancy, standard_hot_water_heat

RATING_VERSION = "sap-style-rating/1.0"
PRICE_P_PER_KWH = {"gas": 3.48, "electricity": 13.19, "offpeak": 5.50}
DEFLATOR = 0.42
STANDARD_HDD = 2100.0
CONTROL_FACTOR = {"none": 1.05, "programmer_thermostat": 1.0, "programmer_thermostat_trvs": 0.97,
                  "smart_thermostat": 0.95, "smart_zoned": 0.93}


def sap_from_cost(cost_pounds: float, tfa: float) -> float:
    ecf = DEFLATOR * max(cost_pounds, 1.0) / (tfa + 45.0)
    sap = 117 - 121 * math.log10(ecf) if ecf >= 3.5 else 100 - 13.95 * ecf
    return max(1.0, min(sap, 120.0))


def standard_cost(st: EnergyState) -> float:
    """Annual energy cost (£) of a home under standard occupancy, climate and prices."""
    tfa = st.phys["floor_area_m2"]
    q_space = (physics.heat_loss_coefficient(st.phys) * STANDARD_HDD * 24 / 1000 * 0.85
               * CONTROL_FACTOR.get(st.controls, 1.0))
    q_hw = standard_hot_water_heat(tfa)
    la = 207.8 * (tfa * sap_occupancy(tfa)) ** 0.4714 + 6.0 * tfa
    p = PRICE_P_PER_KWH
    pence = la * p["electricity"]
    if st.gas_heated:
        pence += (q_space + q_hw) / st.eff * p["gas"]
    elif st.heating_system == "electric_storage":
        pence += q_space * p["offpeak"] + q_hw * p["electricity"]
    elif st.heat_pump:
        pence += (q_space / st.eff + q_hw / st.hw_efficiency()) * p["electricity"]
    else:
        pence += (q_space + q_hw) * p["electricity"]
    pence -= st.pv_generation() * p["electricity"]
    return pence / 100.0


def model_sap(st: EnergyState) -> float:
    return sap_from_cost(standard_cost(st), st.phys["floor_area_m2"])


def sap_after(anchor_sap: float, before: EnergyState, after: EnergyState) -> float:
    """Recorded (or estimated) SAP plus the modelled change from ``before`` to ``after``."""
    return max(1.0, min(anchor_sap + model_sap(after) - model_sap(before), 120.0))


def with_heating_as_recorded(st: EnergyState, system: str, eff: float) -> EnergyState:
    s = copy.deepcopy(st)
    s.heating_system, s.eff = system, eff
    return s
