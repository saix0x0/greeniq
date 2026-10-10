"""Optional language-model narrator, behind the grounding gate. Off unless a provider is configured.

Providers (chosen by ``GREENIQ_LLM_PROVIDER``; default ``auto``):

- ``anthropic``  Claude via the official SDK (needs ``ANTHROPIC_API_KEY`` and ``uv sync --extra llm``).
- ``ollama``     a local Ollama server, native ``/api/chat`` (no key, no cost, offline).
                 ``GREENIQ_OLLAMA_URL`` (default http://127.0.0.1:11434), ``GREENIQ_OLLAMA_MODEL`` (default qwen2.5:7b).
- ``openai_compatible``  any OpenAI-compatible ``/chat/completions`` endpoint, e.g. free tiers of Groq,
                 Google Gemini or OpenRouter, or Ollama's ``/v1``: ``GREENIQ_LLM_BASE_URL``,
                 ``GREENIQ_LLM_API_KEY``, ``GREENIQ_LLM_MODEL``.
- ``off``        template narrator only (also ``GREENIQ_LLM=off``).

``auto`` picks Anthropic if a key is set, else an OpenAI-compatible endpoint if configured, else
Ollama if a server answers within one second, else off. Whatever the model writes, it only reaches
a user if it passes the grounding gate; otherwise the template explanation is shown. Nothing here
ever raises into the app.
"""

from __future__ import annotations

import json
import os
import re

import httpx

from ..facts import ComputedFacts
from .prompts import HYBRID_PROMPT_VERSION, HYBRID_SYSTEM_PROMPT, PROMPT_VERSION, SYSTEM_PROMPT, USER_TEMPLATE

CLAUDE_MODEL = "claude-opus-5-5"
TIMEOUT_S = float(os.environ.get("GREENIQ_LLM_TIMEOUT_S", "60"))


def _env(k: str, default: str = "") -> str:
    return os.environ.get(k, default).strip()


