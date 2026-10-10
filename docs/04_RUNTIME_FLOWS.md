# 04 · Runtime Flows

> How a request actually moves through the system. These sequences define the
> **behaviour** the base product must have. Participant names are roles, not file
> names. Exact routes and payloads: [`11_IMPLEMENTATION_SPEC.md`](11_IMPLEMENTATION_SPEC.md) §8–§9.

---

## Flow A — Analyse a home (the core answer)

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant UI as Dashboard
    participant API
    participant FE as Feature layer
    participant CORE as Deterministic core
    participant FA as Facts assembler

    C->>UI: Open my home
    UI->>API: request analysis(home)
    API->>FE: build HomeState
    FE-->>API: HomeState (+ data-quality flags)
    alt critical inputs missing or conflicting
        API-->>UI: insufficiency state + what's missing
    else enough information
        API->>CORE: score, flag, plan, energy, carbon, value
        Note over CORE: engines run in dependency order<br/>retrofit plan → per-fuel energy → carbon & value
        CORE-->>FA: outputs + receipts
        FA-->>API: ComputedFacts
        API-->>UI: facts (render immediately)
    end
    UI-->>C: Score, band, why, plan, savings, carbon, value
```

## Flow B — Explain (grounded language)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Dashboard
    participant API
    participant NAR as Narrator
    participant LLM as Language model
    participant GATE as Grounding gate

    UI->>API: explain(facts id, question?)
    API->>NAR: facts (read-only) + question
    NAR-->>UI: template explanation (instant)
    opt language model configured
        NAR->>LLM: facts-only prompt + question
        LLM-->>NAR: draft
        NAR->>GATE: draft + facts
        alt every number and claim found in facts
            GATE-->>NAR: pass
            NAR-->>UI: grounded explanation ✓
        else ungrounded number or claim
            GATE-->>NAR: reject (logged)
            NAR-->>UI: keep template explanation
        end
    end
```

## Flow C — What-if (recompute, then explain) — the signature interaction

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant UI as Dashboard
    participant API
    participant CORE as Deterministic core
    participant NAR as Narrator + gate

    C->>UI: "What if I add a heat pump and loft insulation?"
    UI->>API: what-if(home, Scenario)
    API->>API: validate scenario (feasible? conflicts?)
    alt infeasible retrofit or conflict
        API-->>UI: explain why not feasible (no numbers invented)
    else feasible
        API->>CORE: rerun engines on Scenario
        CORE-->>API: new ComputedFacts (+ receipts)
        API->>API: diff(old facts, new facts)
        API-->>UI: new facts + diff → gauge, charts, value animate
        API->>NAR: diff + both facts sets
        NAR-->>UI: grounded explanation of the change
    end
    Note over UI,NAR: The language layer only ever sees numbers<br/>that the engines already produced
```

## Flow D — Portfolio: find & rank poor homes

```mermaid
sequenceDiagram
    autonumber
    actor A as Advisor / Bank analyst
    participant UI as Dashboard
    participant API
    participant CORE as Deterministic core

    A->>UI: Show homes needing help
    UI->>API: flagged(filter)
    API->>CORE: classify all · compute improvement potential
    CORE-->>API: Poor/Very poor + key issues + potential (or "unavailable")
    API-->>UI: ranked list (intensity-fair, per-fuel changes shown)
    A->>UI: open a home → Flow A
```

## Flow E — Customer memory *(optional extension)*

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant UI as Dashboard
    participant API
    participant MEM as Memory
    participant CORE as Deterministic core

    C->>UI: "Already did loft · can't afford external wall insulation"
    UI->>API: remember(constraint, completed retrofit)
    API->>MEM: store event
    API->>CORE: recompute with updated HomeState + constraints
    CORE-->>API: new plan (done items removed, constraints respected)
    API-->>UI: plan diff: "what changed because of what you told us"
```

---

## The grounding gate (decision logic)

> **Implementation note:** the base product uses **structured, citation-bound
> verification** (`11` §8.3). Each LLM sentence carries `fact_ids`, and each number must
> match the display value of a fact that sentence cites. The diagram below shows the
> checks in order; "found in facts" means "found in the sentence's cited facts".

```mermaid
flowchart TD
    D["Draft explanation"] --> N["Extract numeric tokens<br/>(normalise £, %, commas, units)"]
    N --> Q1{"Every number<br/>found in facts?"}
    Q1 -- no --> R["Reject"]
    Q1 -- yes --> E["Extract referenced entities<br/>(components, retrofits, fuels, bands)"]
    E --> Q2{"Every entity<br/>found in facts?"}
    Q2 -- no --> R
    Q2 -- yes --> Q3{"Forbidden claims?<br/>(guarantees, causal value claims,<br/>new estimates)"}
    Q3 -- yes --> R
    Q3 -- no --> P["Pass → deliver, marked grounded"]
    R --> T["Deterministic template from facts"] --> L["Log rejection (feeds eval)"]
    classDef bad fill:#3f1d1d,stroke:#f87171,color:#fef2f2;
    classDef good fill:#0f3d2e,stroke:#34d399,color:#ecfdf5;
    class R,T bad;
    class P good;
```

## Explanation lifecycle

```mermaid
stateDiagram-v2
    [*] --> FactsReady
    FactsReady --> TemplateShown: always, instantly
    TemplateShown --> Drafting: language model available
    TemplateShown --> Done: no language model
    Drafting --> Verifying
    Verifying --> Grounded: passes gate
    Verifying --> Rejected: fails gate
    Grounded --> Done: replace template
    Rejected --> Done: keep template, log
    Done --> [*]
```

---

## Behaviour under the organisers' scenario tests (ER-5)

| Scenario | Required behaviour |
|---|---|
| Missing property fields | Score what can be scored; mark affected components; show an insufficiency state where a number would be a guess |
| Conflicting data (e.g. "heat pump" but very high gas use) | Flag the conflict, explain it, lower confidence; never silently pick one |
| Infeasible retrofit requested (e.g. loft insulation in a mid-floor flat) | Refuse with the reason; offer the feasible alternatives |
| Interacting retrofits | Package result ≠ sum of parts; explain the interaction |
| Electricity rises after a heating change | Shown as a **negative electricity saving** next to the gas saving; carbon nets both |
| Not enough data for savings/value | "Unavailable" with the reason, not a fabricated range |
