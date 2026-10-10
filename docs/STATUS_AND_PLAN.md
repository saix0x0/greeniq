# GreenIQ: status, what is real vs synthetic, and the plan to move to real data

> Written to be pasted into another assistant (or read by the team) without any other context.
> Last updated 2026-10-11. Branch `beautiful` (and `main`) on github.com/SHARMA-AtharvaIIIT/Absolut.

## 1. What GreenIQ is (one paragraph)

GreenIQ is our answer to Lloyds Megathon X, Problem Statement 2: a "Green Home Score and Retrofit
Recommendation Engine". For any home it calculates:
- a 0–100 Green Home Score from seven fixed-weight parts (25/20/15/15/10/10/5);
- whether the home is Poor or Very poor, and how much its purchased energy could fall
  (improvement potential = 100 × (E_before − E_after) / E_before);
- which retrofits are feasible, in what order, and with what suitability (High/Medium/Low);
- electricity and gas savings **separately** (a heat pump raises electricity while cutting gas);
- carbon (per fuel, government factors);
- an indicative, non-causal property-value range.

It then picks a single **Next Best Action** with three reasons, lets the user test "what if"
scenarios, and has a language model **explain** results. The rule from the brief is enforced in code:
*models calculate, the language model only explains*. A "grounding gate" blocks any sentence with a
number, direction or promise the engine didn't produce.

## 2. What "synthetic dataset" means, exactly

**Today, every home in the app is simulated.** We wrote a seeded simulator
(`greeniq/simulator/world.py`) that generates 3,000 UK-like homes, 2,372 customers, 183,146 monthly
meter readings, 2,774 house sales and 498 historical retrofits:
- **Physics:** heat loss from walls, roof, windows and floors, plus weather and heating efficiency.
- **People:** occupants and heating habits, including under-heating of draughty homes.
- **Installers:** installation quality varies.
- **Market:** house prices with an EPC-band premium.
- **Imperfect records:** missing fields, out-of-date EPCs, wrong heating records, missing meter
  months and empty homes.

It is calibrated to public anchors: median gas 12,120 kWh vs Ofgem's typical 11,500; median
electricity 2,757 kWh vs 2,700.

Why we did it: the public datasets the brief suggests (EPC register, smart-meter data, NEED, Land
Registry) cannot be joined home by home. A simulator gives us a complete, consistent world, plus a
hidden "truth" to grade against (e.g. what a retrofit *really* saves).

The weakness: **agreement with our own simulated world is not real-world accuracy**, and judges score
"ML & recommendation quality" (20%) on data quality and held-out evidence. Every report says this
plainly. **We have now downloaded the real dataset (NEED, §5) and the plan below moves the ML onto it.**

## 3. What is built and verified (all on GitHub)

| Area (brief section) | What exists | Evidence |
|---|---|---|
| Green Home Score (§2) | Exact weights, documented monotonic mappings, half-up rounding, 5 bands, per-part contributions, a **score range** when inputs are missing | 36 score tests incl. property-based monotonicity; `docs/SCORING_METHOD.md` |
| Poor homes and ranking (§3) | Flags Poor/Very poor; ranks by improvement potential; "unavailable" when the baseline is zero or unmetered; per fuel; fair to big homes | Ranking matches the true potential with Spearman **0.91**, vs **0.61** for "rank by total kWh" |
| Retrofit recommendations (§4) | 7 measures; feasibility first; High/Medium/Low; reasons for every excluded measure; order fabric → controls → heat pump → solar | 0 infeasible picks in a sweep of all 3,000 homes |
| Energy savings (§5) | Three-stage model (heat need → efficiency → energy bought), anchored on metered data; per fuel; package ≠ sum; heat pump raises electricity | Savings error vs real before/after behaviour in the simulated world: 790 kWh (rule of thumb) → **227 kWh** (calibrated engine) |
| Carbon (§6) | ΔC = ΔE_elec×EF_elec + ΔE_gas×EF_gas, DESNZ factors, signs shown | Tests; recomputes from displayed numbers |
| Property value (§7) | Current value + range; indicative uplift range; non-causal caveat; "unavailable" when evidence is thin | 80% interval covers **80.7%** of held-out sales |
| LLM + what-if (§8) | Template narrator (default); optional Claude / Ollama / llama.cpp / free hosted model behind the grounding gate; rule-based what-if parser; engine always reruns first | Gate: 0/387 honest texts blocked; caught **187/187** invented numbers, **186/186** flipped directions, **187/187** value promises, **135/135** off-scenario measures |
| Real LLM test | Qwen2.5-1.5B running locally via llama.cpp (free) | 94.4% of its numbers grounded; only **26%** of its explanations pass the gate (it often says a heat pump *reduces* electricity), so users see the template. **Users only ever see gated text.** |
| Dashboard | One command, one port, no build step: Dashboard, Properties, Property view (score breakdown, Next Best Action, ask a what-if, gate demo), Decision Lab (named plans, cost-vs-carbon frontier, dependency graph, energy Sankey, interaction heatmap, sensitivity), Analytics, Evidence | Verified in a browser; 0 console errors |
| Next Best Action | One action per home (retrofit / survey / question / no action), exactly 3 reasons, respects prerequisites | Sweep: 0 violations |
| Robustness | Edge-case sweep over all 3,000 homes: missing meters, zero use, conflicts, infeasible measures, interacting packages, heat pumps | **28,422 checks, 0 violations** (`reports/EDGE_CASES.md`) |
| Tests | 177 automated tests (score, data, engines, ML, NBA, API, Decision Lab, trust, LLM providers, end to end) | All pass |
| Submission items A–I | Prototype, code + data scripts, models, scoring doc, LLM doc, architecture, evaluation, Responsible AI, held-out predictions | All present (`docs/CURRENT_STATE.md` §6) |