def _ollama_url() -> str:
    return _env("GREENIQ_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _ollama_model() -> str:
    return _env("GREENIQ_OLLAMA_MODEL", "qwen2.5:7b")


def _ollama_probe() -> tuple[bool, str]:
    """Fast reachability + model check (1 s), so a missing server never slows the app."""
    try:
        r = httpx.get(f"{_ollama_url()}/api/tags", timeout=1.0)
        r.raise_for_status()
        names = {m.get("name", "") for m in r.json().get("models", [])}
    except Exception:
        return False, f"Ollama not reachable at {_ollama_url()}"
    want = _ollama_model()
    if want not in names and f"{want}:latest" not in names:
        return False, f"Ollama is running but model {want!r} is not pulled (ollama pull {want})"
    return True, f"Ollama {want} behind the grounding gate"


_CACHE: dict = {}
_ENV_KEYS = ("GREENIQ_LLM", "GREENIQ_LLM_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GREENIQ_LLM_BASE_URL",
             "GREENIQ_LLM_MODEL", "GREENIQ_OLLAMA_URL", "GREENIQ_OLLAMA_MODEL")


def provider() -> tuple[str, str]:
    """(provider name, human-readable status), cached for 10 s per configuration."""
    import time

    key = tuple(_env(k) for k in _ENV_KEYS)
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 10:
        return hit[1]
    out = _provider()
    _CACHE.clear()
    _CACHE[key] = (time.monotonic(), out)
    return out


def _provider() -> tuple[str, str]:
    if _env("GREENIQ_LLM").lower() == "off":
        return "off", "disabled (GREENIQ_LLM=off)"
    want = _env("GREENIQ_LLM_PROVIDER", "auto").lower()
    if want == "off":
        return "off", "disabled (GREENIQ_LLM_PROVIDER=off)"
    if want in ("auto", "anthropic") and (_env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN")):
        try:
            import anthropic  # noqa: F401
            return "anthropic", f"{_env('GREENIQ_LLM_MODEL', CLAUDE_MODEL)} behind the grounding gate"
        except ImportError:
            if want == "anthropic":
                return "off", "anthropic package not installed (uv sync --extra llm)"
    elif want == "anthropic":
        return "off", "no ANTHROPIC_API_KEY (template narrator)"
    if want in ("auto", "openai_compatible") and _env("GREENIQ_LLM_BASE_URL"):
        if not _env("GREENIQ_LLM_MODEL"):
            return "off", "GREENIQ_LLM_MODEL not set for the OpenAI-compatible endpoint"
        return "openai_compatible", f"{_env('GREENIQ_LLM_MODEL')} at {_env('GREENIQ_LLM_BASE_URL')} behind the grounding gate"
    if want == "openai_compatible":
        return "off", "GREENIQ_LLM_BASE_URL not set"
    if want in ("auto", "ollama"):
        ok, why = _ollama_probe()
        if ok:
            return "ollama", why
        if want == "ollama":
            return "off", why
    return "off", "no language model configured (template narrator)"


def llm_status() -> tuple[bool, str]:
    name, why = provider()
    return name != "off", why


def _change(saving: float | None) -> str:
    """Direction in words, so a model never has to interpret a negative 'saving' (the heat-pump trap)."""
    if not saving:
        return "no change"
    return f"{'falls' if saving > 0 else 'RISES'} by {abs(saving):,.0f} kWh a year"


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
                            "saving_kwh": im.electricity.saving_kwh, "change": _change(im.electricity.saving_kwh)},
            "gas": {"baseline_kwh": im.gas.baseline_kwh, "after_kwh": im.gas.after_kwh, "saving_kwh": im.gas.saving_kwh,
                    "change": _change(im.gas.saving_kwh)},
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


def _words(s: str | None) -> str:
    """Drop every token containing a digit (e.g. '270 mm', '£150-£350'), so a sheet can't leak figures."""
    s = re.sub(r"[£$]?\S*\d\S*(\s+(mm|kWh|kg|t|m²|%|points?|years?|a year))?", "", s or "")
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;:)])", r"\1", s)).strip()


def _dir(saving: float | None) -> str:
    return "no change" if not saving else ("falls" if saving > 0 else "RISES")


def _say(fuel: str, saving: float) -> str:
    return f"{fuel} use stays about the same" if not saving else f"{fuel} use goes {'down' if saving > 0 else 'UP'}"


def meaning_sheet(f: ComputedFacts, scope: str) -> dict:
    """Hybrid style: the facts as words only — no digits anywhere — so a small model has no figure to copy.

    Comparisons ("gas falls by much more than electricity rises") are decided here, in code.
    """
    sheet: dict = {
        "score_band": f.score.band or "not certain (a key input is missing)",
        "score_is": "provisional: some inputs assumed" if f.score.status != "complete" else "complete: from recorded data",
        "biggest_weaknesses": [i.label for i in f.score.issues[:3]],
        "energy_data": {k: b.basis for k, b in f.baseline.items()},
        "confidence": f.confidence.level,
    }
    n = f.next_best_action
    if n and scope == "home":
        sheet["do_first"] = n.action.ref.replace("_", " ") if n.action.kind == "retrofit" and n.action.ref else _words(n.headline)
    if f.package:
        pk, im = f.package, f.package.impact
        e, g = im.electricity.saving_kwh or 0, im.gas.saving_kwh or 0
        sheet["package"] = {
            "measures_in_order": [m.replace("_", " ") for m in pk.measures],
            "electricity": {"change": _dir(e), "say": _say("electricity", e)}, "gas": {"change": _dir(g), "say": _say("gas", g)},
            "overall_energy": "falls" if im.net_saving_kwh > 0 else "rises" if im.net_saving_kwh < 0 else "no change",
            "carbon": "falls" if im.carbon.total_kg > 0 else "rises" if im.carbon.total_kg < 0 else "no change",
            "savings_overlap": bool(pk.interaction_kwh and pk.interaction_kwh < 0),
            "band_after": pk.band_after, "epc_band": f"{pk.epc_band_before} to {pk.epc_band_after}",
        }
        if e < 0 < g:
            sheet["package"]["trade_off"] = ("electricity rises because heat comes from electricity instead of gas; "
                                             + ("gas falls by much more" if g > 2 * -e else "gas falls by more"))
    if f.scenario and f.scenario.rejected:
        sheet["not_modelled"] = [r.name for r in f.scenario.rejected]
    return sheet


