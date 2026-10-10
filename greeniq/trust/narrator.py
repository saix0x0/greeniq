"""Template narrator: plain-English explanations built ONLY from ComputedFacts.

Every sentence carries the fact paths it was built from, so the UI can link each claim to
its receipt and the grounding gate (P5) can check any language-model text against the
same facts. This is the default explainer and the fallback whenever no LLM is available.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..facts import ComputedFacts, Impact

NARRATOR_VERSION = "template-narrator/1.0"


class Sentence(BaseModel):
    text: str
    refs: list[str]


class Explanation(BaseModel):
    mode: str = "template"
    version: str = NARRATOR_VERSION
    facts_id: str
    sentences: list[Sentence]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


def _k(x: float) -> str:
    return f"{abs(x):,.0f}"


def fuel_sentence(imp: Impact, ref: str, subject: str = "This package") -> Sentence:
    e, g = imp.electricity.saving_kwh or 0.0, imp.gas.saving_kwh or 0.0
    parts = []
    if g:
        parts.append(f"{'cuts' if g > 0 else 'adds'} gas by {_k(g)} kWh")
    if e:
        parts.append(f"{'cuts' if e > 0 else 'raises'} electricity by {_k(e)} kWh")
    body = " and ".join(parts) if parts else "barely changes purchased energy"
    tail = ""
    if e < 0 < g:
        tail = " Electricity goes up because heat now comes from electricity; gas falls by more, so the net is a saving."
    return Sentence(text=f"{subject} {body} a year (net {imp.net_saving_kwh:+,.0f} kWh, estimate).{tail}",
                    refs=[f"{ref}.electricity.saving_kwh", f"{ref}.gas.saving_kwh", f"{ref}.net_saving_kwh"])


def explain_home(f: ComputedFacts) -> Explanation:
    s: list[Sentence] = []
    sc = f.score
    if sc.score is not None:
        s.append(Sentence(text=f"This home scores {sc.score}/100 ({sc.band}) on the Green Home Score"
                               f"{'' if sc.status == 'complete' else ', provisional because some inputs are assumed'}.",
                          refs=["score.score", "score.band", "score.status"]))
    else:
        s.append(Sentence(text=f"The score can only be given as a range, {sc.score_range[0]}-{sc.score_range[1]}, "
                               f"because {', '.join(sc.missing_components)} could not be assessed.",
                          refs=["score.score_range", "score.missing_components"]))
    if sc.issues:
        i = sc.issues[0]
        s.append(Sentence(text=f"Most points are lost on {i.label.lower()} ({i.points_available:.1f} points available).",
                          refs=["score.issues[0]"]))
    if f.next_best_action:
        s.append(Sentence(text=f.next_best_action.headline, refs=["next_best_action"]))
    if f.package:
        s.extend(explain_package(f).sentences)
    s.append(Sentence(text=f"Confidence is {f.confidence.level}: {f.confidence.reasons[0]}", refs=["confidence"]))
    return Explanation(facts_id=f.facts_id, sentences=s)


def explain_package(f: ComputedFacts) -> Explanation:
    pk = f.package
    s: list[Sentence] = []
    if pk is None:
        return Explanation(facts_id=f.facts_id, sentences=[Sentence(
            text="No package could be modelled for this home (no feasible measures or no energy baseline).",
            refs=["package"])])
    names = ", ".join(m.replace("_", " ") for m in pk.measures)
    n = len(pk.measures)
    s.append(Sentence(text=f"Modelled package ({n} measure{'s' if n != 1 else ''}, in {pk.order.replace('_', ' ')} order): {names}.",
                      refs=["package.measures", "package.order"]))
    s.append(fuel_sentence(pk.impact, "package.impact"))
    c = pk.impact.carbon.total_tonnes
    s.append(Sentence(text=f"That {'cuts' if c >= 0 else 'adds'} about {abs(c):.2f} t CO2e a year.",
                      refs=["package.impact.carbon.total_tonnes"]))
    if len(pk.measures) > 1 and abs(pk.interaction_kwh) >= 10:
        s.append(Sentence(
            text=(f"Savings do not simply add up: the measures separately would save {pk.sum_of_standalone_net_kwh:,.0f} kWh, "
                  f"together {pk.impact.net_saving_kwh:,.0f} kWh, because you can't save the same heat twice."),
            refs=["package.sum_of_standalone_net_kwh", "package.impact.net_saving_kwh", "package.interaction_kwh"]))
    if pk.score_after is not None and f.score.score is not None:
        s.append(Sentence(text=f"The score would move from {f.score.score} to {pk.score_after} ({pk.band_after}).",
                          refs=["score.score", "package.score_after", "package.band_after"]))
    if pk.epc_band_before and pk.epc_band_after:
        moved = (f"Estimated EPC band {pk.epc_band_before} to {pk.epc_band_after}." if pk.epc_band_before != pk.epc_band_after
                 else f"Estimated EPC band stays {pk.epc_band_before}.")
        s.append(Sentence(text=moved,
                          refs=["package.epc_band_before", "package.epc_band_after"]))
    s.append(Sentence(text=f"Indicative cost £{pk.cost_low:,}-£{pk.cost_high:,}.", refs=["package.cost_low", "package.cost_high"]))
    if f.scenario and f.scenario.rejected:
        s.append(Sentence(text="Not modelled: " + "; ".join(f"{r.name} ({r.reason})" for r in f.scenario.rejected),
                          refs=["scenario.rejected"]))
    return Explanation(facts_id=f.facts_id, sentences=s)
