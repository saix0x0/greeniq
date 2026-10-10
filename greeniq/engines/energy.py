"""Per-fuel energy engine: baseline decomposition and interaction-aware retrofit modelling.

1. **Decompose** the home's baseline purchased energy (metered where possible) into end
   uses: useful space heat, useful hot-water heat, cooking gas, other electricity, and
   solar self-consumption. The decomposition reproduces the baseline exactly.
2. **Apply measures in sequence** to that state. Each measure changes physical inputs,
   and later measures see the changed state. That is where interactions come from:
   - insulation cuts the heat a heat pump must supply, *and* raises its efficiency
     (heat-pump SCOP is fixed at installation from the heat loss per m² at that time);
   - a heat pump moves heating from gas to electricity, so gas falls and electricity
     rises (a *negative* electricity saving);
   - solar offsets imports, not demand, and more of it is self-consumed when demand is
     higher (e.g. after a heat pump).
3. **Report per fuel**: baseline, after, saving = baseline − after (negative = increase).

A package result is never the sum of standalone results. The difference is reported.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..contract import Resolved
from . import physics
from .catalogue import assumption, measure

ENERGY_VERSION = "energy-sequential/1.1"  # 1.1: realised-HLC tracking (no super-additive fabric pairs)


def boiler_efficiency(system: str, age: float | None) -> float:
    age = 12.0 if age is None else age
    if system == "gas_boiler_condensing":
        return max(0.78, 0.85 - 0.004 * max(0.0, age - 10))
    return max(0.62, 0.72 - 0.004 * max(0.0, age - 15))


def heat_pump_scop(hlc_m2: float, ground_source: bool = False) -> float:
    """Seasonal COP from heat loss per m²: leaky homes need hotter flow temperatures."""
    e = measure("air_source_heat_pump")["engineering"]
    x = min(max((hlc_m2 - e["hlc_per_m2_good"]) / (e["hlc_per_m2_poor"] - e["hlc_per_m2_good"]), 0.0), 1.0)
    scop = e["scop_best"] - (e["scop_best"] - e["scop_worst"]) * x
    return scop + (0.4 if ground_source else 0.0)


def sap_occupancy(tfa: float) -> float:
    x = tfa - 13.9
    return 1 + 1.76 * (1 - 2.718281828 ** (-0.000349 * x * x)) + 0.0013 * x if tfa > 13.9 else 1.0


def standard_hot_water_heat(tfa: float) -> float:
    return 600.0 + 450.0 * sap_occupancy(tfa)


@dataclass
class EnergyState:
    """The home's energy system as the engine models it (annual, normal weather year)."""

    phys: dict
    region: str
    heating_system: str
    eff: float  # boiler efficiency, 1.0 for resistance heating, SCOP for heat pumps
    q_space: float  # useful space heat delivered, kWh/yr
    q_hw: float  # useful hot-water heat, kWh/yr
    cooking_gas: float
    other_elec: float  # appliances, lighting, electric cooking, pumps
    pv_kwp: float = 0.0
    pv_orientation: str = "east_west"
    pv_shading: str = "low"
    controls: str = "programmer_thermostat"
    installed: list[str] = field(default_factory=list)
    hlc_eff: float | None = None  # realised heat-loss coefficient after fabric measures (None = nominal)

    # --- purchased energy -------------------------------------------------------------
    @property
    def gas_heated(self) -> bool:
        return self.heating_system.startswith("gas_boiler")

    @property
    def heat_pump(self) -> bool:
        return self.heating_system.endswith("heat_pump")

    def hw_efficiency(self) -> float:
        if self.heat_pump:
            pen = measure("air_source_heat_pump")["engineering"]["hot_water_cop_penalty"]
            return max(self.eff - pen, 2.0)
        return self.eff if self.gas_heated else 1.0

    def pv_generation(self) -> float:
        if self.pv_kwp <= 0:
            return 0.0
        e = measure("solar_pv")["engineering"]
        return (self.pv_kwp * e["yield_kwh_per_kwp"][self.region] * e["orientation_factor"][self.pv_orientation]
                * e["shading_factor"][self.pv_shading])

    @staticmethod
    def self_consumption(gen: float, demand: float) -> float:
        if gen <= 0:
            return 0.0
        e = measure("solar_pv")["engineering"]
        lo, hi = assumption("solar.self_consumption_low_demand_kwh"), assumption("solar.self_consumption_high_demand_kwh")
        frac = e["self_consumption_min"] + (e["self_consumption_max"] - e["self_consumption_min"]) * min(
            max((demand - lo) / (hi - lo), 0.0), 1.0)
        return min(gen * frac, assumption("solar.self_consumption_max_share_of_demand") * demand)

    def electricity_demand(self) -> float:
        space = 0.0 if self.gas_heated else self.q_space / self.eff
        hw = 0.0 if self.gas_heated else self.q_hw / self.hw_efficiency()
        return self.other_elec + space + hw

    def purchased(self) -> dict[str, float]:
        demand = self.electricity_demand()
        gen = self.pv_generation()
        sc = self.self_consumption(gen, demand)
        gas = self.cooking_gas + ((self.q_space / self.eff + self.q_hw / self.eff) if self.gas_heated else 0.0)
        return {"electricity": max(demand - sc, 0.0), "gas": max(gas, 0.0), "electricity_demand": demand,
                "pv_generation": gen, "pv_self_consumed": sc}

    def flows(self) -> list[dict]:
        """Where purchased energy (plus self-consumed solar) goes, per end use, kWh/yr.

        Consistent accounting for the Sankey: grid flows sum to purchased electricity, gas
        flows to purchased gas; solar covers the same share of every electric end use.
        Exported solar is not a flow into the home and is not shown.
        """
        p = self.purchased()
        demand = p["electricity_demand"]
        solar_share = p["pv_self_consumed"] / demand if demand > 0 else 0.0
        elec_uses = {
            "Space heating": 0.0 if self.gas_heated else self.q_space / self.eff,
            "Hot water": 0.0 if self.gas_heated else self.q_hw / self.hw_efficiency(),
            "Appliances & lighting": self.other_elec,
        }
        gas_uses = {
            "Space heating": self.q_space / self.eff if self.gas_heated else 0.0,
            "Hot water": self.q_hw / self.eff if self.gas_heated else 0.0,
            "Cooking (gas)": self.cooking_gas,
        }
        out = []
        for use, kwh in elec_uses.items():
            if kwh > 0:
                out.append({"source": "Grid electricity", "target": use, "kwh": kwh * (1 - solar_share)})
                if solar_share > 0:
                    out.append({"source": "Solar (self-used)", "target": use, "kwh": kwh * solar_share})
        out += [{"source": "Gas", "target": use, "kwh": kwh} for use, kwh in gas_uses.items() if kwh > 0]
        return [{**f, "kwh": float(round(f["kwh"] / 10.0) * 10)} for f in out if f["kwh"] >= 5]


