# GreenIQ: Build Journal & Current State

> **This is the living document for the v1 build.** It is updated and pushed to the
> `beautiful` branch at the end of every phase (and whenever something important
> changes), so the team can follow the build as it happens. If you read one file, read
> this one. Newest log entries are at the bottom of §7.

**Branch:** `beautiful` · **Started:** 2026-10-10 · **Builder:** Claude Code (Opus 5.5), working with Suryansh

---

## 1. Status board

| Phase | What it delivers | Status |
|---|---|---|
| **0** Audit & plan | Requirement matrix, architecture, decisions, risk register (this doc) | ✅ done |
| **1** Contract + Green Home Score | Domain schema; 7 monotonic sub-scores; PS weights; bands; receipts; tests | ✅ done (36 tests green) |
| **2** Data | Synthetic "world" simulator, monthly per-fuel meter data, sales, retrofit history, validation, customer-grouped splits, data card, golden fixtures | ✅ done (48 tests green) |
| **3** Engines | Per-fuel energy, retrofit feasibility + sequencing, interactions, carbon, rating change, conflicts, receipts | ✅ done (74 tests green) |
| **4** ML + evaluation | Energy models vs baselines, savings calibration, value model + ranges, ranking eval, held-out predictions, report | 🔄 next |
| **5** API + persistence + memory | FastAPI, SQLite, scenarios, customer memory | ⬜ |
| **6** Dashboard | One-port web app: score, fingerprint, plan, scenario lab, roadmap, portfolio, receipts | ⬜ |
| **7** Grounded AI | Template narrator, grounding gate, Claude behind the gate, what-if assistant, groundedness eval | ⬜ |
| **8** Hardening | End-to-end tests, adversarial inputs, fresh-clone run | ⬜ |
| **9** Delivery | README, methodology, Responsible AI, architecture, BUILD_REPORT | ⬜ |

### How to run (verified commands only; grows each phase)

```bash
uv sync                      # create .venv with pinned dependencies (uv.lock)
uv run greeniq generate      # rebuild data/ from the simulator (seed 42, ~6 s)
uv run greeniq analyse P00007   # score, plan and package for one home (add --json for everything)
uv run pytest                # run the test suite
```

> Machine note: on a machine with ROS installed, `PYTHONPATH` leaks ROS pytest plugins
> into the venv. Prefix commands with `env -u PYTHONPATH` there. Judges' machines
> won't need this.

---

## 2. Phase 0 audit: what exists today

| Item | Finding |
|---|---|
| `main` | Architecture & build pack only (docs 01–10, ADR-001, PS2 PDF, system SVG). **No application code, no data, no tests.** |
| `atharva` | One commit that replaces the README with `# Absolut / hello`. Nothing to merge. |
| `beautiful` | Created from `main`. All v1 work lands here. |
| Problem statement | `docs/reference/LLOYDS-ps2.pdf` (same content as the condensed 15-slide briefing). It is the source of truth. |
| Machine | Python 3.12 via `uv`; Node 18 but **no npm**. This drives the frontend decision (ADR-002). |

**What we keep:** the whole pack. Its rules (docs/01), requirement IDs (docs/02), architecture
(docs/03), flows (docs/04) and mechanisms (docs/10) are good, and they agree with the
team's pasted plans. **We build on it rather than restart.**

**Where the pasted plans and the pack disagree, and what v1 does:**

| Topic | Pasted plan said | Pack said | v1 decision |
|---|---|---|---|
| Frontend | React + Vite + Tailwind + Recharts | "choose a stack for a one-command starter" | **No-build web app** (HTML + modern JS + SVG charts) served by FastAPI on one port. A fresh clone needs only Python. See ADR-002. |
| Sessions | 3 separate Claude sessions with approval stops | one build session, keep it runnable | One continuous build, phase by phase, **each phase committed and pushed with this journal updated**, so you can stop me at any point. |
| ML | "XGBoost/LightGBM" | "evidence over sophistication" | scikit-learn gradient boosting (no extra native deps), always benchmarked against a simple baseline. |
| Weights | fixed | fixed | Fixed: 25/20/15/15/10/10/5, unit-tested. |

---

