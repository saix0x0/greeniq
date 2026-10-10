"""The orchestrator: ``analyse_home(property) -> ComputedFacts``.

Runs every engine in dependency order and assembles one immutable, receipted result:
resolve inputs → annualise meters → detect conflicts → baseline per fuel → rating →
intensity → Green Home Score → feasible plan → per-fuel impacts (standalone and in
sequence) → package → improvement potential → carbon → score and rating after → value.

The orchestrator does no scoring or physics of its own. Optional "advanced" providers
(the ML energy estimator, the value model, savings calibration) plug in through
``EngineContext``; without them the pipeline still produces a complete, labelled result.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field

from .config import score_mappings as SM
from .contract import CONTRACT_VERSION, FUELS, Property, Receipt, Resolved
from .data import AS_OF, Weather, annualise_property
from .engines import physics, rating
from .engines.carbon import CARBON_VERSION, carbon_reduction, emissions_kg
from .engines.catalogue import catalogue, emission_factors, measure, stage_label
from .engines.energy import ENERGY_VERSION, EnergyState, apply_measure, boiler_efficiency, decompose, physics_estimate
from .engines.nba import DEFAULT_OBJECTIVE, NBA_VERSION, select_next_best_action
from .engines.retrofit import RETROFIT_VERSION, Excluded, plan_candidates
from .facts import (
    BaselineEnergy, ComputedFacts, Confidence, FuelFigures, Impact, ImprovementPotential, PackageResult,
    Recommendation, Scenario, ScenarioInfo, ValueResult,
)
from .features.annualise import ANNUALISE_VERSION
from .features.quality import QUALITY_VERSION, completeness, detect_conflicts
from .features.resolve import DEFAULTS_VERSION, resolve_inputs
from .score import compute_score, sap_to_band

PIPELINE_VERSION = "greeniq-pipeline/1.0"
VALUE_CAVEAT = ("Indicative estimate based on historical market relationships between energy ratings and sale "
                "prices in our (synthetic) dataset, holding the home's other characteristics constant. It is not a "
                "valuation, not a guarantee, and not proof that retrofitting causes a price increase.")


@dataclass
class EngineContext:
    weather: Weather
    as_of: str = AS_OF
    calibration: dict[str, float] = field(default_factory=dict)
    calibration_name: str = "engineering (uncalibrated)"
    energy_estimator: object | None = None  # .name, .predict(p, inp) -> {fuel: kWh} | None
    value_model: object | None = None  # .name, .estimate(p, inp, sap_before, sap_after) -> ValueResult


# ------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------

def _r10(x: float) -> float:
    return float(round(x / 10.0) * 10)


def _impact(before: dict, after: dict, output: str) -> Impact:
    eb, ea = _r10(before["electricity"]), _r10(after["electricity"])
    gb, ga = _r10(before["gas"]), _r10(after["gas"])
    es, gs = eb - ea, gb - ga
    return Impact(
        electricity=FuelFigures(baseline_kwh=eb, after_kwh=ea, saving_kwh=es),
        gas=FuelFigures(baseline_kwh=gb, after_kwh=ga, saving_kwh=gs),
        net_saving_kwh=es + gs,
        carbon=carbon_reduction(es, gs, output=f"{output}.carbon"),
    )


def _cost(mid: str, phys: dict, ptype: str) -> tuple[int, int, str]:
    c = measure(mid)["cost"]
    env = physics.envelope(phys)
    size = measure("solar_pv")["engineering"]["size_kwp"].get(ptype, 3.0)
    qty = {"per m2 of loft": env["roof"], "per m2 of external wall": env["wall"], "per m2 of window": env["window"],
           "per kWp": size, "per home": 1.0}[c["basis"]]
    lo = max(c["low"] * qty, c.get("minimum", 0))
    hi = max(c["high"] * qty, c.get("minimum", 0) * 1.5)

    def r50(x):
        return int(round(x / 50.0) * 50)

    qty_txt = "" if c["basis"] == "per home" else f" × {qty:.1f}"
    return r50(lo), r50(hi), f"£{c['low']}-£{c['high']} {c['basis']}{qty_txt}"


_REVERT = {
    "loft_insulation": {"loft_mm": 100.0},
    "cavity_wall_insulation": {"wall_insulated": False},
    "solid_wall_insulation": {"wall_insulated": False},
    "glazing_upgrade": {"glazing": "double_pre_2002"},
}


def _approx_pre_state(st: EnergyState, measures: list[str], has_gas: bool) -> EnergyState:
    """Approximate the home before ``measures`` were installed (for stale-EPC adjustment)."""
    pre = copy.deepcopy(st)
    for m in measures:
        if m in _REVERT:
            pre.phys.update(_REVERT[m])
        elif m == "smart_controls":
            pre.controls = "programmer_thermostat"
        elif m == "solar_pv":
            pre.pv_kwp = 0.0
        elif m == "air_source_heat_pump":
            pre.heating_system = "gas_boiler_condensing" if has_gas else "electric_storage"
            pre.eff = boiler_efficiency("gas_boiler_condensing", 10) if has_gas else 1.0
    return pre


def _inputs_after(inp: dict[str, Resolved], measures: list[str], ptype: str) -> dict[str, Resolved]:
    out = dict(inp)

    def est(v, note):
        return Resolved(value=v, basis="estimated", note=note)

    for m in measures:
        if m == "loft_insulation":
            out["loft_insulation_mm"] = est(270, "after loft top-up")
        elif m in ("cavity_wall_insulation", "solid_wall_insulation"):
            out["wall_insulated"] = est(True, "after wall insulation")
        elif m == "glazing_upgrade":
            out["glazing"] = est("double_post_2002", "after glazing upgrade")
        elif m == "smart_controls":
            out["controls"] = est("smart_thermostat", "after smart controls")
        elif m == "air_source_heat_pump":
            out["heating_system"] = est("air_source_heat_pump", "after heat pump")
            out["boiler_age_years"] = Resolved(value=None, basis="not_applicable")
        elif m == "solar_pv":
            out["solar_pv_kwp"] = est(measure("solar_pv")["engineering"]["size_kwp"].get(ptype, 3.0), "after solar PV")
    return out


def _apply_memory_to_inputs(inp: dict[str, Resolved], completed: list[str]) -> dict[str, Resolved]:
    """Measures the customer says are done override older record values (marked observed)."""
    note = "customer reported this measure as completed"
    for m in completed:
        if m == "loft_insulation" and inp["has_loft"].value is not False:
            inp["loft_insulation_mm"] = Resolved(value=270, basis="observed", note=note)
        elif m in ("cavity_wall_insulation", "solid_wall_insulation"):
            inp["wall_insulated"] = Resolved(value=True, basis="observed", note=note)
        elif m == "glazing_upgrade":
            inp["glazing"] = Resolved(value="double_post_2002", basis="observed", note=note)
        elif m == "smart_controls":
            inp["controls"] = Resolved(value="smart_thermostat", basis="observed", note=note)
    return inp


# ------------------------------------------------------------------------------------------
# the pipeline
# ------------------------------------------------------------------------------------------

def analyse_home(p: Property, ctx: EngineContext, scenario: Scenario | None = None,
                 constraints: dict | None = None) -> ComputedFacts:
    constraints = constraints or {}
    warnings: list[str] = []
    providers = {"annualisation": "degree-day regression", "score": SM.MAPPING_VERSION,
                 "savings_calibration": ctx.calibration_name}

    # 1. inputs
    inp = resolve_inputs(p)
    inp = _apply_memory_to_inputs(inp, constraints.get("completed_measures", []))

    # 2. meters → annual per fuel
    annual = annualise_property(p, ctx.weather, ctx.as_of)

    # 3. conflicts (decide which heating system the meters support)
    conflicts, effective_heating = detect_conflicts(p, inp, annual)

    # 4. baseline per fuel
    baseline: dict[str, BaselineEnergy] = {}
    estimate = None
    for fuel in FUELS:
        a = annual[fuel]
        if a.status in ("metered_full", "metered_partial"):
            baseline[fuel] = BaselineEnergy(fuel=fuel, annual_kwh=a.annual_kwh, basis="metered", status=a.status,
                                            heating_kwh=a.heating_kwh, baseload_kwh=a.baseload_kwh,
                                            months_used=a.months_used, provider="degree-day annualisation",
                                            receipt=a.receipt)
        elif a.status in ("zero", "not_applicable"):
            baseline[fuel] = BaselineEnergy(fuel=fuel, annual_kwh=0.0, basis=a.status, status=a.status, heating_kwh=0.0,
                                            baseload_kwh=0.0, months_used=a.months_used, provider="meters",
                                            receipt=a.receipt)
        else:
            if estimate is None:
                estimate = _estimate_baseline(p, inp, effective_heating, ctx)
            if estimate is not None:
                kwh = estimate["values"][fuel]
                baseline[fuel] = BaselineEnergy(
                    fuel=fuel, annual_kwh=round(kwh, 1), basis="estimated", status=a.status,
                    heating_kwh=round(kwh * estimate["heating_share"][fuel], 1), months_used=a.months_used,
                    provider=estimate["provider"],
                    receipt=Receipt(output=f"energy.baseline.{fuel}", value=round(kwh, 1), unit="kWh/yr",
                                    inputs={"meter_status": a.status, "months_used": a.months_used},
                                    method=estimate["method"], method_version=estimate["version"],
                                    provider=estimate["provider"],
                                    notes=[f"meters insufficient ({a.status}); model estimate used and labelled"]))
                providers["baseline_estimator"] = estimate["provider"]
            else:
                baseline[fuel] = BaselineEnergy(fuel=fuel, annual_kwh=None, basis="unavailable", status=a.status,
                                                provider="none")
    bases = {b.basis for b in baseline.values()}
    baseline_basis = ("unavailable" if "unavailable" in bases else "estimated" if "estimated" in bases else "metered")
    e_base = None if baseline_basis == "unavailable" else sum(b.annual_kwh for b in baseline.values())
    if baseline_basis == "estimated":
        warnings.append("Some meter data is insufficient; the baseline uses a labelled model estimate.")

    # 5. decompose into an energy state (needs a heating system and a baseline)
    base_state: EnergyState | None = None
    if effective_heating and e_base is not None:
        base_state = decompose(
            p.property_type, inp, p.region, effective_heating, inp["boiler_age_years"].value,
            {f: {"annual": baseline[f].annual_kwh, "heating": baseline[f].heating_kwh} for f in FUELS},
            pv_kwp=inp["solar_pv_kwp"].value or 0.0, pv_orientation=p.roof_orientation, pv_shading=p.roof_shading,
            controls=inp["controls"].value)

    # 6. rating (recorded, band midpoint, stale-adjusted or estimated)
    sap = _resolve_sap(p, base_state, conflicts, warnings)

    # 7. intensity (purchased energy per m²)
    area = inp["floor_area_m2"]
    if not area.known:
        intensity = Resolved(basis="missing", note="floor area unknown")
    elif e_base is None:
        intensity = Resolved(basis="missing", note="annual energy unavailable")
    elif e_base == 0:
        intensity = Resolved(basis="missing", note="zero metered use (likely unoccupied); intensity not assessable")
    else:
        intensity = Resolved(value=round(e_base / area.value, 1),
                             basis="observed" if baseline_basis == "metered" else "estimated",
                             note="metered, weather-normalised" if baseline_basis == "metered" else "model-estimated baseline")

    # 7b. annual emissions of purchased energy (PS2 factors), labelled like the baseline
    if e_base is None:
        emissions = Resolved(basis="missing", note="annual energy unavailable")
    else:
        kg = emissions_kg(baseline["electricity"].annual_kwh, baseline["gas"].annual_kwh)
        emissions = Resolved(value=round(kg, 0), basis="observed" if baseline_basis == "metered" else "estimated",
                             note="baseline kWh per fuel × DESNZ 2025 factors (kg CO2e/yr)")

    # 8. score
    score = compute_score({**inp, "sap_score": sap, "intensity_kwh_m2": intensity})

    # 9. plan
    cands, excluded = plan_candidates(p, inp, effective_heating, constraints)
    heating_conflict = any(c.code in ("heating_system_vs_gas_use", "gas_boiler_without_gas_use") for c in conflicts)
    for c in cands:
        if heating_conflict and c.measure_id in ("air_source_heat_pump", "smart_controls"):
            c.uncertainty.insert(0, "The recorded heating system conflicts with the meters; confirm it before acting on this.")
        if e_base == 0:
            c.uncertainty.insert(0, "Metered use is zero (likely unoccupied), so savings cannot be estimated from this "
                                    "home's meters; feasibility is still shown.")
    if e_base == 0:
        warnings.append("Metered use is zero: energy savings and improvement potential cannot be estimated.")
    plan: list[Recommendation] = []
    package: PackageResult | None = None
    scenario_info: ScenarioInfo | None = None
    if base_state is not None and cands:
        cal = ctx.calibration
        base_p = base_state.purchased()
        standalone = {c.measure_id: apply_measure(base_state, c.measure_id, cal, p.property_type).purchased()
                      for c in cands}
        suit_rank = {"High": 0, "Medium": 1, "Low": 2}
        ordered = sorted(cands, key=lambda c: (c.stage, suit_rank[c.suitability],
                                               -(base_p["electricity"] + base_p["gas"]
                                                 - standalone[c.measure_id]["electricity"]
                                                 - standalone[c.measure_id]["gas"])))
        seq_states = [base_state]
        for c in ordered:
            seq_states.append(apply_measure(seq_states[-1], c.measure_id, cal, p.property_type))
        for i, c in enumerate(ordered):
            lo, hi, basis = _cost(c.measure_id, base_state.phys, p.property_type)
            sa = _impact(base_p, standalone[c.measure_id], f"plan.{c.measure_id}.standalone")
            ip = _impact(seq_states[i].purchased(), seq_states[i + 1].purchased(), f"plan.{c.measure_id}.in_package")
            plan.append(Recommendation(
                measure_id=c.measure_id, name=c.name, stage=c.stage, stage_label=stage_label(c.stage), order=i + 1,
                suitability=c.suitability, rationale=c.rationale, evidence=c.evidence, depends_on=c.depends_on,
                uncertainty=c.uncertainty, standalone=sa, in_package=ip, cost_low=lo, cost_high=hi, cost_basis=basis,
                grant_note=measure(c.measure_id).get("grant_note"),
                receipt=Receipt(output=f"plan.{c.measure_id}", value=sa.net_saving_kwh, unit="kWh/yr net purchased saving (standalone)",
                                inputs={"suitability": c.suitability, "order": i + 1},
                                method="Sequential end-use model anchored on the metered baseline",
                                method_version=f"{ENERGY_VERSION} · {RETROFIT_VERSION}",
                                provider=ctx.calibration_name,
                                sources=[measure(c.measure_id).get("cost_source", ""), "docs/METHODOLOGY.md §3"],
                                notes=["estimate, not a guarantee"] + ([measure(c.measure_id)["evidence_note"]]
                                                                       if measure(c.measure_id).get("evidence_note") else [])),
            ))

        # 10. package (the scenario, or the full recommended package)
        package, scenario_info = _package(p, inp, ctx, scenario, ordered, excluded, base_state, base_p, standalone,
                                          baseline_basis, e_base, sap, intensity)
    elif base_state is None:
        warnings.append("No retrofit impacts: the heating system or baseline energy is unknown.")

    # 11. value
    value = _value(p, inp, ctx, sap, package, providers)

    # 12. completeness + confidence
    questions = completeness(p, inp, annual)
    confidence = _confidence(baseline_basis, baseline, conflicts, score)

    versions = {
        "contract": CONTRACT_VERSION, "pipeline": PIPELINE_VERSION, "score_mappings": SM.MAPPING_VERSION,
        "defaults": DEFAULTS_VERSION, "annualisation": ANNUALISE_VERSION, "physics": physics.PHYSICS_VERSION,
        "energy": ENERGY_VERSION, "retrofit_rules": RETROFIT_VERSION, "rating": rating.RATING_VERSION,
        "carbon": CARBON_VERSION, "quality": QUALITY_VERSION, "catalogue": catalogue()["version"],
        "emission_factors": emission_factors()["version"], "nba": NBA_VERSION,
    }
    fid = hashlib.sha256(json.dumps({"p": p.model_dump(mode="json"), "s": scenario.model_dump() if scenario else None,
                                     "c": constraints, "v": versions, "cal": ctx.calibration},
                                    sort_keys=True, default=str).encode()).hexdigest()[:16]
    facts = ComputedFacts(
        facts_id=fid, property_id=p.property_id, as_of=ctx.as_of, versions=versions,
        property_summary=_summary(p, inp), inputs=inp, baseline=baseline, baseline_basis=baseline_basis,
        intensity_kwh_m2=intensity, baseline_emissions_kg=emissions, sap=sap, epc_band=sap_to_band(sap.value) if sap.known else None, score=score,
        conflicts=conflicts, questions=questions, confidence=confidence, plan=plan, excluded=excluded,
        package=package, value=value, scenario=scenario_info, providers_used=providers, warnings=warnings,
    )
    # 13. next best action: a selector over the finished facts (computes no new numbers)
    nba = select_next_best_action(facts, constraints.get("objective", DEFAULT_OBJECTIVE))
    return facts.model_copy(update={"next_best_action": nba})


def _estimate_baseline(p: Property, inp: dict, heating: str | None, ctx: EngineContext) -> dict | None:
    """Model estimate of annual kWh per fuel when meters are insufficient."""
    phys_est = None
    if heating:
        hdd = ctx.weather.normal_year(p.region)
        phys_est = physics_estimate(p.property_type, inp, heating, p.region, hdd, inp["boiler_age_years"].value)
    share = {"electricity": 0.0, "gas": 0.0}
    if phys_est:
        hf = phys_est["heating_fuel"]
        share[hf] = min(phys_est["heating_kwh"] / max(phys_est[hf], 1.0), 0.95)
    if ctx.energy_estimator is not None:
        try:
            pred = ctx.energy_estimator.predict(p, inp)
        except Exception:  # an advanced provider must never break the pipeline
            pred = None
        if pred is not None:
            if not phys_est:
                share = {"electricity": 0.3, "gas": 0.75}
            return {"values": pred, "heating_share": share, "provider": ctx.energy_estimator.name,
                    "method": "Gradient-boosted regression per fuel on property characteristics (trained on metered homes)",
                    "version": getattr(ctx.energy_estimator, "version", "ml")}
    if phys_est:
        return {"values": {"electricity": phys_est["electricity"], "gas": phys_est["gas"]}, "heating_share": share,
                "provider": "physics estimate", "method": "RdSAP-lite heat loss × normal-year degree days",
                "version": physics.PHYSICS_VERSION}
    return None


def _resolve_sap(p: Property, base_state: EnergyState | None, conflicts, warnings: list[str]) -> Resolved:
    stale = next((c for c in conflicts if c.code == "stale_epc"), None)
    if p.sap_score is not None:
        sap = Resolved(value=float(p.sap_score), basis="observed", note=f"EPC {p.epc_year}" if p.epc_year else "EPC")
    elif p.epc_band is not None:
        sap = Resolved(value=SM.EPC_BAND_MIDPOINT[p.epc_band], basis="observed", note=f"band {p.epc_band} only; midpoint used")
    elif base_state is not None:
        return Resolved(value=round(rating.model_sap(base_state), 1), basis="estimated",
                        note="no EPC; estimated from the home's characteristics")
    else:
        return Resolved(basis="missing", note="no EPC and not enough information to estimate one")
    if stale and base_state is not None:
        done = [r.measure_id for r in p.retrofits_completed if p.epc_year and r.month and int(r.month[:4]) >= p.epc_year]
        pre = _approx_pre_state(base_state, done, has_gas=p.has_gas_connection is not False)
        delta = rating.model_sap(base_state) - rating.model_sap(pre)
        adj = max(1.0, min(sap.value + delta, 120.0))
        warnings.append(f"EPC adjusted by {delta:+.1f} SAP points for work completed after it was lodged.")
        return Resolved(value=round(adj, 1), basis="estimated",
                        note=f"EPC {p.epc_year} ({sap.value:.0f}) adjusted {delta:+.1f} for later work")
    return sap


def _package(p, inp, ctx, scenario, ordered, excluded, base_state, base_p, standalone, baseline_basis, e_base, sap,
             intensity):
    feasible = {c.measure_id for c in ordered}
    rejected: list[Excluded] = []
    if scenario and scenario.measures is not None:
        requested = list(dict.fromkeys(scenario.measures))
        for m in requested:
            if m not in feasible:
                why = next((e for e in excluded if e.measure_id == m), None)
                rejected.append(why or Excluded(measure_id=m, name=m, status="infeasible", reason="Not feasible here."))
        chosen = [m for m in requested if m in feasible]
        if scenario.order == "recommended":
            rank = {c.measure_id: i for i, c in enumerate(ordered)}
            chosen.sort(key=lambda m: rank[m])
        order = scenario.order
    else:
        requested, chosen, order = None, [c.measure_id for c in ordered], "recommended"
    info = ScenarioInfo(name=scenario.name if scenario else "Recommended package", requested=requested,
                        modelled=chosen, rejected=rejected, order=order)
    if not chosen:
        return None, info

    st = base_state
    for m in chosen:
        st = apply_measure(st, m, ctx.calibration, p.property_type)
    after = st.purchased()
    impact = _impact(base_p, after, "package")
    sum_sa = sum(_r10(base_p["electricity"] + base_p["gas"]) - _r10(standalone[m]["electricity"]) - _r10(standalone[m]["gas"])
                 for m in chosen)
    e_after = impact.electricity.after_kwh + impact.gas.after_kwh

    if baseline_basis == "metered" and e_base and e_base > 0:
        e_b = impact.electricity.baseline_kwh + impact.gas.baseline_kwh
        pot = ImprovementPotential(status="available", pct=round(100 * (e_b - e_after) / e_b, 1), e_baseline_kwh=e_b,
                                   e_after_kwh=e_after)
    elif baseline_basis == "metered":
        pot = ImprovementPotential(status="unavailable", e_baseline_kwh=0.0,
                                   reason="Baseline purchased energy is zero (e.g. an unoccupied home), so a percentage "
                                          "reduction is undefined.")
    else:
        e_b = impact.electricity.baseline_kwh + impact.gas.baseline_kwh
        pot = ImprovementPotential(
            status="unavailable", e_baseline_kwh=None,
            reason="No metered baseline (too few meter readings), so improvement potential is not reported.",
            indicative_pct=round(100 * (e_b - e_after) / e_b, 1) if e_b > 0 else None)
    pot.receipt = Receipt(output="package.improvement_potential", value=pot.pct, unit="%",
                          inputs={"e_baseline_kwh": pot.e_baseline_kwh, "e_after_kwh": e_after,
                                  "baseline_basis": baseline_basis},
                          method="100 × (E_baseline − E_after) / E_baseline; E = grid electricity imported + gas",
                          method_version=PIPELINE_VERSION, sources=["Lloyds PS2 §04"])

    inp_after = _inputs_after(inp, chosen, p.property_type)
    sap_after = rating.sap_after(sap.value, base_state, st) if sap.known else None
    int_after = (Resolved(value=round(e_after / inp["floor_area_m2"].value, 1), basis="estimated", note="after package")
                 if intensity.known and inp["floor_area_m2"].known else intensity)
    score_after = compute_score({**inp_after, "sap_score": Resolved(value=sap_after, basis="estimated")
                                 if sap_after is not None else sap, "intensity_kwh_m2": int_after})
    costs = [_cost(m, base_state.phys, p.property_type) for m in chosen]
    pkg = PackageResult(
        measures=chosen, order=order, impact=impact, sum_of_standalone_net_kwh=sum_sa,
        interaction_kwh=impact.net_saving_kwh - sum_sa, improvement_potential=pot,
        score_after=score_after.score, band_after=score_after.band, score_range_after=score_after.score_range,
        sap_before=sap.value if sap.known else None, sap_after=round(sap_after, 1) if sap_after is not None else None,
        epc_band_before=sap_to_band(sap.value) if sap.known else None,
        epc_band_after=sap_to_band(sap_after) if sap_after is not None else None,
        cost_low=sum(c[0] for c in costs), cost_high=sum(c[1] for c in costs),
        components_after={c.key: c.contribution for c in score_after.components},
        receipt=Receipt(output="package", value=impact.net_saving_kwh, unit="kWh/yr net purchased saving",
                        inputs={"measures": chosen, "order": order},
                        method="Measures applied in sequence to one evolving state (not a sum of standalone savings)",
                        method_version=ENERGY_VERSION, provider=ctx.calibration_name,
                        notes=[f"sum of standalone savings {sum_sa:,.0f} kWh vs package {impact.net_saving_kwh:,.0f} kWh"]),
    )
    return pkg, info


def _value(p, inp, ctx, sap, package, providers) -> ValueResult:
    if ctx.value_model is None:
        return ValueResult(status="unavailable", caveat=VALUE_CAVEAT, reason="Value model not loaded.")
    sap_after = package.sap_after if package else None
    try:
        res = ctx.value_model.estimate(p, inp, sap.value if sap.known else None, sap_after)
        providers["value"] = ctx.value_model.name
        return res
    except Exception as e:  # never break the pipeline
        return ValueResult(status="unavailable", caveat=VALUE_CAVEAT, reason=f"Value model error: {type(e).__name__}")


def _confidence(baseline_basis, baseline, conflicts, score) -> Confidence:
    v, reasons = 0.9, []
    if baseline_basis == "estimated":
        v -= 0.2
        reasons.append("Baseline energy is a model estimate, not metered.")
    elif baseline_basis == "unavailable":
        v -= 0.35
        reasons.append("Baseline energy is unavailable.")
    if any(b.status == "metered_partial" for b in baseline.values()):
        v -= 0.05
        reasons.append("Some monthly readings are missing (handled by regression, not zero-filled).")
    for c in conflicts:
        v -= {"high": 0.2, "medium": 0.1, "low": 0.03}[c.severity]
        reasons.append(f"Data conflict: {c.message}")
    if score.estimated_components:
        v -= 0.04 * len(score.estimated_components)
        reasons.append(f"{len(score.estimated_components)} score component(s) use assumed or estimated inputs.")
    if score.status == "partial":
        v -= 0.15
        reasons.append("At least one score component could not be assessed.")
    v = max(0.15, min(v, 0.95))
    level = "high" if v >= 0.75 else ("medium" if v >= 0.5 else "low")
    return Confidence(level=level, value=round(v, 2), reasons=reasons or ["Complete, metered, consistent data."])


def _summary(p: Property, inp: dict[str, Resolved]) -> dict:
    return {
        "property_id": p.property_id, "customer_id": p.customer_id, "region": p.region,
        "property_type": p.property_type, "flat_position": p.flat_position,
        "age_band": inp["age_band"].value, "floor_area_m2": inp["floor_area_m2"].value,
        "heating_system_recorded": p.heating_system, "epc_band_recorded": p.epc_band, "sap_recorded": p.sap_score,
        "epc_year": p.epc_year, "solar_pv_kwp": inp["solar_pv_kwp"].value,
        "retrofits_completed": [r.model_dump() for r in p.retrofits_completed],
    }