# ---------------------------------------------------------------------------------------------
# Baseline decomposition
# ---------------------------------------------------------------------------------------------

def physics_estimate(p_type: str, inp: dict[str, Resolved], heating_system: str, region: str,
                     hdd_normal: float, boiler_age: float | None) -> dict:
    """Physics-only annual purchased energy (used when meters can't provide a baseline)."""
    phys = physics.physical_state(p_type, inp)
    hlc = physics.heat_loss_coefficient(phys)
    q_space = hlc * hdd_normal * 24 / 1000 * assumption("energy.heat_utilisation")
    tfa = phys["floor_area_m2"]
    q_hw = standard_hot_water_heat(tfa)
    other = 207.8 * (tfa * sap_occupancy(tfa)) ** 0.4714 + 350  # SAP 2012 appliance formula + cooking
    st = EnergyState(phys=phys, region=region, heating_system=heating_system,
                     eff=_system_efficiency(heating_system, boiler_age, physics.hlc_per_m2(phys)),
                     q_space=q_space, q_hw=q_hw, cooking_gas=0.0, other_elec=other)
    out = st.purchased()
    heating_fuel = "gas" if st.gas_heated else "electricity"
    out["heating_kwh"] = q_space / st.eff
    out["heating_fuel"] = heating_fuel
    return out


def _system_efficiency(system: str, boiler_age: float | None, hlc_m2: float) -> float:
    if system.startswith("gas_boiler"):
        return boiler_efficiency(system, boiler_age)
    if system.endswith("heat_pump"):
        return heat_pump_scop(hlc_m2, ground_source=system == "ground_source_heat_pump")
    return 1.0


