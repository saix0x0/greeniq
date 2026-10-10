# 03 · Architecture

> The **shape** of GreenIQ: layers, components, contracts, seams and boundaries. This
> fixes *structure and responsibilities*. **The concrete methods, stack, schemas, routes
> and screens are fixed in [`11_IMPLEMENTATION_SPEC.md`](11_IMPLEMENTATION_SPEC.md)**
> (decisions: [ADR-002](adr/ADR-002-base-product-decisions.md)).

![GreenIQ system at a glance](assets/greeniq-system.svg)

---

## 1. Design principles

| # | Principle | What it means in practice |
|---|---|---|
| P1 | **Deterministic core, language at the edge** | All numbers come from engines inside the core. Language models only exist past the trust boundary. |
| P2 | **One contract** | A single domain schema (HomeState → ComputedFacts) is how the modules talk to each other. No module reaches into another's internals. |
| P3 | **Seams everywhere intelligence lives** | Each engine sits behind an interface with a *baseline* and an *advanced* provider; config picks one; fallback is guaranteed. |
| P4 | **Receipts by default** | Every output carries provenance (inputs, method, version, source). Explainability is built in, not added afterwards. |
| P5 | **Recompute, don't imagine** | What-if = mutate the scenario → rerun the engines → explain the diff. |
| P6 | **Honest uncertainty** | Ranges, estimate labels and explicit insufficiency states are first-class outputs, not errors. |
| P7 | **Walking skeleton first** | Every layer exists end-to-end from the first hours; depth is added behind the seams later. |

---

## 2. Layered view

```mermaid
flowchart TB
    subgraph L0["① Data plane"]
        direction LR
        SRC[("Sources: synthetic + public")] --> ING["Ingest & validate"] --> DC["Data card + label rules"]
    end
    subgraph L1["② Feature layer"]
        direction LR
        ANN["Annualise per fuel"] ~~~ INT["Intensity vs peers"] ~~~ MISS["Missing & conflict detection"]
    end
    subgraph L2["③ Domain contract"]
        direction LR
        HS{{"HomeState"}} ~~~ SC{{"Scenario (what-if)"}}
    end
    subgraph L3["④ Deterministic core: every number is made here"]
        direction LR
        SCORE["Score"] ~~~ FLAG["Flag & rank"] ~~~ RETRO["Retrofit plan"] ~~~ ENERGY["Energy per fuel"] ~~~ CARBON["Carbon"] ~~~ VALUE["Value range"]
    end
    subgraph L4["⑤ Facts"]
        direction LR
        CF{{"ComputedFacts"}} ~~~ RC{{"Receipts"}}
    end
    subgraph L5["⑥ Trust & language: words only"]
        direction LR
        LLM["Explainer"] --> GATE{"Grounding gate"} -- rejected --> TPL["Template"]
    end
    subgraph L6["⑦ Interface"]
        direction LR
        API["API"] --> UI["Dashboard"]
    end

    L0 --> L1 --> L2 --> L3 --> L4 --> L5 --> L6
    L4 == "numbers go direct" ==> L6

    classDef core fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    classDef contract fill:#10264a,stroke:#60a5fa,color:#eff6ff;
    classDef trust fill:#3d2f0a,stroke:#fbbf24,color:#fffbeb;
    classDef lang fill:#2a1b4a,stroke:#a78bfa,color:#f5f3ff;
    classDef iface fill:#0b2f3a,stroke:#22d3ee,color:#ecfeff;
    class SCORE,FLAG,ENERGY,RETRO,CARBON,VALUE core;
    class HS,SC,CF,RC contract;
    class GATE,TPL trust;
    class LLM lang;
    class API,UI iface;
```

**Reading the diagram:** layers stack top to bottom. Everything in ④ is deterministic or
an evaluated model. Everything in ⑥ is language, and nothing there reaches ⑦ without
passing the gate. The numbers themselves go **straight** from facts to the interface
and never pass through the language model. The **what-if loop** (shown in the poster above
and in [Flow C](04_RUNTIME_FLOWS.md)) works like this: the UI changes a **Scenario**, the
engines **rerun**, and new facts exist *before* anything is explained.

### Engine dependency order (inside ④)