def _messages(f: ComputedFacts, scope: str, st: str = "full") -> str:
    sheet = meaning_sheet(f, scope) if st == "hybrid" else fact_sheet(f, scope)
    return USER_TEMPLATE.format(scope="home's analysis" if scope == "home" else "retrofit package",
                                facts_json=json.dumps(sheet, sort_keys=True, ensure_ascii=False))


def style() -> str:
    """'hybrid' (default): the model explains meaning, the engine states every number. 'full': the model writes
    the whole explanation including figures (suits strong models); the gate checks either way."""
    s = _env("GREENIQ_LLM_STYLE", "hybrid").lower()
    return s if s in ("hybrid", "full") else "hybrid"


def _prompt(st: str) -> tuple[str, str]:
    return (HYBRID_SYSTEM_PROMPT, HYBRID_PROMPT_VERSION) if st == "hybrid" else (SYSTEM_PROMPT, PROMPT_VERSION)


def _anthropic(user: str, st: str = "full") -> tuple[str | None, str]:
    import anthropic

    model = _env("GREENIQ_LLM_MODEL", CLAUDE_MODEL)
    client = anthropic.Anthropic(timeout=TIMEOUT_S)
    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=2000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # server-side refusal fallback routed by category
            system=_prompt(st)[0],
            messages=[{"role": "user", "content": user}],
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
    return (text or None), f"{resp.model} · {_prompt(st)[1]}"


def _ollama(user: str, st: str = "full") -> tuple[str | None, str]:
    model = _ollama_model()
    r = httpx.post(f"{_ollama_url()}/api/chat", timeout=TIMEOUT_S, json={
        "model": model, "stream": False,
        "options": {"temperature": 0, "seed": 42},  # deterministic, so a result can be reproduced
        "messages": [{"role": "system", "content": _prompt(st)[0]}, {"role": "user", "content": user}],
    })
    r.raise_for_status()
    text = (r.json().get("message") or {}).get("content", "").strip()
    return (text or None), f"ollama/{model} · {_prompt(st)[1]}"


def _openai_compatible(user: str, st: str = "full") -> tuple[str | None, str]:
    base, model, key = _env("GREENIQ_LLM_BASE_URL").rstrip("/"), _env("GREENIQ_LLM_MODEL"), _env("GREENIQ_LLM_API_KEY")
    r = httpx.post(f"{base}/chat/completions", timeout=TIMEOUT_S,
                   headers={"Authorization": f"Bearer {key}"} if key else {},
                   json={"model": model, "temperature": 0, "max_tokens": 800,
                         "messages": [{"role": "system", "content": _prompt(st)[0]}, {"role": "user", "content": user}]})
    r.raise_for_status()
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    return (text or None), f"{model} · {_prompt(st)[1]}"


def generate(f: ComputedFacts, scope: str, st: str | None = None) -> tuple[str | None, str]:
    """Return (text, note). text is None when no model could answer. Never raises."""
    name, why = provider()
    if name == "off":
        return None, why
    st = st or style()
    user = _messages(f, scope, st)
    try:
        fn = {"anthropic": _anthropic, "ollama": _ollama, "openai_compatible": _openai_compatible}[name]
        return fn(user, st)
    except httpx.TimeoutException:
        return None, f"language model ({name}) timed out"
    except httpx.HTTPStatusError as e:
        return None, f"language model ({name}) error {e.response.status_code}"
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as e:
        return None, f"language model ({name}) unavailable: {type(e).__name__}"
