"""Grounding gate: language may only restate ComputedFacts. Anything else is blocked.

Checks every explanation (template or language model) against the facts it claims to explain:

1. **Numbers** — every number in the text must match a value in the facts (tolerating display
   rounding and kg↔t / kWh↔MWh conversions), and its unit must match the kind of fact it came
   from (a "%" must be a percentage fact, "kWh" an energy fact, "£" a money fact, "t" carbon).
2. **Direction** — a clause saying electricity (or gas) falls must not describe a package in
   which it rises, and vice versa (the heat-pump trap).
3. **No causal or guaranteed value claims** — "will increase your home's value", "guaranteed".
4. **Scenario identity** — the text may only talk about measures that are in this scenario
   (or, for a whole-home explanation, the home's plan and exclusions).

A failed gate means the text never reaches the user: the template explanation is shown instead.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from ..facts import ComputedFacts

GATE_VERSION = "grounding-gate/1.3"

MEASURE_WORDS = {
    "air_source_heat_pump": r"heat[- ]pumps?",
    "solar_pv": r"solar|photovoltaic|\bpv\b|panels?",
    "loft_insulation": r"\bloft",
    "cavity_wall_insulation": r"cavity",
    "solid_wall_insulation": r"solid[- ]wall",
    "glazing_upgrade": r"glazing|windows?",
    "smart_controls": r"thermostat|smart controls|heating controls",
}
DOWN = r"\b(cut|cuts|cutting|reduce[sd]?|reducing|lower[s]?|lowering|fall[s]?|falling|drop[s]?|dropping|decrease[sd]?|save[sd]?|saving|goes down|go down|less)\b"
UP = r"\b(rise[s]?|rising|raise[sd]?|raising|increase[sd]?|increasing|goes up|go up|adds?|adding|more)\b"
CAUSAL = (r"\bguarantee[sd]?\b|\bwill (definitely |certainly )?(increase|raise|boost|add to) (your|the) "
          r"(home|property|house)('s)? (value|price)\b|\bwill be worth\b|\bproves?\b")
NUM = re.compile(r"(£\s?)?(-?\d[\d,]*(?:\.\d+)?)\s*(%|kwh|mwh|gwh|tco2e|t\b|tonnes?|kg|points?|/100|kwp|m²|m2)?",
                 re.IGNORECASE)


class Claim(BaseModel):
    text: str
    value: float
    unit: str
    status: Literal["grounded", "unsupported", "exempt"]
    matched: str | None = None


class Violation(BaseModel):
    kind: Literal["unsupported_number", "wrong_direction", "causal_claim", "scenario_mismatch"]
    detail: str


class GateResult(BaseModel):
    version: str = GATE_VERSION
    passed: bool
    claims: list[Claim]
    violations: list[Violation]
    grounded_ratio: float | None


def _kind(path: str) -> str:
    p = path.lower()
    if "pct" in p or "share" in p or "percent" in p:
        return "pct"
    if "kwh" in p or "net_saving" in p or "interaction" in p or "sum_of_standalone" in p:
        return "kwh"
    if "_kg" in p or p.endswith(".kg") or "tonnes" in p or "total_kg" in p or "emissions" in p:
        return "carbon"
    if "cost" in p or "value" in p or "gbp" in p or "price" in p:
        return "money"
    if "score" in p or "contribution" in p or "points" in p or "sap" in p:
        return "score"
    return "other"


def _walk(obj, path="", out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk(v, f"{path}.{k}" if path else k, out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, f"{path}[{i}]", out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.append((path, float(obj)))
    return out


def fact_pool(f: ComputedFacts) -> list[tuple[str, str, float]]:
    """(path, kind, value) for every number in the facts, plus its displayed conversions."""
    pool = []
    for path, v in _walk(f.model_dump(mode="json", exclude={"inputs"})):
        k = _kind(path)
        pool.append((path, k, abs(v)))
        if k in ("carbon", "kwh"):
            pool.append((path + "/1000", k, abs(v) / 1000))
        if k == "pct" and abs(v) <= 1:
            pool.append((path + "×100", k, abs(v) * 100))
        if path.startswith("confidence.value"):
            pool.append((path + "×100", "pct", abs(v) * 100))
    for txt in [r.name for r in f.plan] + [e.name for e in f.excluded]:  # numbers inside measure names ("270 mm")
        for n in re.findall(r"\d+(?:\.\d+)?", txt):
            pool.append(("measure_name", "other", float(n)))
    for c in f.score.components:  # weights are shown as percentages
        pool.append((f"score.components.{c.key}.weight×100", "pct", c.weight * 100))
    return pool


UNIT_KIND = {"%": "pct", "kwh": "kwh", "mwh": "kwh", "gwh": "kwh", "t": "carbon", "tonne": "carbon", "tonnes": "carbon",
             "tco2e": "carbon", "kg": "carbon", "£": "money", "points": "score", "point": "score", "/100": "score"}


CHANGE_PATH = re.compile(r"saving|net_|interaction|sum_of_standalone|delta|reduction|uplift|carbon\.|_pct|\.pct",
                         re.IGNORECASE)
LEVEL_PATH = re.compile(r"baseline_kwh|after_kwh|annual_kwh|heating_kwh|baseload_kwh|emissions", re.IGNORECASE)
CHANGE_CUE = re.compile(DOWN + "|" + UP + r"|\bby\b", re.IGNORECASE)


def _role(text: str, start: int) -> str | None:
    """'change' when the number is the size of a change ("cuts gas by X", "saves X"), else None."""
    clause = re.split(r"[.;()]|\bnet\b", text[:start])[-1][-60:]
    return "change" if CHANGE_CUE.search(clause) else None


def _match(x: float, decimals: int, kind: str | None, pool, role: str | None = None) -> str | None:
    tol_abs = 0.51 * 10 ** (-decimals)
    for path, k, a in pool:
        if kind and k != kind and not (kind == "score" and k == "other"):
            continue
        # a change claim may only match a change fact, never a baseline/after level that happens to be equal
        if role == "change" and k in ("kwh", "carbon") and (LEVEL_PATH.search(path) or not CHANGE_PATH.search(path)):
            continue
        # whole numbers ≥ 100 must match exactly (facts are already display-rounded); decimals to their precision
        rel = 0.0 if (decimals == 0 and x >= 100) else 0.001
        if abs(x - a) <= max(tol_abs, rel * a):
            return path
    return None


def check_numbers(text: str, f: ComputedFacts) -> tuple[list[Claim], list[Violation]]:
    pool = fact_pool(f)
    claims, viol = [], []
    for m in NUM.finditer(text):
        pound, raw, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        if re.fullmatch(r"20\d\d", raw) and not unit and not pound:  # years
            continue
        before = text[max(0, m.start() - 1):m.start()]
        if before.isalpha() or before == "-" and m.start() > 1 and text[m.start() - 2].isalpha():  # e.g. "CO2", "P00007"
            continue
        if m.start() > 0 and text[m.start() - 1].isalnum():
            continue
        x = abs(float(raw.replace(",", "")))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        kind = "money" if pound else UNIT_KIND.get(unit)
        if unit in ("kwp", "m²", "m2") or text[m.end():m.end() + 3].lower().strip().startswith("mm"):
            kind = "other"
        if kind is None and x <= 10 and decimals == 0:  # counts and ordinals ("3 measures", "step 2")
            claims.append(Claim(text=m.group(0).strip(), value=x, unit=unit, status="exempt"))
            continue
        role = _role(text, m.start()) if kind in ("kwh", "carbon") else None
        hit = _match(x, decimals, kind, pool, role) or (_match(x, decimals, None, pool) if kind in (None, "score") else None)
        status = "grounded" if hit else "unsupported"
        claims.append(Claim(text=m.group(0).strip(), value=x, unit=unit or ("£" if pound else ""), status=status, matched=hit))
        if not hit:
            viol.append(Violation(kind="unsupported_number", detail=f"'{m.group(0).strip()}' does not match any computed fact"))
    return claims, viol


def check_direction(text: str, f: ComputedFacts) -> list[Violation]:
    if f.package is None:
        return []
    sign = {"electricity": f.package.impact.electricity.saving_kwh or 0.0, "gas": f.package.impact.gas.saving_kwh or 0.0}
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\([^)]*\)", "", text)):  # asides like "(net +890 kWh)" aside
        for clause in re.split(r";|,\s|\band\b|\bwhile\b|\bbut\b|\bwhereas\b", sentence, flags=re.IGNORECASE):
            cl = clause.lower()
            fuels = [fu for fu, pat in (("electricity", r"electric"), ("gas", r"\bgas\b")) if re.search(pat, cl)]
            if len(fuels) != 1 or re.search(r"\b(net|baseline|today)\b", cl):
                continue
            fuel = fuels[0]
            down, up = re.search(DOWN, cl), re.search(UP, cl)
            if down and not up and re.search(r"(?:^|\s)[-−]\s?\d", cl):  # "a saving of −3,240 kWh" = an increase
                down, up = None, True
            if down and not up and sign[fuel] < 0:
                out.append(Violation(kind="wrong_direction", detail=f"says {fuel} falls, but it rises in this package: '{clause.strip()}'"))
            elif up and not down and sign[fuel] > 0:
                out.append(Violation(kind="wrong_direction", detail=f"says {fuel} rises, but it falls in this package: '{clause.strip()}'"))
    return out


def check_scenario(text: str, f: ComputedFacts, scope: Literal["home", "package"]) -> list[Violation]:
    if scope == "package" and f.package is not None:
        allowed = set(f.package.measures) | {r.measure_id for r in (f.scenario.rejected if f.scenario else [])}
    else:
        allowed = {r.measure_id for r in f.plan} | {e.measure_id for e in f.excluded}
    out = []
    low = text.lower()
    for mid, pat in MEASURE_WORDS.items():
        if mid not in allowed and re.search(pat, low):
            if mid == "solid_wall_insulation" and "cavity" in low and "solid" not in low:
                continue
            out.append(Violation(kind="scenario_mismatch", detail=f"mentions {mid.replace('_', ' ')}, which is not in this {scope}"))
    return out


NEGATION = re.compile(r"\b(not|no|never|nor|without|cannot|can't|won't|doesn't|does not|isn't|is not)\b[^.;]{0,30}$",
                      re.IGNORECASE)


def causal_claims(text: str) -> list[str]:
    """Value promises, ignoring negated disclaimers ("not a guarantee", "does not prove")."""
    out = []
    for m in re.finditer(CAUSAL, text, flags=re.IGNORECASE):
        before = text[max(0, m.start() - 40):m.start()]
        if not NEGATION.search(before):
            out.append(m.group(0))
    return out


def check(text: str, f: ComputedFacts, scope: Literal["home", "package"] = "package") -> GateResult:
    claims, viol = check_numbers(text, f)
    viol += check_direction(text, f)
    if causal_claims(text):
        viol.append(Violation(kind="causal_claim", detail="states a guaranteed or causal value effect"))
    viol += check_scenario(text, f, scope)
    scored = [c for c in claims if c.status != "exempt"]
    ratio = (sum(c.status == "grounded" for c in scored) / len(scored)) if scored else None
    return GateResult(passed=not viol, claims=claims, violations=viol, grounded_ratio=ratio)