## 3. Requirement → implementation matrix

Every PS2 requirement (IDs from [docs/02](02_PROBLEM_DECODED.md)) and where it will live.
The **Status** column is updated as phases land.

| ID | Requirement | Where it is implemented | Proof (test / artifact) | Status |
|---|---|---|---|---|
| FR-1 | Green Home Score, 7 fixed weights, monotonic sub-scores, bands, contributions | `greeniq/score.py`, `greeniq/config/score_mappings.py` | `tests/test_score.py` (weights, bands, half-up rounding, property-based monotonicity) | ✅ engine done; wired into the pipeline in Phase 3 |
| FR-2 | Flag Poor/Very poor, key issues, rank by improvement potential, per fuel, fair to big homes | `greeniq/score.py` (flag + issues), `greeniq/pipeline.py` (potential); portfolio ranking in Phase 4 | zero/estimated baseline → unavailable tests; large-home fixture not poor | 🔄 potential done; ranking in Phase 4 |
| FR-3 | Feasible retrofits only, H/M/L, reasons, interaction order | `greeniq/engines/retrofit.py`, `greeniq/config/retrofit_catalogue.json` | fixture feasibility tests, refused scenario test, fabric-before-heat-pump test | ✅ |
| FR-4 | Per retrofit and per package savings, elec and gas separate, negative savings, not a sum | `greeniq/engines/energy.py`, `greeniq/pipeline.py` | heat-pump test (elec ↑, gas ↓), package ≠ sum, insulate-first beats heat-pump-first, solar cuts imports not demand | ✅ (calibration in Phase 4) |
| FR-5 | ΔC = ΣΔE_f × EF_f with documented factors | `greeniq/engines/carbon.py`, `greeniq/config/emission_factors.json` | per-fuel/sign tests; carbon recomputes from displayed kWh | ✅ |
| FR-6 | Value impact as an indicative, non-causal range | `greeniq/engines/value.py`, `greeniq/ml/value_model.py` | range tests, coverage in eval | ⬜ |
| FR-7 | LLM explains computed facts only; what-if reruns engines first | `greeniq/trust/` (gate, narrator, assistant) | gate rejects invented numbers; what-if recompute test | ⬜ |
| FR-8 | Customer dashboard | `greeniq/web/` served by `greeniq/api.py` | E2E smoke test | ⬜ |
| FR-9 | Customer memory (optional) | `greeniq/memory.py` | "plan changes as memory builds" test | ⬜ |
| DR-1..7 | Data: synthetic/public, entities, grouped splits, no leakage, annualisation, data card, factors | `greeniq/simulator/`, `greeniq/data.py`, `greeniq/features/annualise.py`, [`data/DATA_CARD.md`](../data/DATA_CARD.md) | `tests/test_data.py` (determinism, split disjointness, no zero-fill, architecture guard) | ✅ (DR-7 factors land in Phase 3) |
| ER-1..5 | Splits, baselines, reproducibility, LLM targets, scenario tests | `greeniq/evaluation/`, `reports/` | `greeniq evaluate` regenerates `reports/EVALUATION.md` | ⬜ |
| SR-A..I | Nine submission artifacts | see §6 | checklist | ⬜ |

---

## 4. The v1 design in one page

### 4.1 The one law (unchanged from the pack)
**Code computes every number. The language model only explains. Every number carries a receipt.**

### 4.2 Pipeline

```mermaid
flowchart LR
    W["Synthetic world simulator<br/>(hidden truth, disclosed rules)"] --> D["data/*.csv<br/>properties · monthly meters · sales · retrofit history"]
    D --> V["Validate + customer-grouped splits"]
    V --> F["Features<br/>degree-day annualisation · end-use split · completeness · conflicts"]
    F --> S["Green Home Score<br/>7 sub-scores × PS weights"]
    F --> R["Retrofit planner<br/>feasible → staged → H/M/L"]
    R --> E["Per-fuel energy engine<br/>sequential, interaction-aware"]
    E --> C["Carbon ΔC per fuel"]
    E --> RT["Rating change (SAP-style)"]
    RT --> VAL["Value range (hedonic premium × level model)"]
    S & E & C & VAL --> FACTS["ComputedFacts + receipts"]
    FACTS --> UI["Dashboard"]
    FACTS --> G["Narrator → grounding gate → template fallback"]
    G --> UI
    ML["ML models (trained, evaluated)<br/>energy baseline · savings calibration · value"] -.-> E
    ML -.-> VAL
```

