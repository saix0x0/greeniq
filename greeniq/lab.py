"""Decision Lab: every feasible package, named plans, Pareto frontier, interactions, sensitivity.

Nothing here has its own physics. Every number comes from ``analyse_home`` run on a
scenario (one run per package, per input variant), so the Lab can never disagree with
the property view. With at most 7 measures there are at most 2^7 = 128 packages, so we
evaluate all of them; "best" is a true optimum over that set, not a heuristic.

Definitions (also in docs/METHODOLOGY.md §Decision Lab):

- **Feasible package** — any non-empty subset of the home's feasible measures, installed in
  the recommended order. It *respects prerequisites* when every measure's ``depends_on``
  that is still pending is also in the package (e.g. no heat pump without the fabric
  measures it is sized for). Named plans only use packages that respect prerequisites; the
  scatter shows the rest as hollow points so the cost of skipping the order is visible.
- **Pareto-efficient** — no other prerequisite-respecting package costs less (mid cost)
  AND saves at least as much carbon, with one strictly better.
- **Greenest** — most carbon saved (ties → cheaper).
- **Best value** — most carbon saved per £1k of mid cost (£1k cost floor, as in the Next
  Best Action), among packages that achieve ≥ 20% of the greenest package's saving.
- **Lowest cost** — the cheapest efficient package that achieves ≥ 20% of the greenest
  package's saving (cheap but not trivial).
- **My budget** — most carbon saved with the TOP of the cost range within the budget.
- **Interaction** of a pair — joint saving minus the two standalone savings, per output
  (net kWh, carbon kg, score points), from paired runs on the same baseline.
- **Sensitivity** — rerun with each assumed/missing input set to plausible alternatives,
  and with savings realisation ±20%. A decision is **fragile** when the Next Best Action
  or the recommended package changes. This is a what-to-verify analysis, not a
  statistical confidence interval.
"""

from __future__ import annotations

import copy
from itertools import combinations
from typing import Literal

from pydantic import BaseModel

from .contract import Property
from .facts import ComputedFacts, Scenario
from .pipeline import EngineContext, analyse_home

LAB_VERSION = "decision-lab/1.0"
MIN_SHARE = 0.20
COST_FLOOR = 1000.0
MAX_MEASURES = 7


class PackageOption(BaseModel):
    key: str
    measures: list[str]
    respects_prerequisites: bool
    missing_prerequisites: list[str]
    cost_low: int
    cost_high: int
    cost_mid: float
    electricity_saving_kwh: float
    gas_saving_kwh: float
    net_saving_kwh: float
    carbon_kg: float
    score_after: int | None
    band_after: str | None
    epc_band_after: str | None
    improvement_pct: float | None
    value_uplift_pct_range: tuple[float, float] | None = None
    pareto_carbon: bool = False
    facts_id: str


class NamedPlan(BaseModel):
    id: Literal["lowest_cost", "greenest", "best_value", "my_budget"]
    title: str
    definition: str
    package_key: str | None
    note: str | None = None


class PairInteraction(BaseModel):
    a: str
    b: str
    net_kwh: float
    carbon_kg: float
    score_points: float | None


class SensitivityVariant(BaseModel):
    label: str
    nba_ref: str | None
    nba_kind: str
    package_measures: list[str]
    carbon_kg: float | None
    score: int | None


class SensitivityRow(BaseModel):
    input: str
    label: str
    current: str
    basis: str
    variants: list[SensitivityVariant]
    carbon_low: float | None
    carbon_high: float | None
    nba_changes: bool
    package_changes: bool
    fragile: bool
    action: str


class LabResult(BaseModel):
    property_id: str
    version: str = LAB_VERSION
    base_facts_id: str
    budget: float
    n_feasible_measures: int
    packages: list[PackageOption]
    plans: list[NamedPlan]
    interactions: list[PairInteraction]
    sensitivity: list[SensitivityRow]
    base_nba_ref: str | None
    base_package: list[str]
    base_carbon_kg: float | None
    notes: list[str]


def _key(ms: list[str]) -> str:
    return "+".join(ms)


def _missing_prereqs(chosen: list[str], facts: ComputedFacts) -> list[str]:
    pending = {r.measure_id for r in facts.plan}
    deps = {r.measure_id: r.depends_on for r in facts.plan}
    return sorted({d for m in chosen for d in deps.get(m, []) if d in pending and d not in chosen})


