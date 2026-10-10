# ADR-001 · Deterministic core, grounded language at the edge

- **Status:** accepted (foundational; set by the team before the build)
- **Date:** 2026-10-10
- **Requirements:** FR-1…FR-7, ER-4, ER-5

## Context
PS2's core rule says scores, savings, carbon and value must come from documented models
and calculations. The LLM may only explain them and answer what-if questions after the
models are rerun. Judges target ≥90% groundedness, ≥90% factual accuracy and <5%
unsupported claims, and will probe with missing data, conflicts and infeasible
retrofits.

## Options considered
| Option | Pros | Cons |
|---|---|---|
| A · LLM does the analysis end to end | Fast to prototype | Violates the PS core rule; hallucination; unreproducible |
| B · Engines compute; LLM explains, guarded by prompting alone | Simple | Prompting alone can't guarantee ER-4; failures ship silently |
| **C · Engines compute; LLM explains behind a mechanical grounding gate with a template fallback** | Meets the PS rule by construction; measurable; works with no LLM | Slightly more engineering; gate design needs care |

## Decision
**Option C.** All numbers are produced in a deterministic/evaluated core and published
as immutable, receipted ComputedFacts. The language layer is read-only over facts. Every
language output passes a grounding gate (numbers, entities, forbidden claims). Rejected
output falls back to a deterministic template. What-if requests rerun the engines and
explain only the diff.

## Rationale & sources
- PS2 §1 core rule, §8 what-if flow, §11 LLM targets.
- The mechanism was proven in the team's earlier projects, and is re-implemented here
  for the home-energy domain (Guardrail G2).

## Consequences
- ✅ ER-4 is achieved by construction and measured; demo-safe with no API key.
- ✅ Every number can be explained through its receipt.
- ⚠️ The gate's number/entity matching must handle formatting (currency, %, separators,
  rounding) without letting invented values through. That needs tests.
- 🔁 The narrator is a seam: any model or vendor can be swapped in without touching the core.
