# Problem Statement — Lloyds Megathon X, PS2

> **Green Home Score and Retrofit Recommendation Engine.** The original brief is preserved
> verbatim as a PDF: [`reference/LLOYDS-ps2.pdf`](reference/LLOYDS-ps2.pdf). This page summarises
> it and maps each requirement to where GreenIQ implements it.

## The challenge

> *Many customers want an energy-efficient home but do not know where to start.* Build an AI
> system that analyses property characteristics, energy consumption and existing home features to:

1. Calculate a **Green Home Score**.
2. Identify homes with **poor energy efficiency**.
3. Recommend **suitable improvements** (insulation, heat pumps, solar, double glazing, smart controls).
4. Estimate **energy savings and carbon reduction**.
5. Estimate the **potential increase in property value**.

The system answers four homeowner questions: *How green is my home today? What should I improve?
How much energy and carbon could I save? Could this increase my property's value?*

**The core rule set by the brief.** The score, savings, carbon and value figures must come from
documented models and calculations. **The LLM only explains them and answers what-if questions; it
must not calculate the score or invent estimates.** For a what-if request, the models must be
rerun for the proposed scenario first, and the LLM then explains those computed outputs.

## Fixed specification from the brief

**Green Home Score** — a 0–100 weighted sum of seven sub-scores, with fixed weights:

| Component | Weight | | Band | Classification |
|---|---|---|---|---|
| Energy efficiency | 25% | | 80–100 | Highly efficient |
| Energy consumption intensity (kWh/m²) | 20% | | 65–79 | Good |
| Insulation | 15% | | 50–64 | Moderate |
| Heating system | 15% | | 30–49 | Poor |
| Windows and glazing | 10% | | 0–29 | Very poor |
| Renewable energy | 10% | | | |
| Smart energy management | 5% | | | |

Each sub-score must be **monotonic** (a better state never lowers it) and its mapping documented.
Carbon must use `ΔC = Σ_f ΔE_f × EF_f` with documented per-fuel emission factors. Improvement
potential is `100 × (E_baseline − E_after) / E_baseline` on annual purchased energy. Savings and
carbon must be reported **per fuel** (electricity and gas separately), and the property-value
impact must be an **indicative range**, explicitly non-causal.

## How GreenIQ tackles each requirement

| Brief requirement | Our approach | Where |
|---|---|---|
| **Green Home Score** (fixed weights, monotonic, documented) | Seven monotonic sub-scores combined with the brief's fixed weights; every mapping documented and unit-tested | [`greeniq/score.py`](../greeniq/score.py), [`SCORING_METHOD.md`](SCORING_METHOD.md) |
| **Identify poor homes & rank by improvement potential** | Poor/Very-poor flagged with key issues; ranked by true achievable potential (not by raw consumption — avoids the big-house trap) | [`greeniq/pipeline.py`](../greeniq/pipeline.py), Ranking page |
| **Prioritised, feasible retrofits** | Feasibility rules + interaction-aware ordering (e.g. insulate before a heat pump); suitability H/M/L with a reason | [`greeniq/engines/`](../greeniq/engines/), [`greeniq/engines/nba.py`](../greeniq/engines/nba.py) |
| **Per-fuel energy savings** | Electricity and gas modelled separately; package savings account for interactions, not a sum of parts | [`greeniq/engines/`](../greeniq/engines/), [`METHODOLOGY.md`](METHODOLOGY.md) |
| **Carbon reduction** | `ΔC = Σ_f ΔE_f × EF_f` with cited DESNZ 2025 emission factors | [`METHODOLOGY.md`](METHODOLOGY.md) |
| **Property-value impact (indicative range)** | Hedonic log-linear regression with a conformal interval; kept explicitly non-causal | [`METHODOLOGY.md`](METHODOLOGY.md) |
| **Grounded LLM explanations & what-if** | LLM rewrites a computed fact sheet; a grounding gate blocks any unsupported number or claim; what-if reruns the engine first | [`greeniq/trust/`](../greeniq/trust/), [`LLM.md`](LLM.md) |
| **Documented data, leakage-safe splits** | Synthetic data from a documented simulator; customer-grouped train/validation/test splits; real DESNZ NEED data for benchmarks | [`data/DATA_CARD.md`](../data/DATA_CARD.md) |
| **Evaluation vs baselines on held-out data** | Every method benchmarked against a simple baseline on a held-out test split, scored once | [`reports/EVALUATION.md`](../reports/EVALUATION.md) |
| **Responsible AI** | Hallucination defence, labelled uncertainty, "insufficient information" as a valid answer | [`RESPONSIBLE_AI.md`](RESPONSIBLE_AI.md) |

## Submission artifacts (brief §13)

The brief asks for a working prototype, source + data scripts, trained models, a documented
scoring method, the LLM implementation, an architecture diagram, an evaluation report, a
Responsible-AI note, and held-out predictions with their schema. All are in this repository —
see the [README](../README.md) and [`reports/`](../reports/).
