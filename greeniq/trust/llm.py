"""Optional Claude narrator. Off unless credentials and the `anthropic` package are present.

The model only rephrases a compact fact sheet; its output must pass the grounding gate or the
template explanation is shown instead. The app is fully functional with this module off.
"""

from __future__ import annotations

import json
import os

from ..facts import ComputedFacts
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, USER_TEMPLATE

MODEL = os.environ.get("GREENIQ_LLM_MODEL", "claude-opus-5-5")


def llm_status() -> tuple[bool, str]:
    if os.environ.get("GREENIQ_LLM", "").lower() == "off":
        return False, "disabled (GREENIQ_LLM=off)"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False, "no API key (template narrator)"
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "anthropic package not installed (uv sync --extra llm)"
    return True, f"{MODEL} behind the grounding gate"


def fact_sheet(f: ComputedFacts, scope: str) -> dict:
    """The compact subset of facts the model sees (everything in it is checkable)."""
    sheet = {
        "score": {"score": f.score.score, "range": f.score.score_range, "band": f.score.band, "status": f.score.status,
                  "biggest_gaps": [{"label": i.label, "points_available": round(i.points_available, 1)} for i in f.score.issues[:3]]},
        "baseline_kwh": {k: {"annual_kwh": b.annual_kwh, "basis": b.basis} for k, b in f.baseline.items()},
        "confidence": {"level": f.confidence.level, "reason": f.confidence.reasons[0]},
    }
    if f.next_best_action and scope == "home":
        n = f.next_best_action
        sheet["next_best_action"] = {"headline": n.headline, "reasons": [r.text for r in n.reasons]}
    if f.package:
        pk, im = f.package, f.package.impact
        sheet["package"] = {
            "measures": [m.replace("_", " ") for m in pk.measures],
            "electricity": {"baseline_kwh": im.electricity.baseline_kwh, "after_kwh": im.electricity.after_kwh,
                            "saving_kwh": im.electricity.saving_kwh},
            "gas": {"baseline_kwh": im.gas.baseline_kwh, "after_kwh": im.gas.after_kwh, "saving_kwh": im.gas.saving_kwh},
            "net_saving_kwh": im.net_saving_kwh, "carbon_saving_kg": im.carbon.total_kg,
            "sum_of_standalone_savings_kwh": pk.sum_of_standalone_net_kwh, "interaction_kwh": pk.interaction_kwh,
            "score_after": pk.score_after, "band_after": pk.band_after,
            "epc_band_before": pk.epc_band_before, "epc_band_after": pk.epc_band_after,
            "cost_low_gbp": pk.cost_low, "cost_high_gbp": pk.cost_high,
        }
    if f.value and f.value.status == "available":
        sheet["value"] = {"uplift_pct_range": f.value.uplift_pct_range, "caveat": f.value.caveat}
    if f.scenario and f.scenario.rejected:
        sheet["not_modelled"] = [{"measure": r.name, "reason": r.reason} for r in f.scenario.rejected]
    return sheet


def generate(f: ComputedFacts, scope: str) -> tuple[str | None, str]:
    """Return (text, note). text is None when the model could not answer (never raises)."""
    ok, why = llm_status()
    if not ok:
        return None, why
    import anthropic

    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=2000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # server-side refusal fallback routed by category
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": USER_TEMPLATE.format(
                scope="home's analysis" if scope == "home" else "retrofit package",
                facts_json=json.dumps(fact_sheet(f, scope), sort_keys=True))}],
        )
    except anthropic.APIConnectionError:
        return None, "language model unreachable"
    except anthropic.RateLimitError:
        return None, "language model rate-limited"
    except anthropic.APIStatusError as e:
        return None, f"language model error {e.status_code}"
    if resp.stop_reason == "refusal":
        return None, "language model declined"
    text = " ".join(b.text for b in resp.content if b.type == "text").strip()
    return (text or None), f"{resp.model} · {PROMPT_VERSION}"
