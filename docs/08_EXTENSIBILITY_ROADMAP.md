# 08 · Extensibility Roadmap

> The base product is a **platform**, not a demo. This page lists the extension points
> it must expose and the advanced features we expect to plug into them later, so
> nobody has to reopen the core to add them.

---

## 1. Three tiers

```mermaid
flowchart LR
    subgraph T1["Tier 1 · Base product (this build)"]
        direction TB
        s1["All PS2 outputs at a transparent baseline"]
        s2["Receipts · insufficiency states"]
        s3["Gate + template + LLM explain"]
        s4["What-if recompute loop"]
        s5["Eval harness + docs"]
    end
    subgraph T2["Tier 2 · Advanced (next)"]
        direction TB
        a1["ML energy per fuel (benchmarked)"]
        a2["Value model with intervals"]
        a3["Learned retrofit relevance"]
        a4["Customer memory, visible adaptation"]
        a5["Compare-to-similar homes"]
        a6["Package optimiser under budget"]
    end
    subgraph T3["Tier 3 · Product (later)"]
        direction TB
        p1["Real data integrations"]
        p2["Advisor / portfolio console"]
        p3["Finance & grant pathways"]
        p4["Report export · accessibility"]
    end
    T1 ==> T2 ==> T3
    classDef t1 fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    classDef t2 fill:#10264a,stroke:#60a5fa,color:#eff6ff;
    classDef t3 fill:#2a1b4a,stroke:#a78bfa,color:#f5f3ff;
    class s1,s2,s3,s4,s5 t1;
    class a1,a2,a3,a4,a5,a6 t2;
    class p1,p2,p3,p4 t3;
```

## 2. Extension points (the base product must expose these)

| Seam | Base-product provider (see `11`) | Plug-in later | Must not change |
|---|---|---|---|
| **Data source** | generator / file loader | real public datasets, partner feeds | the HomeState contract |
| **Score mapping** | documented rule tables | calibrated (still monotonic) mappings | PS weights, bands, monotonicity |
| **Energy** | transparent per-fuel model | ML regressors per fuel | per-fuel outputs + receipts |
| **Retrofit ranking** | applicability + ordering rules | learned relevance, cost-benefit | feasibility-first; H/M/L output |
| **Value** | rating-premium band | regression with intervals | range output; non-causal framing |
| **Narrator** | templates + `claude-opus-5-5` behind the citation-bound verifier | other models/vendors | the verifier; facts-only input |
| **Memory** | deferred (seam reserved) | customer memory with visible adaptation | engines still compute every number |
| **Optimiser** | — | best package under a budget/constraints | reuses the engines; no new maths in language |

## 3. Advanced feature backlog

| Feature | Why it wins points | Plugs into | Depends on |
|---|---|---|---|
| **Per-fuel ML energy models** | ML quality (20%) with held-out evidence | Energy seam | Splits, baseline, eval harness |
| **Value model with prediction intervals** | Savings/carbon/value (15%); honest ranges | Value seam | Sales history, eval |
| **Customer memory with "what changed and why"** | Innovation + optional extension, visible adaptation | Memory seam + planner | Contract memory field |
| **Compare-to-similar homes** | Insight + UX; fair benchmarking made visible | Feature layer peer groups | Benchmarks |
| **Budget-constrained package optimiser** | Business relevance; "best plan for £X" | Optimiser seam (calls engines) | Catalogue costs, interaction rule |
| **Gate visibility & adversarial demo** | GenAI (15%): proves grounding live | Narrator + UI | Gate logs |
| **Advisor / portfolio console** | Business relevance for a bank: find, rank and act on many homes | API + UI | Flow D |
| **Finance & grant pathway hints** | Business relevance (lender angle), presented as information not advice | Plan output + UI | Documented sources only |
| **Shareable home report** | UX; a takeaway for the customer | API + UI | Facts + receipts |
| **Accessibility & plain-language mode** | UX + responsible AI | Narrator + UI | Templates |

## 4. Prioritisation (value vs effort — a starting view, re-assess after research)

```mermaid
quadrantChart
    title Advanced features: impact vs effort
    x-axis Low effort --> High effort
    y-axis Lower judge impact --> Higher judge impact
    quadrant-1 Plan carefully
    quadrant-2 Do first
    quadrant-3 Fill-ins
    quadrant-4 Defer
    Gate demo: [0.2, 0.85]
    Compare to similar: [0.3, 0.6]
    Memory adaptation: [0.55, 0.72]
    ML energy per fuel: [0.6, 0.88]
    Value intervals: [0.5, 0.65]
    Package optimiser: [0.75, 0.6]
    Portfolio console: [0.65, 0.5]
    Home report: [0.35, 0.35]
    Finance hints: [0.45, 0.4]
```

## 5. How a new feature plugs in (without touching the core)

```mermaid
flowchart LR
    I["New capability"] --> Q{"New numbers?"}
    Q -- yes --> S["Implement as a provider<br/>behind an existing or new seam"]
    S --> R["Emit receipts + units"]
    R --> B["Benchmark vs baseline<br/>on held-out data"]
    B --> F["Extend ComputedFacts<br/>(additive, versioned)"]
    Q -- no, presentation only --> U["UI / narrator template"]
    F --> G["Gate automatically covers<br/>the new facts"]
    G --> U
    classDef ok fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    class S,R,B,F,G ok;
```

**Rule of thumb:** if a feature needs the language layer to produce a number, it is
designed wrong. Move the number into an engine.
