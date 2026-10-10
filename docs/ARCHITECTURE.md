# GreenIQ architecture, as built (submission artifact F)

> The design rationale is in [`03_ARCHITECTURE.md`](03_ARCHITECTURE.md). This page shows what the code
> actually does, with module paths.

```mermaid
flowchart TB
    subgraph DATA["① Data"]
        SIM["Simulator<br/>simulator/world.py"] --> RAW[("data/raw · truth · processed")]
        RAW --> DL["Load · validate · split by customer<br/>data.py"]
    end
    subgraph ENGINE["② Deterministic core: every number is made here"]
        RES["Resolve inputs + basis tags<br/>features/resolve.py"] --> ANN["Degree-day annualisation<br/>features/annualise.py"]
        ANN --> QC["Conflicts · completeness<br/>features/quality.py"]
        QC --> EN["Three-stage energy model<br/>need → efficiency → bought<br/>engines/energy.py · physics.py"]
        RES --> SC["Green Home Score<br/>score.py"]
        EN --> RT["Retrofit plan<br/>engines/retrofit.py"] --> PK["Package · potential · carbon · rating<br/>pipeline.py · carbon.py · rating.py"]
        PK --> NBA["Next Best Action<br/>engines/nba.py"]
    end
    subgraph ML["③ Evaluated models (promoted only if they beat a baseline)"]
        EM["Energy baseline per fuel"] ~~~ CAL["Savings calibration"] ~~~ VAL["Value level + EPC premium range"]
    end
    subgraph FACTS["④ One result record"]
        CF{{"ComputedFacts + receipts<br/>facts.py"}}
    end
    subgraph TRUST["⑤ Language (words only)"]
        TPL["Template narrator"] --> GATE{"Grounding gate<br/>trust/gate.py"}
        LLM["Optional Claude narrator<br/>trust/llm.py"] --> GATE
        ASK["What-if parser (rules)<br/>trust/assistant.py"]
    end
    subgraph APP["⑥ Product"]
        API["FastAPI · one port<br/>api.py · service.py"] --> UI["Dashboard · Property · Decision Lab · Analytics · Evidence<br/>web/"]
        LAB["Decision Lab: every feasible package<br/>lab.py"]
    end
    DL --> RES
    ML -.-> EN
    ML -.-> PK
    SC & PK & NBA --> CF
    CF --> TPL & LLM & GATE
    CF --> API
    ASK -->|scenario| ENGINE
    LAB -->|reruns| ENGINE
    GATE --> API
```

## The one rule, structurally
- Numbers flow **only** from ② (and the evaluated models in ③) into ④. The UI, the Next Best Action,
  the Decision Lab and the language layer all **read** `ComputedFacts`; none of them calculates.
- A what-if (typed question, picked measures, Decision Lab package) is a new `Scenario`. The engine
  reruns and produces a new `ComputedFacts`; only then is anything explained.
- The language layer has no write path into facts, and its output passes the gate or is replaced.

## Commands
| Command | What it does |
|---|---|
| `uv run greeniq generate` | regenerate `data/` from the seeded simulator |
| `uv run greeniq train` | fit models on train; tune and promote on validation → `models/` |
| `uv run greeniq evaluate` | score the held-out test split once → `reports/EVALUATION.md` |
| `uv run greeniq eval-grounding` | gate false-block and catch rates (and the LLM, if a key exists) → `reports/GROUNDING.md` |
| `uv run greeniq edge-sweep` | every PS2 scenario invariant over all homes → `reports/EDGE_CASES.md` |
| `uv run greeniq analyse P00007` | one home in the terminal |
| `uv run python -m greeniq serve` | API + dashboard at http://127.0.0.1:8000 |
| `uv run pytest` | test suite |
