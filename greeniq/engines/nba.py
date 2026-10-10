"""Next Best Action: pick ONE thing to do next, from facts the engines already computed.

This module is a selector, not an engine. It reads a finished ``ComputedFacts`` and never
computes a new energy, carbon or cost number; every reason it gives points (``fact_ref``)
at the fact it is built from, so the UI can link to it and the grounding gate can check it.

Selection rule (documented in docs/METHODOLOGY.md §NBA):

(a) Blocked: if a fact we are missing would change the plan itself, the next action is to
    get that fact, not to install anything:
      - a high-severity data conflict (e.g. records say heat pump, meters show gas heating)
        → refer for survey;
      - the heating system is unknown → ask the customer;
      - no usable baseline at all (no meters, no estimate) → ask for meter readings;
      - nothing feasible, but some measures need a survey to decide → refer for survey.
(b) Otherwise: among feasible measures whose prerequisites are NOT still pending in the plan
    (so never a heat pump while a fabric measure it depends on is outstanding), rank by
    benefit toward the objective × suitability weight, and pick the top one.
(c) If nothing clears a minimum benefit (or metered use is zero), no action.
"""

from __future__ import annotations

from ..facts import ComputedFacts, NBAAction, NBAAlternative, NBAReason, NextBestAction, Recommendation

NBA_VERSION = "nba/1.0"

# Objective → (benefit of one recommendation, unit). Benefits read the STANDALONE impact,
# which is exactly what doing this one measure next would achieve on today's home.
# "value_for_money" divides by the mid cost with a £1,000 floor: below about £1k the price
# is not what decides, so very cheap jobs compete on carbon rather than winning on a tiny
# denominator (without the floor a £250 thermostat outranks every fabric measure).
COST_FLOOR_GBP = 1000.0
OBJECTIVES = {
    "value_for_money": ("kg CO2e/yr per £1k (mid cost, £1k floor)",
                        lambda r: r.standalone.carbon.total_kg / max((r.cost_low + r.cost_high) / 2, COST_FLOOR_GBP) * 1000),
    "carbon": ("kg CO2e/yr", lambda r: r.standalone.carbon.total_kg),
    "energy": ("kWh/yr net purchased", lambda r: r.standalone.net_saving_kwh),
}
DEFAULT_OBJECTIVE = "value_for_money"
SUITABILITY_WEIGHT = {"High": 1.0, "Medium": 0.7, "Low": 0.4}
MIN_CARBON_KG = 25.0  # below ~25 kg CO2e/yr a measure is not worth leading with
_LEVEL = {"high": 2, "medium": 1, "low": 0}


def _fmt_kwh(x: float) -> str:
    return f"{abs(x):,.0f}"


def _impact_text(r: Recommendation) -> str:
    parts = []
    for fuel in ("gas", "electricity"):
        s = getattr(r.standalone, fuel).saving_kwh or 0.0
        if s > 0:
            parts.append(f"saves {_fmt_kwh(s)} kWh of {fuel}")
        elif s < 0:
            parts.append(f"adds {_fmt_kwh(s)} kWh of {fuel}")
    t = r.standalone.carbon.total_tonnes
    effect = " and ".join(parts) or "changes purchased energy very little"
    return f"{r.name} {effect} a year, {'cutting' if t >= 0 else 'adding'} about {abs(t):.2f} t CO2e (estimate)."


