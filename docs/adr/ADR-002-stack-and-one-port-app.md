# ADR-002 · Stack: Python core, FastAPI, no-build web app on one port

- **Status:** accepted
- **Date:** 2026-10-10
- **Requirements:** FR-8, ER-3, SR-A, SR-B

## Context
The judges must be able to run a fresh clone. The build machine has Python but no npm,
and many judges' machines will be the same. The pasted plan suggested React + Vite +
Tailwind + Recharts, which needs a Node toolchain to build.

## Options considered
| Option | Pros | Cons |
|---|---|---|
| A · React/Vite SPA + FastAPI | Familiar component model | Needs Node + npm to build; two processes or a committed build; more moving parts |
| B · Streamlit/Gradio | Very fast to build | Hard to make distinctive; weak control over interaction and receipts |
| **C · FastAPI serving a no-build web app (HTML + ES modules + hand-written SVG charts)** | One command, one port, only Python needed; full control of the UI; no CDN at runtime | We write our own small chart helpers |

## Decision
**Option C.** Python 3.11+ managed with `uv` (pinned lock file). Core: numpy, pandas,
scikit-learn, pydantic. API: FastAPI + uvicorn. Persistence: SQLite from the standard
library. UI: static files under `greeniq/web/`, no build step, no external CDN. LLM:
the `anthropic` SDK as an optional extra; the app is complete without it.

## Consequences
- ✅ `uv run greeniq serve` (or `pip install -e . && greeniq serve`) is the whole setup.
- ✅ Works offline; no keys needed.
- ⚠️ Charts are hand-rolled SVG. That is acceptable: they are simple bars, gauges and a radial "fingerprint".
- 🔁 If the team later wants React, the API contract does not change.