```mermaid
flowchart LR
    HS{{"HomeState"}} --> SCORE["Score + band<br/>+ contributions"]
    HS --> RETRO["Retrofit planner<br/>feasible · ordered · H/M/L"]
    HS --> ENERGY["Energy per fuel<br/>baseline vs after"]
    RETRO --> ENERGY
    ENERGY --> CARBON["Carbon ΔC<br/>per fuel"]
    ENERGY --> FLAG["Flag + improvement<br/>potential"]
    SCORE --> FLAG
    RETRO --> VALUE["Value range<br/>before vs after"]
    SCORE --> CF{{"ComputedFacts<br/>+ receipts"}}
    FLAG --> CF
    CARBON --> CF
    VALUE --> CF
    RETRO --> CF
    classDef core fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    classDef contract fill:#10264a,stroke:#60a5fa,color:#eff6ff;
    class SCORE,FLAG,ENERGY,RETRO,CARBON,VALUE core;
    class HS,CF contract;
```

---

## 3. Component responsibilities

Each component has a contract (what it takes in and gives back) and two levels of
implementation. **Baseline** = transparent, documented, ships in the base product (exact
methods in `11`). **Advanced** = what may justify itself later, behind the same interface.

| Component | Responsibility | Consumes → Produces | Baseline (base product) | Advanced (later, if it beats baseline) | Reqs |
|---|---|---|---|---|---|
| **Ingest & validate** | Load sources, validate the schema, flag conflicts | raw tables → validated records | schema validation + rule checks | richer conflict resolution, real-data loaders | DR-1..7 |
| **Feature layer** | Annualise per fuel, compute intensity, benchmark vs peers, flag missingness | records → HomeState | documented annualisation + peer-group benchmark | learned imputation with uncertainty | DR-5, FR-2 |
| **Score engine** | 7 sub-scores → weighted score → band → contributions | HomeState → score facts | documented monotonic mappings | calibrated mappings (still monotonic) | FR-1 |
| **Efficiency flag & rank** | Flag Poor/Very poor, key issues, improvement potential | HomeState + energy facts → flags, rank | rules over sub-scores + the PS formula | learned issue detection | FR-2 |
| **Energy engine** | Per-fuel baseline and post-scenario kWh/yr | HomeState + Scenario → per-fuel energy | transparent physics-lite / catalogue model with an interaction rule | ML regressors per fuel (benchmarked) | FR-2, FR-4 |
| **Retrofit planner** | Feasibility filter → interaction-aware ordering → suitability | HomeState (+ memory) → ranked plan | applicability rules + dependency ordering | learned relevance ranking | FR-3, FR-9 |
| **Carbon engine** | ΔE per fuel × cited factor | energy facts → carbon facts | pure formula + factor config | — (stays deterministic) | FR-5 |
| **Value engine** | Before/after value **range** | HomeState + Scenario → value range | documented rating-premium band | regression with intervals on market data | FR-6 |
| **Facts assembler** | Merge outputs + receipts + insufficiency states | all engine outputs → ComputedFacts | always | — | all |
| **Grounding gate** | Verify every number/claim in AI text against the facts | text + facts → pass / reject | always | richer claim checks | FR-7, ER-4 |
| **Explainer / narrator** | Explain facts; narrate what-if diffs | facts (+ diff) → text | deterministic templates | LLM behind the gate | FR-7 |
| **Memory** *(optional)* | Persist constraints, completed retrofits, responses | events → memory → planner inputs | simple store, constraint filters | preference learning | FR-9 |
| **API** | Stable endpoints for every output and what-if | requests → facts / explanations | always | — | FR-8 |
| **Dashboard** | Show the answer, the why, the plan, the what-if | API → UI | always | richer visuals | FR-8 |

---

## 4. The domain contract

The schema is the team contract. Fields are listed **conceptually**; the build team names
them precisely.

```mermaid
classDiagram
    direction LR
    class HomeState {
        identity and ownership
        physical characteristics
        fabric and systems
        renewables and controls
        energy usage per fuel per period
        derived features
        data quality flags
        memory reference
    }
    class Scenario {
        base home reference
        retrofit set
        input overrides
    }
    class ComputedFacts {
        score and band
        sub-scores and contributions
        issues and improvement potential
        ranked feasible retrofits
        per-fuel energy baseline after delta
        carbon breakdown
        value range
        insufficiency states
    }
    class Receipt {
        output reference
        inputs used
        method and version
        source and citation
    }
    class Explanation {
        text
        grounded flag
        fallback flag
        facts cited
    }
    class Memory {
        completed retrofits
        stated constraints
        past responses
    }
    HomeState --> ComputedFacts : engines compute
    Scenario --> ComputedFacts : engines recompute
    ComputedFacts "1" o-- "many" Receipt : every number has one
    ComputedFacts --> Explanation : gated language
    Memory --> HomeState : adapts planning
```

