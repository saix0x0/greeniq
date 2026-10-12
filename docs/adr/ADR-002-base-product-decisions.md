# ADR-002 · Base-product implementation decisions

- **Status:** accepted
- **Date:** 2026-10-10
- **Requirements:** all mandatory PS2 requirements

## Context
The architecture's shape was fixed early, but methods, data and stack were left open.
This ADR records the concrete decisions taken for the build. Implementation details live
in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`../SCORING_METHOD.md`](../SCORING_METHOD.md).

## Decisions
| Area | Decision | Why |
|---|---|---|
| Data backbone | **DESNZ NEED anonymised 2026, 50k sample** (OGL, no registration) + documented synthetic augmentation | The only public, property-level, freely downloadable source with real gas and electricity use *and* property characteristics *and* real retrofit installs; avoids EPC registration and big downloads |
| Stack | FastAPI + Pydantic v2 + SQLite/SQLAlchemy; pandas/scikit-learn; React + TS + Vite + Tailwind + Recharts | Fewest moving parts; one-port run; strong typing end to end |
| Score | Exact PS weights; band-midpoint rating, peer-normalised intensity, element tables; bounds for missing data; round half up | Monotonic, documented, honest about missing inputs without changing the fixed weights |
| Savings | Deterministic end-use + relative heat-loss model, sequential package, **in-use calibration from real NEED CWI/LI installs** | Interactions by construction; anchored to observed real-world savings |
| Rating projection | SAP 2012 ECF functional form with a cost ratio | "Documented rating-based measure" for scenario efficiency and value bands |
| Carbon | DESNZ 2026: electricity 0.13096, gas 0.18231 kgCO₂e/kWh (Scope 1 + 2, location-based) | Latest official set; a consistent scope |
| Value | Hedonic OLS with band dummies + bootstrap range; synthetic sales calibrated to UK HPI Jul 2026 and DECC 2013 associations | Range plus explicit non-causal framing; honest about synthetic validation |
| ML | HGBR per fuel on real NEED features vs a peer-median baseline | PS-suggested regression, evaluated on real held-out data |
| LLM | `claude-opus-5-5`, effort low, structured outputs, citation-bound verifier, template fallback | Grounded by construction; works with no key; forced tool calls are unsupported on this model |
| Scope | Customer memory deferred (optional in PS) | Keeps the one-pass build complete for every mandatory requirement |

## Consequences
Claude-2 builds without re-litigating these. Each can be swapped later behind its seam
(`08`), but only after beating its baseline on held-out data.