### 4.3 Where ML is used, and why (not ML for its own sake)

| Model | Task | Why it is needed | Simple baseline it must beat |
|---|---|---|---|
| **Per-fuel energy model** (gradient boosting, one per fuel) | Predict annual electricity and gas from property characteristics | Homes with too little metered data still need a labelled *estimated* baseline; it also gives "expected use for a home like yours", which exposes performance gaps and data conflicts | Peer-group median intensity × floor area |
| **Savings realisation calibration** | Learn how much of the engineering-estimated saving homes actually realise, per measure, from historical before/after retrofits | Real retrofits under-deliver (performance gap, comfort-taking); this is how EM&V practice corrects estimates | Uncalibrated engineering estimate, and PS2's flat illustrative % |
| **Value model** (level) + **hedonic EPC premium** (uplift) | Current value, and the indicative uplift range from a rating change | PS2 asks for a range holding other characteristics constant; hedonic premiums with bootstrap intervals give exactly that, with honest uncertainty | Regional median £/m² × floor area |
| **Ranking evaluation** | Check our improvement-potential ranking against the simulator's counterfactual truth | Shows we rank by *potential*, not by house size | Rank by total kWh (the "big house" trap) and by EPC band |

### 4.4 Our own features (the creative layer), all powered by the same engines
1. **Home Energy Fingerprint:** a seven-petal visual of the score; each petal's length is the sub-score and its width is the weight. Click a petal to open its receipt.
2. **Retrofit Scenario Lab:** compare "fabric first", "solar first", "whole home" and "best for £X" side by side: score, electricity, gas, carbon, value range, uncertainty.
3. **Exhaustive package optimiser:** with at most 7 measures there are at most 128 packages, so we evaluate every feasible one with the real engine. "Best under budget" is a true optimum over that set, not a heuristic.
4. **Staged roadmap:** now → next → later, with dependencies (insulate before a heat pump; size solar after the heat pump).
5. **Impact receipts and a printable report:** every number links to inputs, method, version and source.
6. **Visible grounding gate:** each explanation shows "grounded ✓" or "template"; a demo button shows the gate rejecting an invented number.
7. **Customer memory:** "already did the loft", "budget £8k", "no heat pump" change the plan, and the app shows what changed and why.
8. **Portfolio view for the bank:** poor homes ranked by improvement potential, with a fairness check showing big homes are not penalised for size.

---

## 5. Risk register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Synthetic labels make ML look better than it is | Judges penalise overclaiming | The simulator is a separate module with hidden variables the engines never see; every metric is labelled "synthetic"; the report says agreement ≠ real-world accuracy |
| R2 | Engine and simulator share formulas, so evaluation is circular | Invalid evaluation | Different functional forms; the simulator has occupant behaviour, performance gaps and rebound the engine does not model; savings are evaluated against *observed* before/after meter data |
| R3 | Emission factors wrong or unsourced | FR-5/DR-7 failure | One config file with source, year, unit and verification note; DESNZ 2025 values |
| R4 | LLM key unavailable at demo | GenAI demo fails | Template narrator is the default; the LLM is optional, behind the gate |
| R5 | Frontend needs a Node toolchain judges lack | Clean-clone failure | No-build frontend served by the API |
| R6 | Missing months treated as zero | DR-5 failure | Degree-day regression annualisation with explicit coverage rules; insufficient → "unavailable" or "estimated (model)" |
| R7 | Score reads "fine" when data is missing | False clearance (handbook L2) | Provisional/insufficient score states; completeness checklist |
| R8 | Value uplift read as a promise | FR-6 failure | Range only; mandatory non-causal caption; the gate rejects causal wording |
| R9 | Time | Incomplete v1 | Strict phase order, thin end-to-end first; every phase leaves the product runnable |

---

## 6. Submission checklist (PS2 §13)

