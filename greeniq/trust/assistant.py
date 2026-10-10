"""What-if assistant: question → scenario (deterministic parse) → engine rerun → gated explanation.

The parser maps words to measure IDs and intents; it never computes anything. The engine
reruns ``analyse_home`` on the interpreted scenario, and the explanation goes through the
grounding gate like every other explanation.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ..facts import ComputedFacts
from .gate import MEASURE_WORDS


class Interpretation(BaseModel):
    understood: bool
    measures: list[str] | None = None  # None = recommended package
    declined: list[str] = []
    completed: list[str] = []
    message: str


def _find(text: str) -> list[str]:
    return [m for m, pat in MEASURE_WORDS.items() if re.search(pat, text)]


def interpret(question: str, base: ComputedFacts) -> Interpretation:
    q = question.lower().strip()
    if not q:
        return Interpretation(understood=False, message="Ask a what-if, e.g. “What if I add solar panels?”")
    feasible = [r.measure_id for r in base.plan]
    declined, completed = [], []
    for m in re.finditer(r"(?:without|no|skip|don'?t want|not|instead of)\s+(?:a |the |any )?([a-z \-]+)", q):
        declined += _find(m.group(1))
    for m in re.finditer(r"(?:already (?:have|has|had|did|done|got|installed)|have already (?:done|installed|got))\s+(?:a |the )?([a-z \-]+)", q):
        completed += _find(m.group(1))
    mentioned = [m for m in _find(q) if m not in declined and m not in completed]
    if re.search(r"\b(everything|all of it|whole (package|plan)|full (package|plan)|recommended)\b", q):
        measures = None
    elif mentioned:
        only = re.search(r"\bonly\b|\bjust\b", q)
        measures = mentioned if only or not re.search(r"\b(also|as well|plus|on top)\b", q) else \
            list(dict.fromkeys(feasible + mentioned))
    elif declined or completed:
        measures = None
    else:
        names = ", ".join(r.name.lower() for r in base.plan) or "none here"
        return Interpretation(understood=False, message=f"I can answer what-ifs about these measures: {names}. "
                                                        "Try “What if I only add a heat pump?”")
    parts = []
    if measures is None:
        parts.append("the recommended package")
    else:
        parts.append("modelling " + ", ".join(m.replace("_", " ") for m in measures))
    if declined:
        parts.append("without " + ", ".join(m.replace("_", " ") for m in declined))
    if completed:
        parts.append("treating " + ", ".join(m.replace("_", " ") for m in completed) + " as already done")
    return Interpretation(understood=True, measures=measures, declined=declined, completed=completed,
                          message="Understood: " + "; ".join(parts) + ".")
