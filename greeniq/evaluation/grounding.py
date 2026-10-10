"""Groundedness evaluation (ER-4): does any language that reaches a user restate the facts?

Three measurements on held-out test homes:
1. Clean template explanations through the gate → false-block rate (should be 0).
2. Corrupted explanations (invented number, flipped fuel direction, causal value promise,
   off-scenario measure) → the gate's catch rate per corruption type.
3. Language-model explanations (only when credentials exist; never faked) → share of claims
   grounded, share of explanations passing (factually accurate), share of unsupported claims.
"""

from __future__ import annotations

import json
import re
import time

from ..context import load_context
from ..data import ROOT, load_dataset, load_splits
from ..pipeline import analyse_home
from ..trust.gate import MEASURE_WORDS, check
from ..trust.llm import generate, llm_status
from ..trust.narrator import explain_home, explain_package

REPORTS = ROOT / "reports"


def _invent_number(text: str) -> str | None:
    m = re.search(r"(\d[\d,]*) kWh", text)
    if not m:
        return None
    v = float(m.group(1).replace(",", "")) * 1.37 + 130
    return text[:m.start(1)] + f"{v:,.0f}" + text[m.end(1):]


def _flip(text: str) -> str | None:
    swaps = [(r"cuts gas", "raises gas"), (r"adds gas", "cuts gas"),
             (r"raises electricity", "cuts electricity"), (r"cuts electricity", "raises electricity")]
    for a, b in swaps:
        if re.search(a, text):
            return re.sub(a, b, text, count=1)
    return None


def _foreign(text: str, f) -> str | None:
    allowed = set(f.package.measures) | {r.measure_id for r in (f.scenario.rejected if f.scenario else [])}
    for mid, phrase in (("solar_pv", "solar panels"), ("air_source_heat_pump", "a heat pump"), ("loft_insulation", "loft insulation")):
        if mid not in allowed:
            return text + f" Adding {phrase} would help as well."
    return None


def evaluate_grounding(n_homes: int = 200, llm_homes: int = 0) -> dict:
    t0 = time.time()
    ds, ctx = load_dataset(), load_context()
    test = load_splits()
    ids = [p for p in test[test["split"] == "test"]["property_id"].tolist() if p in set(ds.property_ids)][:n_homes]
    clean = {"texts": 0, "blocked": 0, "claims": 0, "grounded": 0}
    corrupt = {k: {"tried": 0, "caught": 0} for k in ("invented_number", "flipped_direction", "causal_value_claim", "off_scenario_measure")}
    llm = {"run": False, "homes": 0, "explanations": 0, "passed": 0, "claims": 0, "grounded": 0, "unsupported": 0,
           "status": llm_status()[1], "failures": []}
    for i, pid in enumerate(ids):
        f = analyse_home(ds.property(pid), ctx)
        for scope, e in (("home", explain_home(f)), ("package", explain_package(f) if f.package else None)):
            if e is None:
                continue
            g = check(e.text, f, scope)
            clean["texts"] += 1
            clean["blocked"] += not g.passed
            scored = [c for c in g.claims if c.status != "exempt"]
            clean["claims"] += len(scored)
            clean["grounded"] += sum(c.status == "grounded" for c in scored)
        if f.package:
            base = explain_package(f).text
            variants = {"invented_number": _invent_number(base), "flipped_direction": _flip(base),
                        "causal_value_claim": base + " This will increase your home's value.",
                        "off_scenario_measure": _foreign(base, f)}
            for k, t in variants.items():
                if t is None:
                    continue
                corrupt[k]["tried"] += 1
                corrupt[k]["caught"] += not check(t, f, "package").passed
        if i < llm_homes and llm_status()[0]:
            llm["run"] = True
            llm["homes"] += 1
            for scope in ("home", "package") if f.package else ("home",):
                text, note = generate(f, scope)
                if not text:
                    llm["failures"].append(f"{pid}/{scope}: {note}")
                    continue
                g = check(text, f, scope)
                llm["explanations"] += 1
                llm["passed"] += g.passed
                scored = [c for c in g.claims if c.status != "exempt"]
                llm["claims"] += len(scored)
                llm["grounded"] += sum(c.status == "grounded" for c in scored)
                llm["unsupported"] += sum(c.status == "unsupported" for c in scored)
    out = {"homes": len(ids), "clean_templates": clean, "corruptions": corrupt, "llm": llm,
           "seconds": round(time.time() - t0, 1)}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "grounding.json").write_text(json.dumps(out, indent=2))
    (REPORTS / "GROUNDING.md").write_text(_markdown(out))
    return out


def _pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "—"


def _markdown(o: dict) -> str:
    c, L = o["clean_templates"], o["llm"]
    rows = "\n".join(f"| {k.replace('_', ' ')} | {v['tried']} | {v['caught']} | {_pct(v['caught'], v['tried'])} |"
                     for k, v in o["corruptions"].items())
    if L["run"]:
        llm_txt = (f"| Claims grounded (target ≥ 90%) | {_pct(L['grounded'], L['claims'])} |\n"
                   f"| Explanations passing the gate = factually accurate (target ≥ 90%) | {_pct(L['passed'], L['explanations'])} |\n"
                   f"| Unsupported claims (target < 5%) | {_pct(L['unsupported'], L['claims'])} |\n"
                   f"| Homes / explanations | {L['homes']} / {L['explanations']} |")
    else:
        llm_txt = f"| Not run | {L['status']}. No numbers are reported rather than invented. |"
    return f"""# Grounded language evaluation (ER-4)

> Generated by `uv run python -m greeniq eval-grounding` on {o['homes']} held-out test homes in {o['seconds']} s.
> The gate (`greeniq/trust/gate.py`) checks numbers (value **and** unit kind), per-fuel direction,
> causal/guaranteed value wording, and scenario identity. Text that fails is never shown; the
> template explanation is shown instead.

## 1. Clean template explanations (false blocks)

| Metric | Value |
|---|---|
| Explanations checked | {c['texts']} |
| Wrongly blocked | {c['blocked']} ({_pct(c['blocked'], c['texts'])}) |
| Numeric claims grounded | {c['grounded']} / {c['claims']} ({_pct(c['grounded'], c['claims'])}) |

## 2. Corrupted explanations (does the gate catch lies?)

| Corruption | Tried | Caught | Catch rate |
|---|---|---|---|
{rows}

## 3. Language-model explanations

| Metric | Value |
|---|---|
{llm_txt}

## Limitations
- The gate checks *what can be checked*: numbers, units, signs, scenario and value wording. A
  sentence can be number-correct and still misleading in tone; the prompt and the template
  fallback are the defence there.
- Number matching tolerates display rounding only; a model that rounds differently is blocked
  (by design: precision we did not compute is not shown).
"""
