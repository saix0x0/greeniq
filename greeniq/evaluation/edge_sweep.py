"""End-to-end edge-case sweep: every home, every PS2 scenario test, as checkable invariants.

``uv run python -m greeniq edge-sweep`` → reports/EDGE_CASES.md + edge_cases.json.

For each of the 3,000 homes the full product path runs (analyse → Next Best Action →
gated explanations → what-ifs) and the invariants PS2 §12 cares about are checked. The
report counts how many homes fall in each edge category and how many violations were found
(the target is zero everywhere). Nothing here is tuned; it only observes.
"""

from __future__ import annotations

import json
import time
from collections import Counter

from ..context import load_context
from ..contract import MEASURES
from ..data import ROOT, load_dataset
from ..facts import Scenario
from ..lab import decision_lab
from ..pipeline import analyse_home
from ..trust.gate import check
from ..trust.narrator import explain_home, explain_package

REPORTS = ROOT / "reports"


def sweep(lab_every: int = 15) -> dict:
    t0 = time.time()
    ds, ctx = load_dataset(), load_context()
    cats: Counter = Counter()
    checks: Counter = Counter()
    fails: dict[str, list[str]] = {}

    def ok(name: str, cond: bool, pid: str, detail: str = "") -> None:
        checks[name] += 1
        if not cond:
            fails.setdefault(name, []).append(f"{pid} {detail}".strip())

    for i, pid in enumerate(ds.property_ids):
        p = ds.property(pid)
        f = analyse_home(p, ctx)
        planned = {r.measure_id for r in f.plan}

        # --- categories -------------------------------------------------------------------
        if f.baseline_basis == "estimated":
            cats["missing or insufficient meter data (baseline estimated)"] += 1
        if f.baseline_basis == "unavailable":
            cats["no usable baseline at all"] += 1
        if any(b.basis == "zero" for b in f.baseline.values()) and all(
                (b.annual_kwh or 0) == 0 for b in f.baseline.values()):
            cats["zero purchased energy"] += 1
        if f.conflicts:
            cats["conflicting records"] += 1
        if f.score.status == "partial":
            cats["score is a range (component missing)"] += 1
        if any(e.status == "infeasible" for e in f.excluded):
            cats["has an infeasible measure"] += 1
        if f.package and len(f.package.measures) > 1:
            cats["interacting package (2+ measures)"] += 1

        # --- invariants ---------------------------------------------------------------------
        ok("home explanation passes the gate", check(explain_home(f).text, f, "home").passed, pid)
        if f.package:
            ok("package explanation passes the gate", check(explain_package(f).text, f, "package").passed, pid)
            ip = f.package.improvement_potential
            e_total = sum(b.annual_kwh or 0 for b in f.baseline.values())
            if f.baseline_basis != "metered" or e_total == 0:
                ok("no improvement % without a metered, non-zero baseline", ip.status == "unavailable" and ip.pct is None, pid)
            if len(f.package.measures) > 1:
                pk = f.package
                ok("package = standalone sum + reported interaction",
                   abs(pk.impact.net_saving_kwh - (pk.sum_of_standalone_net_kwh + pk.interaction_kwh)) < 1, pid)
            ok("carbon recomputes from displayed per-fuel kWh",
               abs(f.package.impact.carbon.total_kg - (f.package.impact.carbon.electricity_kg + f.package.impact.carbon.gas_kg)) < 0.5, pid)
        n = f.next_best_action
        if n is not None:
            ok("NBA never picks an infeasible retrofit", n.action.kind != "retrofit" or n.action.ref in planned, pid, n.action.ref or "")
            ok("NBA gives exactly three reasons", len(n.reasons) == 3, pid)
        if f.intensity_kwh_m2.value is not None:
            ok("intensity never computed from zero use", f.intensity_kwh_m2.value > 0, pid)

        # what-if: ask for every measure → infeasible ones are refused with a reason, never modelled
        w = analyse_home(p, ctx, scenario=Scenario(name="everything", measures=list(MEASURES)))
        modelled = set(w.package.measures) if w.package else set()
        ok("what-if never models a measure the home can't have", modelled <= planned, pid, str(modelled - planned))
        ok("every refused what-if measure carries a reason",
           all(r.reason for r in (w.scenario.rejected if w.scenario else [])), pid)

        # heat pump on a gas-heated home: electricity must rise, gas must fall
        if "air_source_heat_pump" in planned and f.baseline["gas"].basis == "metered" and \
                (f.baseline["gas"].heating_kwh or 0) > 1000:
            h = analyse_home(p, ctx, scenario=Scenario(name="hp", measures=["air_source_heat_pump"]))
            im = h.package.impact
            cats["gas-heated home with a feasible heat pump"] += 1
            ok("heat pump raises electricity and cuts gas", im.electricity.saving_kwh < 0 < im.gas.saving_kwh, pid)

        if lab_every and i % lab_every == 0 and f.package:
            L = decision_lab(p, ctx, 10000.0, {"objective": "value_for_money"})
            ok("Decision Lab only offers feasible packages", all(set(o.measures) <= planned for o in L.packages), pid)
            cats["Decision Lab runs"] += 1

    out = {"homes": len(ds.property_ids), "categories": dict(cats), "checks": dict(checks),
           "violations": {k: len(v) for k, v in fails.items()}, "examples": {k: v[:5] for k, v in fails.items()},
           "seconds": round(time.time() - t0, 1)}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "edge_cases.json").write_text(json.dumps(out, indent=2))
    (REPORTS / "EDGE_CASES.md").write_text(_markdown(out))
    return out


def _markdown(o: dict) -> str:
    cats = "\n".join(f"| {k} | {v} |" for k, v in sorted(o["categories"].items(), key=lambda kv: -kv[1]))
    rows = "\n".join(f"| {k} | {v} | {o['violations'].get(k, 0)} |" for k, v in o["checks"].items())
    ex = "\n".join(f"- **{k}**: {', '.join(v)}" for k, v in o["examples"].items()) or "None."
    return f"""# End-to-end edge-case sweep (PS2 §12 scenario tests)

> Generated by `uv run python -m greeniq edge-sweep` over all {o['homes']} homes in {o['seconds']} s.
> Each check is an invariant the product must hold on every home; the target is **0 violations**.

## Edge cases present in the data

| Category | Homes |
|---|---|
{cats}

## Invariants

| Check | Times checked | Violations |
|---|---|---|
{rows}

## Violation examples

{ex}
"""