def _option(f: ComputedFacts, base: ComputedFacts, chosen: list[str]) -> PackageOption:
    pk = f.package
    im = pk.impact
    v = f.value
    return PackageOption(
        key=_key(chosen), measures=chosen, respects_prerequisites=not _missing_prereqs(chosen, base),
        missing_prerequisites=_missing_prereqs(chosen, base), cost_low=pk.cost_low, cost_high=pk.cost_high,
        cost_mid=(pk.cost_low + pk.cost_high) / 2, electricity_saving_kwh=im.electricity.saving_kwh,
        gas_saving_kwh=im.gas.saving_kwh, net_saving_kwh=im.net_saving_kwh, carbon_kg=im.carbon.total_kg,
        score_after=pk.score_after, band_after=pk.band_after, epc_band_after=pk.epc_band_after,
        improvement_pct=pk.improvement_potential.pct if pk.improvement_potential.status == "available"
        else pk.improvement_potential.indicative_pct,
        value_uplift_pct_range=v.uplift_pct_range if v and v.status == "available" else None, facts_id=f.facts_id)


def enumerate_packages(p: Property, ctx: EngineContext, base: ComputedFacts, constraints: dict) -> list[PackageOption]:
    measures = [r.measure_id for r in base.plan][:MAX_MEASURES]
    out = []
    for k in range(1, len(measures) + 1):
        for combo in combinations(measures, k):
            f = analyse_home(p, ctx, Scenario(measures=list(combo), name="lab"), constraints)
            if f.package is not None:
                out.append(_option(f, base, f.package.measures))
    _mark_pareto(out)
    return out


def _mark_pareto(opts: list[PackageOption]) -> None:
    ok = [o for o in opts if o.respects_prerequisites]
    for o in ok:
        o.pareto_carbon = not any(
            q is not o and q.cost_mid <= o.cost_mid and q.carbon_kg >= o.carbon_kg
            and (q.cost_mid < o.cost_mid or q.carbon_kg > o.carbon_kg) for q in ok)


def named_plans(opts: list[PackageOption], budget: float) -> list[NamedPlan]:
    ok = [o for o in opts if o.respects_prerequisites and o.carbon_kg > 0]
    defs = {
        "lowest_cost": ("Lowest cost", f"Cheapest efficient package saving at least {MIN_SHARE:.0%} of the greenest plan's carbon."),
        "greenest": ("Greenest", "Most carbon saved per year, whatever it costs (ties go to the cheaper)."),
        "best_value": ("Best value", f"Most carbon saved per £1k of mid cost (£1k floor), among packages saving at least "
                                     f"{MIN_SHARE:.0%} of the greenest plan's carbon."),
        "my_budget": ("My budget", f"Most carbon saved where even the top of the cost range fits within £{budget:,.0f}."),
    }
    if not ok:
        return [NamedPlan(id=i, title=t, definition=d, package_key=None, note="No feasible package saves carbon here.")
                for i, (t, d) in defs.items()]
    green = max(ok, key=lambda o: (o.carbon_kg, -o.cost_mid))
    floor = MIN_SHARE * green.carbon_kg
    big = [o for o in ok if o.carbon_kg >= floor]
    cheap = min((o for o in big if o.pareto_carbon), key=lambda o: (o.cost_mid, -o.carbon_kg), default=None)
    value = max(big, key=lambda o: (o.carbon_kg / max(o.cost_mid, COST_FLOOR), -o.cost_mid))
    fits = [o for o in ok if o.cost_high <= budget]
    mine = max(fits, key=lambda o: (o.carbon_kg, -o.cost_mid), default=None)
    picks = {"lowest_cost": cheap, "greenest": green, "best_value": value, "my_budget": mine}
    return [NamedPlan(id=i, title=t, definition=d, package_key=picks[i].key if picks[i] else None,
                      note=None if picks[i] else f"Nothing feasible fits within £{budget:,.0f}.")
            for i, (t, d) in defs.items()]


def pair_interactions(opts: list[PackageOption], base: ComputedFacts) -> list[PairInteraction]:
    by = {o.key: o for o in opts}
    order = [r.measure_id for r in base.plan]
    s0 = base.score.score
    out = []
    for a, b in combinations(order, 2):
        oa, ob, oab = by.get(a), by.get(b), by.get(_key([a, b]))
        if not (oa and ob and oab):
            continue
        sp = None
        if s0 is not None and None not in (oa.score_after, ob.score_after, oab.score_after):
            sp = float((oab.score_after - s0) - (oa.score_after - s0) - (ob.score_after - s0))
        out.append(PairInteraction(a=a, b=b, net_kwh=round(oab.net_saving_kwh - oa.net_saving_kwh - ob.net_saving_kwh, 0),
                                   carbon_kg=round(oab.carbon_kg - oa.carbon_kg - ob.carbon_kg, 1), score_points=sp))
    return out


# --- sensitivity ---------------------------------------------------------------------------

