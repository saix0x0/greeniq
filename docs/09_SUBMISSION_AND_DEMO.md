# 09 · Submission & Demo Readiness

> What "ready to submit" means for GreenIQ: the PS2 deliverables checklist, the
> readiness checks, the pitch skeleton and the demo path. No schedule here. The team
> manages timing separately.

## 1. Submission checklist (PS2 §13)

| ID | Artifact | Source in repo | ☐ |
|---|---|---|---|
| SR-A | Working prototype | app + one-command run | ☐ |
| SR-B | Source, data generation/prep scripts, run instructions | repo + README + data card | ☐ |
| SR-C | Trained models + inference code | train + engines | ☐ |
| SR-D | Documented sub-score mappings | scoring methodology doc | ☐ |
| SR-E | LLM prompts, model/API details, eval approach | narrator + LLM doc + eval report | ☐ |
| SR-F | Architecture diagram | adapted from `03` + `assets/` | ☐ |
| SR-G | Evaluation report (validation metrics) | eval output | ☐ |
| SR-H | Responsible-AI note | seeded from `07` §4 | ☐ |
| SR-I | Held-out predictions + schema/label docs | eval output + data card | ☐ |

## 2. Readiness checks (before any submission or demo)

- [ ] A **fresh clone** runs from the README alone, with **no API keys**
- [ ] All tests green (monotonicity, per-fuel signs, gate rejects invented numbers, no
  split leakage, infeasible retrofit refused, baseline-zero → unavailable)
- [ ] The evaluation command runs end to end and regenerates the report
- [ ] Every number on screen opens a receipt
- [ ] The what-if loop recomputes and the explanation covers only the diff
- [ ] Every artifact in §1 exists and is linked from the README

## 3. Pitch skeleton (~10 slides)

1. **Promise:** "How green is my home, what should I fix, what would I save, what is it worth?"
2. **Why it matters to a lender:** greener homes, advice-led products, measurable carbon
3. **The big idea:** code computes every number, AI only explains, and a gate enforces it
4. **Green Home Score:** 7 weighted components, monotonic, contributions shown
5. **Retrofit plan:** feasible, ordered by interactions, H/M/L
6. **Per-fuel savings & carbon:** electricity vs gas; why a heat pump can raise electricity
7. **Value:** an indicative range, honestly non-causal
8. **Live demo:** what-if → everything recomputes → grounded explanation → the gate blocks a fake number
9. **Evidence:** held-out metrics vs baselines, grounding targets, reproducible run
10. **Responsible AI + roadmap:** memory, portfolio console, real data

## 4. Demo path (≈3 minutes)

Open a poor home → click a component to show its receipt → read the retrofit plan →
**what-if toggle** (gauge, per-fuel bars, carbon and value all move) → ask "will this
raise my home's value?" (range + non-causal) → try to make the AI invent a number (the gate
blocks it) → show the evaluation report. **Fallback:** screenshots plus the evaluation
numbers in the deck.