| ID | Artifact | Location (planned) | Status |
|---|---|---|---|
| A | Working prototype | `greeniq serve` → http://localhost:8000 | ⬜ |
| B | Source + data generation scripts + run instructions | `greeniq/`, `greeniq generate`, README | ⬜ |
| C | Trained models + inference code | `models/`, `greeniq/ml/` | ⬜ |
| D | Sub-score mappings | [`docs/SCORING_METHOD.md`](SCORING_METHOD.md) | ✅ |
| E | LLM prompts, model details, evaluation approach | `docs/LLM.md`, `greeniq/trust/prompts.py` | ⬜ |
| F | Architecture diagram | `docs/ARCHITECTURE.md` + `docs/03` | ⬜ |
| G | Evaluation report | `reports/EVALUATION.md` (generated) | ⬜ |
| H | Responsible AI note | `docs/RESPONSIBLE_AI.md` | ⬜ |
| I | Held-out test predictions + schema | `reports/test_predictions.csv` + `data/DATA_CARD.md` | ⬜ |

---

## 7. Build log

### 2026-10-10 · Phase 0: audit and plan
- Read the PS2 brief (all 15 slides), the whole pack (docs 01–10, ADR-001) and both branches.
- Verified external anchors before building on them:
  - **Natural gas EF 2025:** 0.18296 kg CO₂e/kWh (gross CV), DESNZ 2025 flat file (via Climatiq mirror).
  - **UK electricity EF 2025:** DESNZ's 2025 "major changes" document states a 15% cut vs 2024 (0.20705 → ≈0.177 kg CO₂e/kWh). Recorded as *derived; confirm against the workbook*.
  - **SAP 2012 rating:** ECF = 0.42 × cost / (TFA + 45); SAP = 117 − 121·log₁₀(ECF) if ECF ≥ 3.5, else 100 − 13.95·ECF (BRE via Ofgem ECO paper). Used only to *simulate* plausible ratings and estimate rating changes, not as an accredited SAP calculation.
  - **Typical consumption:** Ofgem TDCV 11,500 kWh gas / 2,700 kWh electricity (used to sanity-check the simulator).
  - **Retrofit costs:** secondary sources citing EST/RICS/MCS (ASHP ≈ £13–14k before the £7,500 BUS grant; 3.5–4 kWp PV ≈ £5.5–8k; loft ≈ £0.8–0.9k; cavity ≈ £2.7k for a semi). Shipped as *indicative ranges with sources and dates*.
  - **Heat pump efficiency:** BUS minimum SCOP 2.8; monitored real-world fleets report higher. The engine uses 2.6–3.4 depending on how well insulated the home is.
  - **Value premium evidence:** Fuerst et al. (DECC 2013; 2015 paper): EPC A/B ≈ +5%, C ≈ +1.8% vs D, all else equal. The simulator plants premiums of this order; the report states the model can only recover what was planted.
- Set up the Python project with `uv` (pinned `uv.lock`).
- **Next:** Phase 1, the domain contract and the Green Home Score engine.