def _retrofit_reasons(f: ComputedFacts, i: int, objective: str) -> list[NBAReason]:
    r = f.plan[i]
    out = [NBAReason(code="impact", text=_impact_text(r), fact_ref=f"plan[{i}].standalone")]
    optional: list[NBAReason] = []
    dependants = [(j, d) for j, d in enumerate(f.plan) if r.measure_id in d.depends_on]
    if dependants:
        j, d = dependants[0]
        names = ", ".join(x.name.lower() for _, x in dependants)
        optional.append(NBAReason(
            code="unlocks", fact_ref=f"plan[{j}].depends_on",
            text=f"Do it before {names}: those are sized and sequenced for the improved home."))
    for k, iss in enumerate(f.score.issues):
        if r.measure_id in iss.improved_by and iss.component not in ("energy_efficiency", "consumption_intensity"):
            optional.append(NBAReason(
                code="score_gap", fact_ref=f"score.issues[{k}]",
                text=f"{iss.label} is where the score loses {iss.points_available:.1f} points; this measure addresses it."))
            break
    if objective == "value_for_money":
        optional.append(NBAReason(
            code="cost", fact_ref=f"plan[{i}].cost_low",
            text=f"Low cost for the carbon it saves: indicative £{r.cost_low:,}-£{r.cost_high:,}."))
    if r.evidence:
        optional.append(NBAReason(code="evidence", fact_ref=f"plan[{i}].evidence[0]",
                                  text=f"Based on this home's record: {r.evidence[0]}."))
    optional.append(NBAReason(code="suitability", fact_ref=f"plan[{i}].suitability",
                              text=f"{r.suitability} suitability: {r.rationale}"))
    optional.append(NBAReason(code="cost", fact_ref=f"plan[{i}].cost_low",
                              text=f"Indicative cost £{r.cost_low:,}-£{r.cost_high:,}."))
    seen = set()
    for reason in optional:
        if len(out) == 3:
            break
        if reason.code not in seen:
            out.append(reason)
            seen.add(reason.code)
    return out


def _confidence_reason(f: ComputedFacts) -> NBAReason:
    return NBAReason(code="confidence", fact_ref="confidence",
                     text=f"Confidence is {f.confidence.level}: {f.confidence.reasons[0]}")


def _pad(reasons: list[NBAReason], f: ComputedFacts) -> list[NBAReason]:
    """Always exactly three reasons, each tied to a fact."""
    fill = [_confidence_reason(f),
            NBAReason(code="score", fact_ref="score.band",
                      text=(f"The Green Home Score is {f.score.score}/100 ({f.score.band})." if f.score.score is not None
                            else f"The Green Home Score can only be given as a range ({f.score.score_range})."))]
    for r in fill:
        if len(reasons) >= 3:
            break
        if r.code not in {x.code for x in reasons}:
            reasons.append(r)
    return reasons[:3]


def _blocked(f: ComputedFacts) -> NextBestAction | None:
    survey_needed = [(k, e) for k, e in enumerate(f.excluded) if e.status == "needs_survey"]
    affects = (NBAReason(code="affects", fact_ref=f"excluded[{survey_needed[0][0]}]",
                         text=f"Until then we cannot assess: {', '.join(e.name.lower() for _, e in survey_needed)}.")
               if survey_needed else None)

    def make(kind, ref, label, headline, reasons, blocked_by):
        return NextBestAction(
            action=NBAAction(kind=kind, ref=ref, label=label), disposition="refer_for_survey", headline=headline,
            reasons=_pad([r for r in reasons if r is not None], f), objective="unblock", confidence=f.confidence.level,
            alternatives=_alternatives(f, DEFAULT_OBJECTIVE, exclude=None, why="provisional until the blocker is resolved"),
            blocked_by=blocked_by, method_version=NBA_VERSION)

    for k, c in enumerate(f.conflicts):
        if c.severity == "high":
            return make("survey", c.code, "Confirm the heating system",
                        "Confirm the heating system before acting: the records and the meters disagree.",
                        [NBAReason(code="conflict", fact_ref=f"conflicts[{k}]", text=c.message),
                         NBAReason(code="resolution", fact_ref=f"conflicts[{k}].resolution", text=c.resolution),
                         affects or _confidence_reason(f)], c.resolution)
    for k, q in enumerate(f.questions):
        if q.field == "heating_system" and q.importance == "high":
            return make("answer_question", q.field, "Tell us how the home is heated",
                        "Tell us how the home is heated: it decides which upgrades make sense.",
                        [NBAReason(code="question", fact_ref=f"questions[{k}]", text=q.why), affects,
                         _confidence_reason(f)], q.question)
        if q.field == "meters" and f.baseline_basis == "unavailable":
            return make("answer_question", q.field, "Share meter readings",
                        "Share a few months of meter readings so savings can be estimated.",
                        [NBAReason(code="question", fact_ref=f"questions[{k}]", text=q.why),
                         NBAReason(code="baseline", fact_ref="baseline_basis",
                                   text="There is no usable energy baseline, so no saving can be estimated yet."),
                         _confidence_reason(f)], q.question)
    if not f.plan and survey_needed:
        k, e = survey_needed[0]
        return make("survey", e.measure_id, f"Survey: {e.name.lower()}",
                    f"Arrange a survey: {e.reason[0].lower() + e.reason[1:]}",
                    [NBAReason(code="needs_survey", fact_ref=f"excluded[{k}].reason", text=e.reason), affects,
                     _confidence_reason(f)], e.reason)
    return None


