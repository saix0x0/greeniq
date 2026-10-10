"""A stand-in for an Ollama server (protocol-accurate, no model weights), for testing at zero cost.

It speaks Ollama's native API (GET /api/tags, POST /api/chat) and the OpenAI-compatible
POST /v1/chat/completions, so GreenIQ's real HTTP client code is exercised end to end.
It is NOT a language model: it writes replies from the FACTS JSON it is sent, and can be told
to misbehave the way real models do, to prove the grounding gate catches it.

Modes:
    honest       paraphrases the facts correctly, in different words from the template
    meaning      a digit-free explanation of what the facts mean (hybrid mode)
    meaning_flip the same, but says electricity falls when it rises
    invent       inflates a saving (a hallucinated number)
    flip         says electricity falls when the facts say it rises (the heat-pump trap)
    promise      adds "this will increase your home's value"
    slow         answers after a delay (to test timeouts)
    error        returns HTTP 500
    empty        returns an empty message

Manual use (see the app in "language model" mode without installing Ollama):
    python tests/fake_ollama.py --mode honest --port 11434
    GREENIQ_LLM_PROVIDER=ollama uv run python -m greeniq serve
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "qwen2.5:7b"


def _facts(user: str) -> dict:
    m = re.search(r"FACTS:\s*(\{.*\})\s*$", user, re.S)
    return json.loads(m.group(1)) if m else {}


def reply(user: str, mode: str) -> str:
    f = _facts(user)
    if mode.startswith("meaning"):
        pk = f.get("package") or {}
        rises = "RISES" in (pk.get("electricity", {}).get("change") or "")
        if rises and mode == "meaning_flip":
            return "A heat pump makes your electricity use fall and your gas use fall too."
        if rises:
            return ("Heat would come from electricity instead of gas, so electricity use goes up while gas use falls "
                    "by much more. Insulating first means the heat pump has less work to do.")
        return "Most of the gain comes from keeping heat in, so the home needs less energy to stay warm."
    s = f.get("score", {})
    parts = []
    if s.get("score") is not None:
        parts.append(f"Your home's Green Home Score is {s['score']}/100, which puts it in the {s['band']} band.")
    pk = f.get("package")
    if pk:
        e, g = pk["electricity"]["saving_kwh"] or 0, pk["gas"]["saving_kwh"] or 0
        if mode == "invent" and g:
            g = g * 1.5 + 77
        if g:
            parts.append(f"Gas use would {'fall' if g > 0 else 'rise'} by {abs(g):,.0f} kWh a year.")
        if e:
            word = "fall" if e > 0 else "rise"
            if mode == "flip" and e < 0:
                word = "fall"
            parts.append(f"Electricity use would {word} by {abs(e):,.0f} kWh a year.")
        parts.append(f"Overall that is a net saving of {pk['net_saving_kwh']:,.0f} kWh a year, an estimate.")
        if pk.get("score_after") is not None and s.get("score") is not None:
            parts.append(f"The score could rise to {pk['score_after']}.")
    if mode == "promise":
        parts.append("This will increase your home's value.")
    return " ".join(parts)


class _Handler(BaseHTTPRequestHandler):
    server_version = "fake-ollama/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": self.server.model}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.server.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        mode = self.server.mode
        if mode == "error":
            return self._json(500, {"error": "boom"})
        if mode == "slow":
            time.sleep(self.server.delay)
        user = next((m["content"] for m in body.get("messages", []) if m["role"] == "user"), "")
        text = "" if mode == "empty" else reply(user, mode)
        if self.path == "/api/chat":
            self._json(200, {"model": body.get("model"), "message": {"role": "assistant", "content": text}, "done": True})
        elif self.path == "/v1/chat/completions":
            self._json(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})
        else:
            self._json(404, {"error": "not found"})


class FakeOllama:
    """Context manager: ``with FakeOllama(mode="honest") as srv: srv.url``."""

    def __init__(self, mode: str = "honest", model: str = MODEL, port: int = 0, delay: float = 3.0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.mode, self.httpd.model, self.httpd.delay, self.httpd.requests = mode, model, delay, []
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    @property
    def requests(self) -> list:
        return self.httpd.requests

    def set_mode(self, mode: str) -> None:
        self.httpd.mode = mode

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", default="honest")
    ap.add_argument("--port", type=int, default=11434)
    a = ap.parse_args()
    srv = FakeOllama(a.mode, port=a.port)
    print(f"fake Ollama ({a.mode}) at {srv.url} serving model {MODEL!r}; Ctrl+C to stop")
    try:
        srv.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
