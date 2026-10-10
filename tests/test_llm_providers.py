"""Language-model providers (Ollama, OpenAI-compatible) through the real HTTP path, at zero cost.

A protocol-accurate fake Ollama server (tests/fake_ollama.py) stands in for the model, so the
request format, response parsing, timeouts, errors and the grounding gate are all exercised
without downloading anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fake_ollama import MODEL, FakeOllama  # noqa: E402

from greeniq.context import load_context  # noqa: E402
from greeniq.contract import Property  # noqa: E402
from greeniq.pipeline import analyse_home  # noqa: E402
from greeniq.trust import llm  # noqa: E402
from greeniq.trust.narrator import explain  # noqa: E402

FIX = {f["property"]["property_id"]: f for f in
       json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())}


@pytest.fixture(scope="module")
def hp():
    return analyse_home(Property(**FIX["FX-HP-CANDIDATE"]["property"]), load_context())


@pytest.fixture
def ollama(monkeypatch):
    with FakeOllama() as srv:
        monkeypatch.delenv("GREENIQ_LLM", raising=False)
        monkeypatch.setenv("GREENIQ_LLM_PROVIDER", "ollama")
        monkeypatch.setenv("GREENIQ_OLLAMA_URL", srv.url)
        monkeypatch.setenv("GREENIQ_LLM_TIMEOUT_S", "1")
        monkeypatch.setattr(llm, "TIMEOUT_S", 1.0)
        llm._CACHE.clear()
        yield srv
    llm._CACHE.clear()


def test_ollama_is_detected_and_reported(ollama):
    name, why = llm.provider()
    assert name == "ollama" and MODEL in why


def test_honest_ollama_answer_is_shown_as_llm(ollama, hp):
    e = explain(hp, "package")
    assert e.mode == "llm" and e.gate["passed"], e.note
    assert e.version.startswith(f"ollama/{MODEL}")
    req = ollama.requests[-1]
    assert req["path"] == "/api/chat" and req["body"]["stream"] is False
    assert req["body"]["options"]["temperature"] == 0
    assert req["body"]["messages"][0]["role"] == "system" and "FACTS" in req["body"]["messages"][1]["content"]


@pytest.mark.parametrize("mode,reason", [("invent", "does not match"), ("flip", "rises in this package"),
                                         ("promise", "causal")])
def test_misbehaving_model_is_blocked_and_template_shown(ollama, hp, mode, reason):
    ollama.set_mode(mode)
    e = explain(hp, "package")
    assert e.mode == "template" and "blocked by the grounding gate" in e.note
    assert e.gate["passed"]  # what IS shown passes


@pytest.mark.parametrize("mode,note", [("slow", "timed out"), ("error", "error 500"), ("empty", "")])
def test_model_failures_fall_back_without_breaking(ollama, hp, mode, note):
    ollama.set_mode(mode)
    e = explain(hp, "package")
    assert e.mode == "template" and note in (e.note or "")


def test_missing_model_is_reported_not_used(ollama, monkeypatch):
    monkeypatch.setenv("GREENIQ_OLLAMA_MODEL", "llama-not-pulled")
    llm._CACHE.clear()
    name, why = llm.provider()
    assert name == "off" and "not pulled" in why


def test_unreachable_ollama_means_template(monkeypatch, hp):
    monkeypatch.delenv("GREENIQ_LLM", raising=False)
    monkeypatch.setenv("GREENIQ_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("GREENIQ_OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    llm._CACHE.clear()
    assert llm.provider()[0] == "off"
    assert explain(hp, "package").mode == "template"
    llm._CACHE.clear()


def test_openai_compatible_endpoint_with_key(monkeypatch, hp):
    with FakeOllama() as srv:
        monkeypatch.delenv("GREENIQ_LLM", raising=False)
        monkeypatch.setenv("GREENIQ_LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("GREENIQ_LLM_BASE_URL", srv.url + "/v1")
        monkeypatch.setenv("GREENIQ_LLM_MODEL", "free-tier-model")
        monkeypatch.setenv("GREENIQ_LLM_API_KEY", "test-key")
        llm._CACHE.clear()
        e = explain(hp, "package")
        assert e.mode == "llm" and e.gate["passed"]
        assert srv.requests[-1]["headers"]["Authorization"] == "Bearer test-key"
    llm._CACHE.clear()


def test_auto_prefers_a_running_ollama_and_off_switch_wins(ollama, monkeypatch):
    monkeypatch.setenv("GREENIQ_LLM_PROVIDER", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GREENIQ_LLM_BASE_URL", raising=False)
    llm._CACHE.clear()
    assert llm.provider()[0] == "ollama"
    monkeypatch.setenv("GREENIQ_LLM", "off")
    llm._CACHE.clear()
    assert llm.provider()[0] == "off"


def test_grounding_eval_runs_the_model_path(ollama, monkeypatch, tmp_path):
    """The groundedness evaluation measures a real provider when one is configured."""
    from greeniq.evaluation import grounding
    monkeypatch.setattr(grounding, "REPORTS", tmp_path)
    o = grounding.evaluate_grounding(n_homes=6, llm_homes=6)
    L = o["llm"]
    assert L["run"] and L["explanations"] > 0
    assert L["passed"] == L["explanations"]  # the honest stand-in is fully grounded