### 2026-10-10 · Phase 1: domain contract and Green Home Score
- **Contract** (`greeniq/contract.py`): strict input validation (impossible values → 422-style errors; e.g. negative floor area, SAP 500, `flat_position` on a house, duplicate meter months). Missing values are *not* errors.
- **Basis tags** on every input: observed · derived · assumed (age-band default) · estimated (model) · not applicable · missing. The UI will show these next to numbers.
- **Score engine** (`greeniq/score.py`): PS2 weights, half-up rounding, five bands, contributions and "points available" per component, issues ranked by points available, a receipt on every component.
- **Missing data, without guessing:** `complete` / `provisional` (defaults or estimates used) / `partial` (a component can't be valued → we report the **range** the score could take, and a band only if the range sits in one band).
- **Fairness:** a mid-floor flat isn't penalised for having no loft; intensity is per m², so size alone never lowers the score (both tested).
- **Bug caught by property-based testing:** Hypothesis found that a 21-year-old non-condensing boiler (30 − 10.2 age penalty) scored *below* direct electric (20), the rung beneath it. Fixed by setting direct electric to 15 so ladder rungs can't overlap, plus a dedicated regression test.
- **Tests:** `uv run pytest` → **36 passed** (weights, bands, rounding, monotonicity of every mapping, whole-score monotonicity over 300 generated homes, missing-data states, fairness, contract validation).
- **Docs:** [`docs/SCORING_METHOD.md`](SCORING_METHOD.md) (submission artifact D).
- **Next:** Phase 2, the synthetic world simulator and data pipeline.

### 2026-10-10 · Phase 2: synthetic world and data pipeline
- **Simulator** (`greeniq/simulator/world.py`): physics-lite heat loss + people + weather + installers + market, observed through imperfect records, monthly meters and sales. It holds **hidden truth the engines never see** (behaviour, under-heating of leaky homes, installation quality, heat-pump SCOP spread, smart-thermostat effect, location premium), so evaluation is not circular.
- **Calibration vs public anchors:** median gas 12,120 kWh (Ofgem TDCV 11,500), median electricity 2,757 kWh for gas homes (TDCV 2,700), median SAP 66 (band D).
- **Dataset** (`uv run greeniq generate`, 5.4 s): 3,000 homes · 2,372 customers (436 own several homes) · 183,146 monthly reads · 2,774 sales · 498 historical retrofits with before/after meter data · deliberate imperfections (12% no EPC, 487 stale EPCs, 24 wrong heating records, 4% missing reads, new customers, 27 void homes).
- **Validation:** every record passes through the contract; 0 schema errors, 0 duplicates, 0 orphans.
- **Splits by customer** (hash of customer ID): train 2,146 · validation 453 · test 401 homes; disjointness tested.
- **Annualisation** (`greeniq/features/annualise.py`): degree-day regression (PRISM), weather-normalised, splits baseload from heating, **never zero-fills** a missing month (tested: removing 3 months changes the annual figure by under 2%; a zero-fill would have under-counted). Explicit states: full · partial · insufficient · zero · no data · not applicable.
- **Golden fixtures** (`tests/fixtures/sample_properties.json`): 7 edge-case homes (PS-style poor semi, heat-pump candidate, mid-floor flat, missing data, large efficient detached, void/zero, conflicting records), each with documented expected behaviour.
- **Architecture guard:** a test fails if any product module imports the simulator or the hidden truth.
- **Tests:** 48 passed. **Docs:** [`data/DATA_CARD.md`](../data/DATA_CARD.md).
- **Next:** Phase 3, the deterministic engines (per-fuel energy, retrofit planner, carbon, rating change, conflicts) and the `analyse_home` pipeline.

### 2026-10-10 · Phase 3: deterministic engines and the `analyse_home` pipeline
- **Energy engine** (`engines/energy.py`, `engines/physics.py`): decomposes the *metered* baseline into end uses (reproduced to ±10 kWh), then applies measures **in sequence to one evolving state**. Results per fuel, standalone and in-package, with the interaction reported explicitly.
  - Heat pump: gas −11,390 / electricity **+3,610** kWh standalone for the heat-pump candidate (negative electricity saving), and carbon still falls.
  - Poor semi: package 22,170 kWh vs a sum of standalone savings of 31,250 → **interaction −9,080 kWh**.
  - **Order matters where it physically should:** heat-pump SCOP is fixed at installation, so insulating first beats heat-pump-first (tested).
  - Solar cuts imports, not demand, and is worth more after a heat pump (tested).
- **Retrofit planner** (`engines/retrofit.py`): feasibility first; H/M/L with evidence and uncertainty; every non-recommended measure has a status and a reason; fabric → controls → heat pump → solar.
- **Carbon** (`engines/carbon.py`): PS2 formula with DESNZ 2025 factors from config; computed from the displayed kWh, so anyone can recompute it from the screen.
- **Rating** (`engines/rating.py`): SAP-2012-style estimate for missing EPCs, stale-EPC adjustment, and rating after the package (recorded + modelled change).
- **Data quality** (`features/quality.py`): conflict detection (catches 22 of the 24 planted wrong heating records; flags 429 stale EPCs), confidence scoring, and ranked questions for missing inputs.
- **Customer-memory hooks:** declined measures are excluded with a reason; completed ones update inputs.
- **Robustness sweep:** all 3,000 homes analysed, **0 errors, 1.3 ms per home**.
- **Two fixes from the sweep:**
  1. A simulator bug derived the EPC band from the unrounded SAP (93 spurious mismatches → 0).
  2. Score mappings re-calibrated (v1.1) to a stated anchor (a typical UK home lands in Moderate). v1.0 had put 42% of homes in Poor/Very poor; now 33%. The scoring doc records the change and why.
- **CLI:** `uv run greeniq analyse <id>`.
- **Tests:** 74 passed (all seven fixtures' documented behaviours plus PS2's scenario tests).
- **Docs:** [`docs/METHODOLOGY.md`](METHODOLOGY.md), ADR-003 (simulated world), ADR-004 (energy method).
- **Next:** Phase 4, the ML models (energy baseline, savings calibration, value), portfolio ranking, and the evaluation harness with held-out predictions.

---

## 8. Product build (execution brief, phases P1–P5)

From here the build follows the locked execution brief: **build the product layer on the
existing engine, vertically.** Product phases P1–P5 map onto the journal's phases 5–8
(API → dashboard → Decision Lab → grounded AI → hardening). The engine is not rewritten.

| Product phase | Delivers | Status |
|---|---|---|
| **P1** Stabilise | verify engine, list UI gaps, merge `main` in | ✅ |
| **P2** Next Best Action | thin selector over ComputedFacts, 3 traced reasons | ✅ |
| **P3** API + core dashboard | FastAPI + one-port no-build web app; portfolio + property views | ✅ |
| **P4** Decision Lab | Choose Your Plan, dependency graph, Pareto, Sankey, interactions, sensitivity | ✅ |
| **P5** Grounded AI + E2E validation | narrator, grounding gate, template fallback, edge-case sweep | 🔄 next |

### 2026-10-10 · P1: stabilise — verification note
- **Tests:** `uv run pytest` → **88 passed** on `beautiful` before any change.
- **End to end:** `uv run greeniq analyse P00007` → score 48 (Poor), per-fuel plan (heat pump elec −2,290 / gas +7,820 kWh),
  package net +10,350 kWh/yr, +1.91 t CO₂e/yr, EPC D→C, value range. Works.
- **Machine note (macOS):** if `greeniq` says `No module named 'greeniq'`, the venv's `.pth` files got the macOS
  `hidden` flag (Python ≥3.11.14 skips hidden `.pth` files). Fix: `chflags nohidden .venv/lib/python3.11/site-packages/*.pth`.
- **What ComputedFacts already carries for the UI:** score + 7 weighted contributions + points available + issues,
  per-fuel baseline (with heating/baseload split and basis), plan with standalone **and** in-package impacts, excluded
  with reasons, conflicts, questions, confidence, package (interaction, score/EPC after, cost), value range, scenario.
- **UI gaps found (and where they get filled):**
  1. Next Best Action — missing → **P2** (done).
  2. Every feasible package (for Choose Your Plan / Pareto) — missing → P4 `engines/packages.py`, via `analyse_home` per subset.
  3. End-use breakdown (heating / hot water / appliances / PV) for the Sankey — computed inside `EnergyState`, not
     exposed → P4 adds it to the package result.
  4. Pairwise interactions per output (score, energy, carbon) — derivable from paired scenario runs → P4.
  5. Sensitivity (which assumed inputs flip the decision) — missing → P4, by re-running `analyse_home` on flipped inputs.
  6. Portfolio summary — `engines/ranking.py` exists; API aggregates it → P3.
- **Merge:** `main` merged into `beautiful` (teammates' `greenpath_home/`, `dataset.md`, docs 11–14, ADR-002 base-product
  decisions all kept). Only conflict: `.gitignore`, resolved as the union. 88 tests still green.
- **Noted, not changed:** `main`'s README mentions the DESNZ NEED sample as the data source; the engine on this branch
  uses the documented synthetic world (ADR-003). To reconcile in the delivery docs.

### 2026-10-10 · P2: Next Best Action
- `greeniq/engines/nba.py`: a **selector** over the finished `ComputedFacts`; it computes no energy, carbon or cost number.
  Exposed as `ComputedFacts.next_best_action` and printed by `greeniq analyse`.
- **Rule:** (a) blocked → get the missing fact first: high-severity conflict → survey; heating unknown → ask; no baseline
  at all → ask for readings; nothing feasible but survey-gated measures → survey. (b) otherwise rank feasible measures
  whose prerequisites are not pending (never a heat pump while its fabric measures are outstanding) by objective ×
  suitability (High 1.0 / Medium 0.7 / Low 0.4). (c) nothing above 25 kg CO₂e/yr, or zero metered use → no action.
- **Objectives:** `value_for_money` (default; kg CO₂e/yr per £1k of mid cost, **£1k cost floor** so a £250 thermostat
  can't win on a tiny denominator — without the floor it was picked for every home), `carbon`, `energy`.
  Passed as `constraints["objective"]`.
- **Exactly 3 reasons**, each with a `fact_ref` path into the facts (tested to resolve), e.g. `plan[1].standalone`,
  `score.issues[3]`, `plan[4].depends_on` ("do it before the heat pump").
- **Fixtures:** poor semi → loft; heat-pump candidate → cavity wall first; mid flat → glazing; conflict → survey;
  void → no action; large efficient → no action.
- **Sweep:** 3,000 homes, 0 errors, 1.8 ms/home; actions spread across loft 637, controls 684, cavity 568, heat pump 409
  (fabric already done), glazing 247, solid wall 137, solar 80, no action 159, ask 48, survey 31.
- **Tests:** 116 passed (28 new in `tests/test_nba.py`).
- **Next:** P3, the API and the core dashboard (vertical slice).

### 2026-10-10 · P3: API + core dashboard (the vertical slice)
- **Run:** `uv run python -m greeniq serve` → http://127.0.0.1:8000 (UI + API on one port). Verified from a **fresh
  clone with no API key**: health 200, UI 200. First start analyses all 3,000 homes (~10 s) and caches them in
  `var/greeniq.sqlite`, keyed by engine versions + model card + data fingerprint; later starts ~3 s.
  (`python -m greeniq` also sidesteps the macOS hidden-`.pth` issue noted in P1.)
- **Service** (`greeniq/service.py`): the only place facts come from; calls `analyse_home`; a what-if always reruns it.
- **API** (`greeniq/api.py`): `/api/health`, `/api/portfolio`, `/api/properties` (search, band/region/type/next-action
  filters, sort by potential/score), `/api/properties/{id}` (facts + explanation), `/next-best-action?objective=`,
  `POST /scenarios`, `/api/evidence`. Errors: one shape `{"error": {code, message}}` (404 unknown home, 422 bad measure or
  objective). An infeasible measure in a what-if is **rejected with its reason inside the facts**, not an HTTP error.
- **Engine output additions** (numbers the UI needed, computed by the engine, not the UI): `baseline_emissions_kg`
  (baseline kWh × DESNZ factors, labelled metered/estimated) and `package.components_after` (score contribution per
  component after the package, for the before/after decomposition overlay).
- **Template narrator** (`greeniq/trust/narrator.py`): plain-English home and package explanations; every sentence carries
  the fact paths it was built from (shown in Evidence mode). Explains the heat-pump trade-off and non-additivity.
- **UI** (`greeniq/web/`, no build step): sidebar Dashboard · Properties · Decision Lab · Analytics · Evidence, a persistent
  **Evidence/Demo** toggle and Settings (NBA objective, theme).
  - *Dashboard:* KPI strip (avg score 53.2, opportunity 25.6 GWh / 4,682 tCO₂e with the gas ▼ / electricity ▲ split,
    36.7% poor, 93% metered), band distribution (All / region / type / age), triage queue (All / Recommend / Refer)
    with each home's Next Best Action, portfolio goal (53.0 → 79.8 if packages installed), opportunity by region,
    quick actions.
  - *Property view:* KPIs (score + status + confidence, purchased energy per fuel with basis, carbon, value range),
    **score decomposition** (7 contributions vs points available, biggest-gap marker, outlined "after" overlay),
    recommendations rail (Recommend / Refer / Not suitable), NBA card with its 3 traced reasons, where the energy goes
    (heating vs baseload per fuel), **try a change** chips → engine rerun → per-fuel before/after, carbon, score, EPC and
    the explanation.
  - *Analytics / Evidence:* model-vs-baseline and ranking tables from `reports/metrics.json`; emission factors with
    sources, cost ranges, engine versions, model quality.
  - Every number comes from the API and carries an evidence tag (measured / metered / estimate / assumed / unavailable);
    in Evidence mode dotted numbers open their receipt.
- **Gate verified in the browser:** P02129 (Very poor, 27) → NBA loft insulation → try "air source heat pump" alone →
  electricity 2,630 → 20,120 kWh (▲), gas 61,630 → 210 (▼), −8.14 t CO₂e, score 27 → 49, **EPC E → F** (SAP is
  cost-based; a heat pump in an uninsulated home raises running cost — the "insulate first" lesson, from the engine).
- **Tests:** 124 passed (8 new in `tests/test_api.py`).
- **Next:** P4, the Decision Lab.

### 2026-10-10 · P4: Decision Lab (the centrepiece)
- **Engine** (`greeniq/lab.py`, `GET /api/properties/{id}/lab?budget=&objective=`): every non-empty subset of the
  home's feasible measures is run through `analyse_home` (≤127 runs; 0.07 s for a 6-measure home). Definitions in
  [`docs/METHODOLOGY.md` §8](METHODOLOGY.md).
  - **Choose Your Plan:** Lowest cost · Greenest · Best value · My budget, each with a written definition; only
    prerequisite-respecting packages; *best value* = kg CO₂e/yr per £1k (same £1k floor as the NBA).
  - **Pareto frontier** (cost vs carbon) over genuinely feasible packages; packages that skip a prerequisite are
    **shown as hollow points, not hidden** — some cut more carbon per £ (heat pump before insulating), and the UI says
    why the plans still follow fabric-first (more electricity, EPC can fall: P02129 heat pump alone → E → F).
  - **Interactions** per output (net kWh, kg CO₂e, score points) from paired runs on one baseline.
  - **Sensitivity**: assumed/missing inputs set to plausible alternatives + savings realisation ±20%; *fragile* when the
    NBA or the package changes; framed as "what to verify", not a confidence interval.
- **Engine output addition:** `baseline_flows` / `package.flows_after` — purchased electricity, gas and self-used solar
  by end use, for the Sankey. Grid flows reconcile with purchased electricity and gas flows with gas (tested).
- **Engine bug found by the heatmap and fixed (energy 1.1):** with savings realisation < 100%, the second fabric measure
  was judged against the *nominal* heat-loss cut of the first, so fabric pairs were super-additive (P02129 loft + solid
  wall: +1,530 kWh/yr). The engine now tracks the realised heat-loss coefficient; standalone figures are unchanged,
  fabric pairs are additive within rounding across 400 homes; regression test added. Evaluation regenerated:
  savings metrics unchanged, ranking Spearman 0.912 → 0.913, score band agreement 90.9% → 91.5%.
- **UI** (`#/lab/<id>`): NBA strip · Choose Your Plan cards ⇄ cost-vs-carbon scatter (click a point to select) ·
  dependency graph (click to add/remove; a red dashed arrow when a measure is chosen without its prerequisite) ·
  Sankey today vs selected on one scale · selected-package card (per-fuel before/after bars, carbon, score/EPC, cost,
  value range, narrator) · Detail: interaction heatmap (output selector) and sensitivity tornado.
- **Gate verified in the browser:** P02129 → Greenest: card and engine re-run agree (10.38 t/yr; electricity
  2,630 → 7,470 kWh ▲; gas 61,630 → 210 ▼; score 27 → 88; EPC E → C); Sankey after = 9,460 kWh (7,470 grid +
  210 gas + self-used solar). Lowest cost (loft): 2.20 t, 27 → 37. `tests/test_lab.py` checks the same consistency
  for every named plan.
- **Deferred on purpose:** benchmarking scatter / outlier residuals (design priority P2, after reference data is defensible).
- **Tests:** 134 passed (10 new in `tests/test_lab.py`).
- **Next:** P5 — grounded AI (narrator → grounding gate → template fallback) and the end-to-end edge-case validation.