def _eligible(f: ComputedFacts) -> list[int]:
    pending = {r.measure_id for r in f.plan}
    return [i for i, r in enumerate(f.plan) if not (set(r.depends_on) & pending)]


def _rank(f: ComputedFacts, objective: str) -> list[tuple[float, int]]:
    _, fn = OBJECTIVES[objective]
    ranked = [(fn(f.plan[i]) * SUITABILITY_WEIGHT[f.plan[i].suitability], i) for i in _eligible(f)
              if f.plan[i].standalone.carbon.total_kg >= MIN_CARBON_KG]
    return sorted(ranked, key=lambda x: (-x[0], f.plan[x[1]].order))


def _alternatives(f: ComputedFacts, objective: str, exclude: int | None, why: str) -> list[NBAAlternative]:
    out = []
    for score, i in _rank(f, objective):
        if i == exclude:
            continue
        r = f.plan[i]
        out.append(NBAAlternative(action=NBAAction(kind="retrofit", ref=r.measure_id, label=r.name),
                                  benefit=round(score, 1), why_not_first=why))
    pending = {r.measure_id for r in f.plan}
    for r in f.plan:
        waiting = [m for m in r.depends_on if m in pending]
        if waiting:
            out.append(NBAAlternative(action=NBAAction(kind="retrofit", ref=r.measure_id, label=r.name),
                                      why_not_first=f"after {', '.join(w.replace('_', ' ') for w in waiting)}"))
    return out[:4]


def select_next_best_action(f: ComputedFacts, objective: str = DEFAULT_OBJECTIVE) -> NextBestAction:
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown objective {objective!r}; choose one of {sorted(OBJECTIVES)}")
    blocked = _blocked(f)
    if blocked is not None:
        return blocked

    zero_use = f.package is not None and f.package.impact.electricity.baseline_kwh == 0 \
        and f.package.impact.gas.baseline_kwh == 0
    ranked = [] if zero_use else _rank(f, objective)
    if not ranked:
        reasons = []
        if zero_use:
            reasons.append(NBAReason(code="zero_use", fact_ref="baseline",
                                     text="Metered energy use is zero (the home looks unoccupied), so savings cannot be estimated."))
        not_needed = [e.name.lower() for e in f.excluded if e.status in ("not_needed", "completed")]
        if not_needed:
            reasons.append(NBAReason(code="already_done", fact_ref="excluded",
                                     text=f"Already in place: {', '.join(not_needed)}."))
        if f.plan and not zero_use:
            reasons.append(NBAReason(code="small_benefit", fact_ref="plan",
                                     text=f"No remaining feasible measure saves more than {MIN_CARBON_KG:.0f} kg CO2e a year."))
        return NextBestAction(
            action=NBAAction(kind="no_action", label="No action needed now"), disposition="no_action",
            headline="Nothing worth doing right now." if not zero_use
            else "No action until the home is occupied and metered use can be assessed.",
            reasons=_pad(reasons, f), objective=objective, confidence=f.confidence.level,
            alternatives=[], method_version=NBA_VERSION)

    unit, _ = OBJECTIVES[objective]
    score, i = ranked[0]
    r = f.plan[i]
    conf = min(f.confidence.level, {"High": "high", "Medium": "medium", "Low": "low"}[r.suitability], key=_LEVEL.get)
    return NextBestAction(
        action=NBAAction(kind="retrofit", ref=r.measure_id, label=r.name), disposition="recommend",
        headline=f"Next: {r.name.lower()}.",
        reasons=_retrofit_reasons(f, i, objective), objective=objective, benefit=round(score, 1), benefit_unit=unit,
        confidence=conf, alternatives=_alternatives(f, objective, exclude=i, why="ranks lower on the objective"),
        method_version=NBA_VERSION)
