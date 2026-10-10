"""Build tests/fixtures/sample_properties.json: hand-designed edge-case homes.

Meter reads are generated from a known degree-day model (kWh = a·days + b·HDD) using the
dataset's own weather, with no noise, so tests can check that annualisation recovers
a and b. The ``expected`` block documents each home's deterministic expected behaviour.

    uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

from greeniq.data import baseline_window, days_in, load_dataset

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_properties.json"

HOMES = [
    {
        "property": dict(property_id="FX-POOR-SEMI", customer_id="FX-C1", region="north",
                         property_type="semi_detached", age_band="pre_1919", floor_area_m2=95, wall_type="solid",
                         wall_insulated=False, loft_insulation_mm=25, floor_insulated=False, glazing="single",
                         heating_system="gas_boiler_noncondensing", boiler_age_years=22, has_gas_connection=True,
                         controls="none", solar_pv_kwp=0, roof_orientation="south", roof_shading="low",
                         epc_band="F", sap_score=36, epc_year=2019, listed_or_conservation=False, outdoor_space=True),
        "meters": {"gas": (9.0, 8.5), "electricity": (7.5, 0.1)},
        "expected": {"why": "PS2-style poor home: solid walls, single glazing, old boiler",
                     "band_in": ["Poor", "Very poor"], "improvement_potential": "available",
                     "feasible": ["loft_insulation", "solid_wall_insulation", "glazing_upgrade",
                                  "air_source_heat_pump", "solar_pv", "smart_controls"],
                     "infeasible": ["cavity_wall_insulation"]},
    },
    {
        "property": dict(property_id="FX-HP-CANDIDATE", customer_id="FX-C2", region="midlands",
                         property_type="semi_detached", age_band="1965_1980", floor_area_m2=88, wall_type="cavity",
                         wall_insulated=False, loft_insulation_mm=100, floor_insulated=False,
                         glazing="double_pre_2002", heating_system="gas_boiler_condensing", boiler_age_years=9,
                         has_gas_connection=True, controls="programmer_thermostat", solar_pv_kwp=0,
                         roof_orientation="south", roof_shading="low", epc_band="D", sap_score=58, epc_year=2021,
                         listed_or_conservation=False, outdoor_space=True),
        "meters": {"gas": (6.0, 4.2), "electricity": (7.8, 0.05)},
        "expected": {"why": "Heat pump switch: gas falls, electricity rises (negative electricity saving)",
                     "heat_pump_raises_electricity": True,
                     "fabric_before_heat_pump": True,
                     "feasible": ["loft_insulation", "cavity_wall_insulation", "air_source_heat_pump", "solar_pv"]},
    },
    {
        "property": dict(property_id="FX-MID-FLAT", customer_id="FX-C3", region="london", property_type="flat",
                         flat_position="mid", age_band="1965_1980", floor_area_m2=55, wall_type="cavity",
                         wall_insulated=True, glazing="double_pre_2002", heating_system="electric_storage",
                         has_gas_connection=False, controls="programmer_thermostat", solar_pv_kwp=0,
                         epc_band="E", sap_score=47, epc_year=2018, listed_or_conservation=False,
                         outdoor_space=False),
        "meters": {"electricity": (9.0, 1.6)},
        "expected": {"why": "Mid-floor flat: loft, solar and heat pump are infeasible",
                     "infeasible": ["loft_insulation", "solar_pv", "air_source_heat_pump", "cavity_wall_insulation"],
                     "gas_status": "not_applicable"},
    },
    {
        "property": dict(property_id="FX-MISSING-DATA", customer_id="FX-C4", region="south_east",
                         property_type="terraced", floor_area_m2=82, heating_system="gas_boiler_condensing",
                         has_gas_connection=True),
        "meters": {"gas": (5.5, 4.0), "electricity": (7.0, 0.0)},
        "months": 3,
        "expected": {"why": "New customer: 3 months of reads, no EPC, unknown age and fabric",
                     "annualisation": "insufficient", "score_status_in": ["partial", "provisional"]},
    },
    {
        "property": dict(property_id="FX-LARGE-EFFICIENT", customer_id="FX-C5", region="south_west",
                         property_type="detached", age_band="post_2002", floor_area_m2=280, wall_type="cavity",
                         wall_insulated=True, loft_insulation_mm=300, floor_insulated=True, glazing="triple",
                         heating_system="air_source_heat_pump", has_gas_connection=False, controls="smart_zoned",
                         solar_pv_kwp=4.0, roof_orientation="south", roof_shading="low", epc_band="B",
                         sap_score=84, epc_year=2022, listed_or_conservation=False, outdoor_space=True),
        "meters": {"electricity": (14.0, 3.0)},
        "expected": {"why": "Large home with high total use but low intensity: must not be flagged poor",
                     "is_poor": False, "band_in": ["Good", "Highly efficient"]},
    },
    {
        "property": dict(property_id="FX-VOID-ZERO", customer_id="FX-C6", region="wales", property_type="semi_detached",
                         age_band="1945_1964", floor_area_m2=85, wall_type="cavity", wall_insulated=True,
                         loft_insulation_mm=150, glazing="double_pre_2002", heating_system="gas_boiler_condensing",
                         boiler_age_years=6, has_gas_connection=True, controls="programmer_thermostat",
                         solar_pv_kwp=0, epc_band="D", sap_score=62, epc_year=2020, outdoor_space=True),
        "meters": {"gas": (0.0, 0.0), "electricity": (0.0, 0.0)},
        "expected": {"why": "Void property: zero baseline, so improvement potential is unavailable",
                     "improvement_potential": "unavailable"},
    },
    {
        "property": dict(property_id="FX-CONFLICT", customer_id="FX-C7", region="scotland", property_type="detached",
                         age_band="1981_2002", floor_area_m2=130, wall_type="cavity", wall_insulated=True,
                         loft_insulation_mm=200, glazing="double_post_2002", heating_system="air_source_heat_pump",
                         has_gas_connection=True, controls="smart_thermostat", solar_pv_kwp=0, epc_band="C",
                         sap_score=72, epc_year=2023, outdoor_space=True),
        "meters": {"gas": (5.0, 4.0), "electricity": (8.0, 0.4)},
        "expected": {"why": "Records a heat pump, but meters show substantial gas heating: conflict",
                     "conflict": "heating_system_vs_gas_use"},
    },
]


def main() -> None:
    ds = load_dataset()
    window = baseline_window()
    days = days_in(window)
    out = []
    for home in HOMES:
        p = dict(home["property"])
        region = p["region"]
        hdd = ds.weather.hdd(region, window)
        months = window[-home.get("months", 12):]
        reads = []
        for fuel, (a, b) in home["meters"].items():
            for m in months:
                reads.append({"month": m, "fuel": fuel, "kwh": round(a * days[m] + b * hdd[m], 1)})
        p["meter_readings"] = reads
        out.append({"property": p, "true_model": {f: {"a": a, "b": b} for f, (a, b) in home["meters"].items()},
                    "expected": home["expected"]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {len(out)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