## 4. What is not done yet (honest list)

1. **Real data.** The ML is evaluated only on simulated homes. This is the biggest gap.
2. **The small local LLM fails the gate too often (26% pass).** The gate is right to block it, but we
   should help small models with a better prompt, and fix one false block (the gate misreads
   "a saving of −3,240 kWh").
3. **Customer memory** (optional in the brief) only exists per request ("no heat pump", "already did
   the loft"); nothing is stored between visits.
4. **Emission factors** are DESNZ 2025. The 2026 factors (electricity 0.13096) are newer.
5. **Peer comparison and under-heating flags** ("your use is far below similar homes, so savings may be
   smaller") are not built.
6. **Live Claude** has never been run (no key). Not required: the local model covers the brief.

## 5. The real dataset we now have

**NEED anonymised 2026, 50,000-home sample** (DESNZ, Open Government Licence; 15 MB CSV; downloaded
to `~/.local/greeniq-raw/`, not yet in the repo). Verified contents:

| Field | Values | Use |
|---|---|---|
| Property type | semi 12,592 · flat 11,910 · mid terrace 9,444 · detached 7,777 · end terrace 4,309 · bungalow 3,968 | feature |
| Age band, floor-area band | 4 age bands, 5 area bands (coded) | features |
| Region | 9 English regions + Wales | feature |
| EPC band | A/B 5,291 · C 12,408 · D 13,015 · E 3,565 · F/G 635 · none 15,086 | feature |
| Main heating fuel | gas 40,445 · other 9,555 | feature |
| Retrofit installs with year | loft 7,180 · cavity wall 7,164 · **solar PV 800** | **real savings evidence** |
| Annual gas and electricity 2005–2024 | 2024 valid: gas 37,186 (median 10,000 kWh), electricity 45,214 (median 2,600 kWh) | **real targets** |
| Not included | wall type, loft depth, glazing, controls, boiler type, exact floor area, prices, monthly readings | must stay simulated, and be labelled |

## 6. Plan: move the ML onto real data (and finish everything)

Times are build time for one Claude Code session; model runs and evaluations are mostly unattended.

| Step | What | How | Done when | Time |
|---|---|---|---|---|
| **R1** Load NEED | Loader + validation + data card section | Read the metadata to decode bands; treat validity flags properly (V = valid, O = genuinely zero/off-gas, else missing); keep raw file checksum; split train/validation/test | 50,000 rows loaded, codes decoded, splits saved, data card updated | 45 min |
| **R2** Real energy model | Predict annual gas and electricity from real characteristics | Gradient boosting per fuel vs a peer-median baseline; tune on validation; score test once | Real held-out MAE/R² reported next to the baseline; ships only if it wins | 1–1.5 h |
| **R3** Real savings evidence | How much do loft, cavity and solar installs *really* save? | Difference-in-differences: change in use across the install year for installers vs similar non-installers (same type, age, area, region), with bootstrap ranges | Real % savings per measure with intervals; engine calibrated to them; report shows engine vs reality | 1–1.5 h |
| **R4** Peer comparison + under-heating flag | "Homes like yours use X"; flag homes using far less than expected | Real peer percentiles; expected (real model) vs actual | Shown on the property page; feeds Next Best Action confidence | 45 min |
| **R5** Real-data demo homes | App homes built from real NEED records | Sample NEED homes; fill missing details (exact area within band, walls, loft, glazing, heating detail, monthly split, sales) by documented rules; tag every field **real** or **simulated** in the UI | App runs on real-backed homes; badges visible; simulator kept for the tests that need hidden truth | 2–3 h |
| **R6** Fix the LLM pass rate | Help small models without loosening the gate | Fix the signed-number false block; give direction words in the fact sheet ("electricity: rises by 1,780 kWh"); tune on validation homes only; one test run | Pass rate re-measured honestly (before → after) | 1–1.5 h |
| **R7** Re-run and document | Retrain, re-evaluate (real and synthetic sections kept separate), edge sweep, tests, docs | Existing commands | All reports regenerated, all tests green | 1 h |
| **R8** Final submission pass | README, journal, fresh-clone run, merge to `main` | — | A stranger can run it from the README | 1 h |

**Total: about 9–11 hours of build time.** Order matters: R1 → R2 → R3 give the biggest gain in
marks (real evidence for the 20% ML criterion). R5 is the most work and can be cut to a smaller
sample if time is short.

## 6b. Progress on the plan (live)

| Step | Status | Result |
|---|---|---|
| R1 Load NEED | ✅ done | 50,000 real homes; checksum verified; codes decoded from the official metadata; only flag V used (O/E/L/G/blank = missing, never zero); split 35,197 / 7,311 / 7,492 |
| R2 Real energy model | ✅ done, honest result | On 6,774 real test homes, gradient boosting does **not** beat the "similar homes" median for electricity (MAE 1,640 vs 1,601 kWh). For gas it is slightly better (3,857 vs 3,979 kWh). R² 0.16 / 0.35. Characteristics explain little of real use; behaviour dominates. So the product anchors on each home's own meters, and the promotion rule keeps the simple baseline where the model doesn't win. |
| R3 Real savings evidence | ✅ done | Loft **5.6%** of gas (90% CI 5.2–6.1, 4,452 homes) · cavity wall **11.1%** of gas (10.5–11.6, 3,725 homes) · solar **9.8%** of grid electricity (5.2–12.2, 381 homes). Our engine predicts 6.4% / 22.1% / 26.2%, so real-world realisation is 0.88 / 0.50 / 0.37: a performance gap, now measured. |
| R4 Peers + evidence in the product | ✅ done | "Homes like yours" card on every metered home (vs real NEED homes of the same type, size and age, with percentile); low-use signal; "real data" evidence line on loft, cavity and solar recommendations |
| R5 Real-backed demo homes | ⬜ next | — |
| R6 LLM pass rate | 🔄 running | Gate false positive fixed (signed numbers); prompt v1.1 gives direction words ("RISES by …"); validation re-run in progress |
| R7 Re-run and document | ⬜ | — |
| R8 Final pass | ⬜ | — |

## 7. Decisions for the team

1. Commit the 15 MB NEED CSV to the repo (OGL allows it, reproducible offline), or download it on
   first run? Recommendation: commit it.
2. Switch emission factors to DESNZ 2026? Recommendation: yes, once the gas row is confirmed.
3. Customer memory: build a small persistent store (cheap, worth the 5% innovation marks) or leave it?
4. LLM for the demo: free local model (works offline, sometimes blocked) or a free hosted tier
   (better quality, needs someone to sign up)?

## 8. How to see it

```bash
uv sync
uv run python -m greeniq serve      # http://127.0.0.1:8000 (template narrator, no key needed)
# optional local LLM (free): run llama.cpp's llama-server with any small GGUF model on port 8081, then:
GREENIQ_LLM_PROVIDER=openai_compatible GREENIQ_LLM_BASE_URL=http://127.0.0.1:8081/v1 \
  GREENIQ_LLM_MODEL=qwen2.5-1.5b-instruct uv run python -m greeniq serve
```
Reports: `reports/EVALUATION.md`, `reports/GROUNDING.md`, `reports/EDGE_CASES.md`. Journal:
`docs/CURRENT_STATE.md`.

## 9. Prompt to paste into ChatGPT

> You are reviewing a hackathon project (Lloyds PS2, Green Home Score & Retrofit Recommendation
> Engine). Judging weights: ML & recommendation quality 20%, score & insight 15%, savings/carbon/value
> 15%, GenAI/LLM 15%, business relevance 10%, technical architecture 10%, explainability & responsible
> AI 5%, UX 5%, innovation 5%. Below is the project's status and plan. Tell us: (1) which of steps
> R1–R8 to do first, and which to cut if we only have N hours; (2) any risk in the plan or in how we
> describe synthetic vs real data; (3) what judges are most likely to probe in a 3-minute demo and how
> we should demo it; (4) anything missing against the brief. Be specific and practical.
>
> [paste this whole document here]