_ALTERNATIVES = {
    "wall_insulated": ("Wall insulation", [True, False]),
    "wall_type": ("Wall construction", ["cavity", "solid"]),
    "loft_insulation_mm": ("Loft insulation depth", [50, 270]),
    "glazing": ("Glazing", ["single", "double_post_2002"]),
    "controls": ("Heating controls", ["none", "smart_thermostat"]),
    "outdoor_space": ("Outdoor space for a heat pump", [True, False]),
    "roof_orientation": ("Roof orientation", ["south", "north"]),
    "floor_insulated": ("Floor insulation", [True, False]),
}


def _variant(label: str, f: ComputedFacts) -> SensitivityVariant:
    n = f.next_best_action
    return SensitivityVariant(label=label, nba_ref=n.action.ref if n else None, nba_kind=n.action.kind if n else "none",
                              package_measures=f.package.measures if f.package else [],
                              carbon_kg=f.package.impact.carbon.total_kg if f.package else None, score=f.score.score)


def _row(key, label, current, basis, variants, base: ComputedFacts, action_if_fragile) -> SensitivityRow:
    base_ref = base.next_best_action.action.ref if base.next_best_action else None
    base_pkg = base.package.measures if base.package else []
    carbons = [v.carbon_kg for v in variants if v.carbon_kg is not None]
    nba_changes = any(v.nba_ref != base_ref for v in variants)
    pkg_changes = any(v.package_measures != base_pkg for v in variants)
    fragile = nba_changes or pkg_changes
    return SensitivityRow(input=key, label=label, current=current, basis=basis, variants=variants,
                          carbon_low=min(carbons) if carbons else None, carbon_high=max(carbons) if carbons else None,
                          nba_changes=nba_changes, package_changes=pkg_changes, fragile=fragile,
                          action=action_if_fragile if fragile else "Robust: the decision holds either way.")


def sensitivity(p: Property, ctx: EngineContext, base: ComputedFacts, constraints: dict) -> list[SensitivityRow]:
    rows = []
    for key, (label, alts) in _ALTERNATIVES.items():
        r = base.inputs.get(key)
        recorded = getattr(p, key, None)
        if key == "roof_orientation":
            if p.property_type == "flat" or recorded is not None:
                continue
            basis = "missing"
        elif r is None or r.basis not in ("assumed", "missing"):
            continue
        else:
            basis = r.basis
        variants = []
        for alt in alts:
            try:
                q = p.model_copy(update={key: alt})
                Property.model_validate(q.model_dump())
            except Exception:
                continue
            variants.append(_variant(f"if {str(alt).replace('_', ' ').lower()}", analyse_home(q, ctx, None, constraints)))
        if variants:
            cur = "unknown" if (r is None or r.value is None) else str(r.value).replace("_", " ")
            rows.append(_row(key, label, cur, basis, variants, base,
                             f"Verify before acting: a survey or one customer answer settles it."))
    # engine assumption: how much of the engineering saving homes actually realise
    variants = []
    for lab, mult in (("realisation −20%", 0.8), ("realisation +20%", 1.2)):
        c2 = copy.copy(ctx)
        c2.calibration = {m: ctx.calibration.get(m, 1.0) * mult for m in
                          ("loft_insulation", "cavity_wall_insulation", "solid_wall_insulation", "glazing_upgrade",
                           "smart_controls", "air_source_heat_pump", "solar_pv")}
        variants.append(_variant(lab, analyse_home(p, c2, None, constraints)))
    rows.append(_row("savings_realisation", "Savings realised in practice (performance gap)", "calibrated" if ctx.calibration
                     else "engineering", "estimated", variants, base,
                     "The ranking depends on real-world performance; treat the savings as a range."))
    rows.sort(key=lambda r: (not r.fragile, -((r.carbon_high or 0) - (r.carbon_low or 0))))
    return rows


def decision_lab(p: Property, ctx: EngineContext, budget: float = 10000.0, constraints: dict | None = None) -> LabResult:
    constraints = constraints or {}
    base = analyse_home(p, ctx, None, constraints)
    opts = enumerate_packages(p, ctx, base, constraints) if base.plan else []
    notes = []
    if len(base.plan) > MAX_MEASURES:
        notes.append(f"Only the first {MAX_MEASURES} measures were combined.")
    if base.baseline_basis != "metered":
        notes.append("The baseline is not metered, so every saving here is model-estimated.")
    return LabResult(
        property_id=p.property_id, base_facts_id=base.facts_id, budget=budget, n_feasible_measures=len(base.plan),
        packages=sorted(opts, key=lambda o: o.cost_mid), plans=named_plans(opts, budget),
        interactions=pair_interactions(opts, base), sensitivity=sensitivity(p, ctx, base, constraints),
        base_nba_ref=base.next_best_action.action.ref if base.next_best_action else None,
        base_package=base.package.measures if base.package else [],
        base_carbon_kg=base.package.impact.carbon.total_kg if base.package else None, notes=notes)
