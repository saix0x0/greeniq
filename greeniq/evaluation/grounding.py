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


def evaluate_grounding(n_homes: int = 200, llm_homes: int = 0, split: str = "test",
                       styles: tuple[str, ...] = ("hybrid", "full")) -> dict:
    """Tune on split="validation"; report split="test" once (PS2 §11). Writes GROUNDING.md for the test split and
    GROUNDING_VALIDATION.md for validation, so the two are never mixed."""
    t0 = time.time()
    ds, ctx = load_dataset(), load_context()
    test = load_splits()
    ids = [p for p in test[test["split"] == split]["property_id"].tolist() if p in set(ds.property_ids)][:n_homes]
    clean = {"texts": 0, "blocked": 0, "claims": 0, "grounded": 0}
    corrupt = {k: {"tried": 0, "caught": 0} for k in ("invented_number", "flipped_direction", "causal_value_claim", "off_scenario_measure")}
    def _blank():
        return {"run": False, "homes": 0, "explanations": 0, "passed": 0, "claims": 0, "grounded": 0, "unsupported": 0,
                "status": llm_status()[1], "failures": [], "violations": {}}
    by_style = {st: _blank() for st in styles}
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
            for st, llm in by_style.items():
                llm["run"] = True
                llm["homes"] += 1
                for scope in ("home", "package") if f.package else ("home",):
                    text, note = generate(f, scope, st)
                    if not text:
                        llm["failures"].append(f"{pid}/{scope}: {note}")
                        continue
                    if st == "hybrid":
                        tmpl = (explain_home(f) if scope == "home" else explain_package(f)).text
                        digits = bool(re.search(r"\d", re.sub(r"CO2e?|CO₂e?", "", text)))  # same rule as the narrator
                        g = check(f"{text} {tmpl}", f, scope)
                        ok = g.passed and not digits
                        if digits:
                            llm["violations"]["model_wrote_a_number"] = llm["violations"].get("model_wrote_a_number", 0) + 1
                    else:
                        g = check(text, f, scope)
                        ok = g.passed
                    for v in g.violations:
                        llm["violations"][v.kind] = llm["violations"].get(v.kind, 0) + 1
                    llm["explanations"] += 1
                    llm["passed"] += ok
                    scored = [c for c in g.claims if c.status != "exempt"]
                    llm["claims"] += len(scored)
                    llm["grounded"] += sum(c.status == "grounded" for c in scored)
                    llm["unsupported"] += sum(c.status == "unsupported" for c in scored)
    out = {"homes": len(ids), "split": split, "clean_templates": clean, "corruptions": corrupt,
           "llm": by_style.get("hybrid", next(iter(by_style.values()))), "llm_by_style": by_style,
           "seconds": round(time.time() - t0, 1)}
    REPORTS.mkdir(exist_ok=True)
    stem = "grounding" if split == "test" else f"grounding_{split}"
    (REPORTS / f"{stem}.json").write_text(json.dumps(out, indent=2))
    (REPORTS / f"{stem.upper()}.md").write_text(_markdown(out))
    return out


def _pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "—"


def _markdown(o: dict) -> str:
    c = o["clean_templates"]
    rows = "\n".join(f"| {k.replace('_', ' ')} | {v['tried']} | {v['caught']} | {_pct(v['caught'], v['tried'])} |"
                     for k, v in o["corruptions"].items())
    S = o.get("llm_by_style", {"full": o["llm"]})
    if any(L["run"] for L in S.values()):
        lines = ["| Metric | " + " | ".join(f"{k} style" for k in S) + " | Target |", "|---|" + "---|" * len(S) + "---|"]
        lines.append("| Explanations passing the gate (= factually accurate) | " + " | ".join(
            f"{_pct(L['passed'], L['explanations'])} ({L['passed']}/{L['explanations']})" for L in S.values()) + " | ≥ 90% |")
        lines.append("| Numeric claims grounded | " + " | ".join(_pct(L["grounded"], L["claims"]) for L in S.values()) + " | ≥ 90% |")
        lines.append("| Unsupported claims | " + " | ".join(_pct(L["unsupported"], L["claims"]) for L in S.values()) + " | < 5% |")
        lines.append("| Why blocked | " + " | ".join(", ".join(f"{k} {v}" for k, v in L["violations"].items()) or "—" for L in S.values()) + " | |")
        lines.append("| Model | " + " | ".join(L["status"] for L in S.values()) + " | |")
        llm_txt = "\n".join(lines) + f"""

**Styles.** *full*: the model writes the whole explanation, figures included. *hybrid* (default): the model writes
only the plain-English meaning with **no numbers**, and the engine's template sentences supply every figure (the
brief's "models calculate, the LLM explains", applied literally). In hybrid style the numeric claims are the
engine's own, so the meaningful measure is the pass rate (direction, scenario and value wording, no digits).
What users see is always gated: a failed explanation is replaced by the template."""
    else:
        llm_txt = f"| Not run | {o['llm']['status']}. No numbers are reported rather than invented. |\n|---|---|"
    return f"""# Grounded language evaluation (ER-4)

> Generated by `uv run python -m greeniq eval-grounding` on {o['homes']} held-out {o.get('split', 'test')}-split homes in {o['seconds']} s.
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

## 3. Language-model explanations (a real model, when one is configured)

{llm_txt}

## Limitations
- The gate checks *what can be checked*: numbers, units, signs, scenario and value wording. A
  sentence can be number-correct and still misleading in tone; the prompt and the template
  fallback are the defence there.
- Number matching tolerates display rounding only; a model that rounds differently is blocked
  (by design: precision we did not compute is not shown).
"""