**Contract rules:** facts are **immutable per computation** (a what-if produces a *new*
facts object, which is diffed against the old one); every numeric field has a receipt;
"unknown" is a value, not a missing key; current value estimate ≠ historical sale price.

---

## 5. The provider-seam pattern

Every intelligent step uses the same pattern, so advanced work never destabilises the
base product.

```mermaid
flowchart LR
    REQ["Engine call"] --> SEL{"Config<br/>selects provider"}
    SEL -->|baseline| B["Baseline provider<br/>transparent rules"]
    SEL -->|advanced| A["Advanced provider<br/>model / service"]
    A -->|unavailable or error| B
    B --> OUT["Output + receipt<br/>names the provider used"]
    A --> OUT
    subgraph BENCH["Promotion gate (offline)"]
        H["Held-out eval"] --> CMP{"Beats baseline?"}
        CMP -->|yes| PROMOTE["May become default"]
        CMP -->|no| KEEP["Stays optional"]
    end
    classDef base fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    classDef adv fill:#10264a,stroke:#60a5fa,color:#eff6ff;
    class B base;
    class A adv;
```

Seams to expose (minimum): **score mapping · energy · retrofit ranking · value ·
narrator · memory.** Each receipt records **which provider produced the number**, so
the UI can show it (observability that judges can see).

---

## 6. The trust boundary

```mermaid
flowchart TB
    subgraph NUM["NUMBERS ARE COMPUTED HERE"]
        E["Engines"] --> F["ComputedFacts"]
    end
    subgraph WORDS["WORDS ARE GENERATED HERE"]
        L["Language model"]
    end
    F -->|facts only, read-only| L
    L -->|draft text| G{"Grounding gate"}
    F -->|reference set| G
    G -->|every number & claim found in facts| OK["Deliver"]
    G -->|anything not found| FB["Template from facts"] --> OK
    L -.->|cannot write| F
    classDef num fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    classDef words fill:#2a1b4a,stroke:#a78bfa,color:#f5f3ff;
    classDef gate fill:#3d2f0a,stroke:#fbbf24,color:#fffbeb;
    class E,F num;
    class L words;
    class G,FB gate;
```

Information flows **one way**: facts → language. The language layer has **no write
path** into facts, engines or scores.

---

## 7. Mechanisms worth borrowing (from prior work and research)

The team's earlier projects proved out these mechanisms. Re-implement them **for this
domain** (Guardrail G2). **Full detail, sketches, gotchas and tests are in
[`10_MECHANISMS_HANDBOOK.md`](10_MECHANISMS_HANDBOOK.md).** It's already distilled, so
don't re-derive it.

| Mechanism | Why it matters here |
|---|---|
| **Grounding gate + template fallback** | Hits ER-4 (≥90% grounded, <5% unsupported) by construction, not by hoping |
| **Shared schema as team contract** | Parallel work without integration chaos |
| **Provider seams with guaranteed fallback** | Base product stays green while advanced work happens |
| **Per-output receipts / provenance** | "Show why it got this score" (FR-1) and explainability scoring |
| **Decision layer** (score → band → review/insufficiency queue) | Honest handling of missing/conflicting data (ER-5) |
| **Peer-baseline / percentile lane** | Fair intensity scoring ("big house ≠ inefficient") and "compare to similar homes" |
| **Benchmark-before-replace + honest eval harness** | ML quality (20%) is judged on held-out evidence vs baselines |
| **Orchestrator + pluggable modules** | Clean pipeline coordination; easy to add memory and new engines |
| **"Which model produced this" observability** | Makes the deterministic discipline *visible* in the demo |
| **Completeness / missing-field detection** | DR-5 and the "insufficient information" scenarios |

---

## 8. Quality attributes (what "good" looks like)

| Attribute | Target behaviour |
|---|---|
| **Correctness** | PS formulas exact; monotonicity provable by test; per-fuel signs right (e.g. a heating change can raise electricity) |
| **Explainability** | Any number → its receipt in one click |
| **Groundedness** | ≥90% grounded, ≥90% factually accurate, <5% unsupported (ER-4) |
| **Responsiveness** | Deterministic outputs and what-if recompute feel instant; language explanation is incremental, and template text appears immediately while it loads |
| **Resilience** | No key, no model, no network → still fully usable (baseline + template) |
| **Reproducibility** | One command to run, one command to evaluate, same numbers every time |
| **Cost** | Language calls are small (facts-only context), cacheable, and optional |
| **Extensibility** | A new engine/provider/feature plugs in without touching the core contract |