def decompose(
    p_type: str,
    inp: dict[str, Resolved],
    region: str,
    heating_system: str,
    boiler_age: float | None,
    baseline: dict[str, dict],
    pv_kwp: float,
    pv_orientation: str | None,
    pv_shading: str | None,
    controls: str,
) -> EnergyState:
    """Build an EnergyState that reproduces the baseline purchased energy per fuel.

    ``baseline[fuel]`` = {"annual": kWh, "heating": kWh or None} (heating = degree-day share).
    """
    phys = physics.physical_state(p_type, inp)
    hlc_m2 = physics.hlc_per_m2(phys)
    eff = _system_efficiency(heating_system, boiler_age, hlc_m2)
    st = EnergyState(phys=phys, region=region, heating_system=heating_system, eff=eff, q_space=0.0, q_hw=0.0,
                     cooking_gas=0.0, other_elec=0.0, pv_kwp=pv_kwp or 0.0,
                     pv_orientation=pv_orientation or "east_west", pv_shading=pv_shading or "low", controls=controls)

    imports = baseline["electricity"]["annual"]
    gas = baseline["gas"]["annual"]
    # Underlying electricity demand = imports + solar self-consumption (fixed point).
    gen = st.pv_generation()
    demand = imports
    for _ in range(6):
        demand = imports + st.self_consumption(gen, demand)

    if st.gas_heated:
        heat_fuel = baseline["gas"]["heating"] if baseline["gas"]["heating"] is not None else gas * assumption("energy.gas_heating_share_fallback")
        heat_fuel = min(heat_fuel, gas)
        base = gas - heat_fuel
        cooking = min(assumption("energy.cooking_gas_max_kwh"), assumption("energy.cooking_gas_share_of_baseload") * base)
        st.cooking_gas = cooking
        st.q_space = heat_fuel * eff
        st.q_hw = (base - cooking) * eff
        st.other_elec = demand
    else:
        heat_fuel = baseline["electricity"]["heating"]
        if heat_fuel is None:
            heat_fuel = demand * assumption("energy.electric_heating_share_fallback")
        heat_fuel = min(heat_fuel, demand)
        st.q_space = heat_fuel * eff
        base_elec = demand - heat_fuel
        q_hw = min(standard_hot_water_heat(phys["floor_area_m2"]), assumption("energy.hot_water_max_share_of_electric_baseload") * base_elec * st.hw_efficiency())
        st.q_hw = q_hw
        st.other_elec = max(base_elec - q_hw / st.hw_efficiency(), 0.0)
        st.cooking_gas = gas  # any gas in a non-gas-heated home is cooking (or a flagged conflict)
    return st


# ---------------------------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------------------------

def _fabric(st: EnergyState, change: dict, realisation: float) -> EnergyState:
    """Only ``realisation`` of the nominal heat-loss reduction is achieved. We track the realised
    (effective) HLC so that a second fabric measure is judged against what the first one really
    delivered; otherwise sequential fabric savings become super-additive whenever realisation < 1."""
    new = copy.deepcopy(st)
    before = physics.heat_loss_coefficient(st.phys)
    new.phys.update(change)
    after = physics.heat_loss_coefficient(new.phys)
    h_eff = st.hlc_eff if st.hlc_eff is not None else before
    h_new = max(h_eff - realisation * max(before - after, 0.0), 1e-6)
    new.q_space = st.q_space * h_new / h_eff
    new.hlc_eff = h_new
    return new


def apply_measure(st: EnergyState, measure_id: str, calibration: dict[str, float] | None = None,
                  property_type: str = "semi_detached") -> EnergyState:
    """Return a NEW state with ``measure_id`` installed (the input state is not modified)."""
    r = (calibration or {}).get(measure_id, 1.0)
    eng = measure(measure_id)["engineering"]
    if measure_id == "loft_insulation":
        new = _fabric(st, {"loft_mm": float(eng["target_loft_mm"]), "has_loft": True}, r)
    elif measure_id in ("cavity_wall_insulation", "solid_wall_insulation"):
        new = _fabric(st, {"wall_insulated": True}, r)
    elif measure_id == "glazing_upgrade":
        new = _fabric(st, {"glazing": "double_post_2002",
                           "ach_factor": st.phys["ach_factor"] * (1 - eng["infiltration_reduction"])}, r)
    elif measure_id == "smart_controls":
        new = copy.deepcopy(st)
        new.q_space = st.q_space * (1.0 - r * eng["heat_demand_reduction"])
        new.controls = "smart_thermostat"
    elif measure_id == "air_source_heat_pump":
        new = copy.deepcopy(st)
        new.heating_system = "air_source_heat_pump"
        new.eff = heat_pump_scop(physics.hlc_per_m2(st.phys)) * r  # fixed at installation
        if not st.gas_heated:
            new.cooking_gas = st.cooking_gas
    elif measure_id == "solar_pv":
        new = copy.deepcopy(st)
        new.pv_kwp = float(eng["size_kwp"].get(property_type, 3.0)) * r
    else:
        raise ValueError(f"unknown measure {measure_id}")
    new.installed = st.installed + [measure_id]
    return new


def fuel_delta(before: dict, after: dict) -> dict:
    """Savings per fuel (positive = saving, negative = increase) and net purchased saving."""
    e = before["electricity"] - after["electricity"]
    g = before["gas"] - after["gas"]
    return {"electricity_saving_kwh": e, "gas_saving_kwh": g, "net_saving_kwh": e + g}
