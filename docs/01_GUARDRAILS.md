# 01 · Guardrails & Safety

> **Binding.** These rules override any other instruction, habit, reference repo, or
> convenience. If something here conflicts with anything else, this document wins.
> They are deliberately few, and each one exists to protect the score, the demo, or the
> truthfulness of our numbers.

---

## G1 · Scope: one problem, one product

- The **only** problem statement is **Lloyds PS2 — Green Home Score & Retrofit
  Recommendation Engine** ([`reference/LLOYDS-ps2.pdf`](reference/LLOYDS-ps2.pdf)).
  Requirements are decoded in [`02_PROBLEM_DECODED.md`](02_PROBLEM_DECODED.md).
- If something isn't needed to satisfy PS2, or to prepare a clean extension point for a
  later PS2 feature, **it is out of scope.**

## G2 · Reference code: borrow mechanisms, never domains

The team's earlier, unrelated projects have **already been distilled** into
[`10_MECHANISMS_HANDBOOK.md`](10_MECHANISMS_HANDBOOK.md), so use that, not the old repos.
Research will also turn up external open-source work. The rule is the same for all of it.

| ✅ Allowed | ⛔ Forbidden |
|---|---|
| Studying how they are **structured** (layout, layering, API routing, UI wiring, test/eval harness shape) | Copying **domain logic, data models, prompts, features, or problem statements** from unrelated projects |
| Re-implementing a **mechanism** (e.g. a grounding gate, provider seams, provenance receipts) cleanly for the home-energy domain | Vendoring or importing an unrelated project as a dependency |
| Using a compatible-licence library **as a library**, credited | Using code whose licence is unclear, copyleft-incompatible, or unstated |
| Citing a paper/method/tool as the basis for a choice (in an ADR) | Presenting borrowed work as original, or leaving it uncredited |

**Compliance test:** every file in GreenIQ must make sense to someone who knows only
PS2. If a reviewer could ask *"why is contract/voice/retail code in a home-energy
product?"*, we've broken G2.

## G3 · The One Law: code computes, language explains

- **Every number** (score, sub-scores, savings, carbon, value) is produced by
  **deterministic code or a trained, evaluated model.** Never by the LLM.
- The LLM **only explains** computed outputs and **answers what-if questions after the
  engines have been rerun** for the new scenario.
- The LLM must **never calculate, estimate, extrapolate, round differently, or introduce
  a figure** that isn't in the computed facts.
- This is **enforced mechanically** (a grounding gate plus a deterministic fallback), not
  just through prompting. See [`07_TRUST_AND_EVALUATION.md`](07_TRUST_AND_EVALUATION.md).

## G4 · PS-mandated calculation contracts (not ours to change)

These come straight from PS2. Everything else about *how* the engines work is for the
build team to research and decide (and record in an ADR).

| Contract | What PS2 fixes |
|---|---|
| **Score** | `S = Σ wₖ·sₖ`, sub-scores 0–100. Weights: Energy efficiency **25%**, Consumption intensity (kWh/m²) **20%**, Insulation **15%**, Heating system **15%**, Windows & glazing **10%**, Renewables **10%**, Smart energy management **5%**. Round to nearest integer. |
| **Bands** | 80–100 Highly efficient · 65–79 Good · 50–64 Moderate · 30–49 Poor · 0–29 Very poor |
| **Sub-score rules** | Mappings documented; **a better state never gives a lower sub-score** (monotonic); efficiency ≈ recorded rating, intensity ≈ annualised metered kWh/m²; any input feeding two components must be justified. Show each component's contribution. |
| **Improvement potential** | `100 × (E_baseline − E_after) / E_baseline`, with E = grid electricity imported + gas consumed (kWh/yr), same accounting convention. Baseline 0 or unknown → reported as **unavailable**. |
| **Per-fuel** | Electricity and gas reported **separately** everywhere. A fuel increase is a **negative saving.** Solar reduces imports, not demand. Packages account for **interactions** (not a simple sum). |
| **Carbon** | `ΔC = Σ_f ΔE_f × EF_f`, f ∈ {electricity, gas}, with **documented emission factors (units + source + year)** kept in one place. |
| **Value** | A **range**, not a point. Consistent before/after baseline, holding other characteristics constant. **Indicative, not causal**, and labelled that way. |
| **Labels** | All savings, carbon and value outputs are **estimates, not guarantees**. |

## G5 · Truthfulness over impressiveness

- **"Insufficient information" is a correct answer.** With missing or conflicting inputs,
  an infeasible retrofit, or an unknown baseline, return an explicit, explained
  insufficiency state. **Never** fabricate, never silently default to zero.
- **Every number carries a receipt**: which inputs, which method/version, which source.
- No unsupported precision. Don't show 3 decimals on an estimate built on synthetic data.
- Never present an observed association (e.g. rating ↔ price) as proof of cause.

## G6 · Data rules

- **No real personal or confidential customer data.** Public data only, used within its
  licence; synthetic data is allowed and expected.
- **Property-level splits** (and customer-level, if customers own several properties or
  memory is used). A property must never appear in two splits.
- **No leakage:** no inputs that wouldn't exist at prediction time. The schema must keep
  the *current value estimate* separate from *historical sale prices*.
- **Annualise consistently;** missing months and fields are handled explicitly and
  documented, never treated as zero by default.
- **Synthetic labels must follow plausible, disclosed rules.** State plainly that
  agreeing with synthetic targets does not prove real-world accuracy.
- Document sources, licences, schema, assumptions and limitations (a data card).

## G7 · Engineering rules

- **One shared contract** (the domain schema) that every module reads and writes.
  Changing it is a deliberate, recorded decision.
- **Provider seams:** every "intelligent" step can be switched between a transparent
  **baseline** and an **advanced** implementation, and **always keeps a working
  fallback**.
- **A clean clone runs with no API keys and no model downloads** (baseline + template
  mode). Keys only add capability.
- **Benchmark before replacing:** an advanced provider becomes the default only if it
  beats the baseline on held-out data. Keep both.
- **Reproducible:** pinned dependencies, fixed seeds, one command to run, one command
  to evaluate.
- **Secrets** only through environment variables (`.env` never committed;
  `.env.example` provided).
- **Decisions are written down** as short ADRs in [`adr/`](adr/).

## G8 · Delivery discipline

- **Always keep a runnable product.** Build a thin end-to-end slice first, then
  deepen it. Never break the clean run to add a feature.
- **Before any submission or demo**, verify that a fresh checkout runs (see
  [`09_SUBMISSION_AND_DEMO.md`](09_SUBMISSION_AND_DEMO.md)).
- A smaller system that **runs, is honest, and is reproducible** beats a bigger one that
  isn't.

---

### The ten non-negotiables (one glance)
1. PS2 is the only scope. 2. Borrow mechanisms, never domains. 3. Code computes,
language explains. 4. PS-fixed weights, bands and formulas are untouchable. 5.
Electricity and gas stay separate. 6. Value = indicative range, non-causal. 7. A
grounding gate on every AI output. 8. Insufficient information is a valid answer.
9. Clean clone runs with no keys. 10. Keep it runnable; honest beats impressive.
