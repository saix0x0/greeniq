# Contributing to GreenIQ

Thanks for your interest in GreenIQ. This document explains how to set up the project and the
conventions we follow.

## Development setup

```bash
git clone https://github.com/saix0x0/greeniq.git
cd greeniq
uv sync --dev          # creates .venv with pinned dependencies
uv run pytest          # run the full test suite
uv run python -m greeniq serve   # http://127.0.0.1:8000
```

You need **Python 3.11+** and **[uv](https://docs.astral.sh/uv/)**.

## Ground rules

GreenIQ has one invariant, and every change must respect it:

> **Code computes every number. AI only explains. Every number has a receipt.**

- New figures on screen must come from the engine ([`greeniq/pipeline.py`](greeniq/pipeline.py)),
  not from the frontend or the language model.
- Any text an LLM produces must pass the grounding gate
  ([`greeniq/trust/gate.py`](greeniq/trust/gate.py)).
- Every engine behaviour needs a test. The suite must stay green.

## Workflow

1. Fork the repository and create a branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Make your change with tests. Run `uv run pytest` locally.
3. Open a pull request against `main`. CI (lint + tests) must pass.
4. Keep PRs focused — one logical change per PR.

## Commit messages

Write imperative, descriptive subjects (`Add conformal interval to value model`). Explain the
*why* in the body when it isn't obvious.

## Reporting bugs and requesting features

Use the issue templates under [`.github/ISSUE_TEMPLATE`](.github/ISSUE_TEMPLATE). For anything
security-related, follow [`SECURITY.md`](SECURITY.md) instead of opening a public issue.
