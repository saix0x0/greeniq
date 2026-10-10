# GreenIQ — Implementation audit (Phase 0)

> Audit date 2026-10-11 · branch `beautiful` · HEAD `f0e5de6` (= `origin/beautiful`) plus **uncommitted** work
> (40 modified, 3 untracked files, +2,630 / −1,043 lines). Every status below cites a file, function, test or command
> result. No code was changed in Phase 0; this document is the only new file.
>
> Status key: ✅ implemented and tested · 🟡 implemented, not sufficiently validated · 🟠 partial · ❌ missing ·
> ⛔ blocked (data, credentials or approval).

## 1. Repository state

| Item | Evidence |
|---|---|
| Branch / remote | `git branch --show-current` → `beautiful`; `git status -sb` → `## beautiful...origin/beautiful` (no unpushed commits) |
| Uncommitted work | 40 modified + 3 new: `greeniq/config/assumptions.json`, `greeniq/evaluation/impacts.py`, `reports/RETROFIT_IMPACTS.md`. Includes the frontend rewrite, real-data calibration, PS2 audit fixes (layers §2–§4), validation-set evaluation and the NBA/LLM changes listed in the README status block. |
| Safety | Nothing committed or pushed since `f0e5de6`. The working tree is the only copy of this session's work. |
| Test baseline | `uv run pytest` → **199 passed, 0 failed** (run during this audit). |
| App | `uv run python -m greeniq serve` on :8000 starts, rebuilds 3,000 homes on an engine-key change and serves the UI and API; inspected in the browser at 1440 px, 800 px and 375 px. |

## 2. Architecture and data flow (as built)

```
data/raw (SIMULATED: properties, meters, weather, sales, market index, retrofit history)   data/real/need (REAL: DESNZ NEED 50k, OGL)
        │                                                                                         │
        ▼                                                                                         ▼
greeniq/data.py → features/resolve (Resolved: observed/derived/assumed/estimated/missing)   real/need.py → real/benchmarks.py (peers),
        │                                                                                    real/evidence.py (DiD savings → calibration)
        ▼
pipeline.analyse_home(p, ctx, scenario, constraints)   ── the single engine ──
  annualise (degree-day) → baseline per fuel → energy.decompose (need → efficiency → bought) → rating (SAP, stale-EPC reconcile)
  → score.compute_score (7 weights) → retrofit.plan_candidates (feasible / needs_survey / not suitable)
  → sequential apply_measure (calibrated) → package + improvement potential → carbon → value (ml/registry ValueModel)
  → nba.select_next_best_action → ComputedFacts (facts_id, versions, receipts)
        │
        ├── service.py (SQLite cache keyed by engine key; portfolio rows, group summaries)
        ├── lab.py (enumerate feasible packages, named plans, Pareto, interactions, sensitivity)
        ├── trust/ (narrator template, llm providers, gate, assistant what-if parser)
        └── api.py (FastAPI) → web/ (vanilla JS, no build)
```

The calculation engine is the single source of truth: the UI only formats API numbers; `tests/test_trust.py::test_ask_reruns_engine_and_explanation_matches_fresh_run` and `tests/test_nba.py::test_selector_computes_no_new_numbers` enforce that the AI and NBA layers do not compute.

## 3. PS2 traceability matrix

| PS2 § | Requirement | Implementation | Evidence | Status | Gap → planned correction (acceptance) |
|---|---|---|---|---|---|
| §1 | LLM never computes; what-if reruns models before explaining | `api.py` `/ask`, `/scenarios` → `pipeline.analyse_home`; `trust/narrator.explain` | `test_ask_reruns_engine_and_explanation_matches_fresh_run`, `test_what_if_reruns_the_engine`, `test_no_key_means_template_and_gated` | ✅ | — |
| §2 | Fixed weights 25/20/15/15/10/10/5, Σ=1 | `config/score_mappings.WEIGHTS`; assert in `score.compute_score` | `test_weights_are_exactly_ps2` | ✅ | — |
| §2 | Round to nearest integer; five bands | `score.round_half_up`, `band_for`, `BANDS` | `test_round_half_up`, `test_band_boundaries` | ✅ | — |
| §2 | Documented, monotonic sub-score mappings | `score_mappings.py`, `docs/SCORING_METHOD.md` | hypothesis tests `test_*_monotone`, `test_improving_one_input_never_lowers_the_score`, `test_heating_rungs_do_not_overlap…` | ✅ | — |
| §2 | Efficiency = recorded rating (or rating-based measure) | `score._efficiency`; `pipeline._resolve_sap` (recorded / band midpoint / stale-adjusted / estimated) | rating model vs peer baseline, validation MAE 4.4 vs 7.1 SAP (`reports/EVALUATION.md`) | ✅ | — |
| §2 | Intensity = annualised metered kWh/m² | `pipeline` step 7; `score._intensity` | `test_intensity_is_per_m2…` | ✅ | Estimated baseline is used and labelled when meters are insufficient (documented). |
| §2 | Justify inputs affecting >1 component | `docs/SCORING_METHOD.md` §3 | doc present | ✅ | — |
| §2 | Show each component's contribution | `ComponentScore.contribution`; UI tab 1 writes the sum out | `test_score_by_hand_from_the_ps2_formula` (44.0875 → 44) | ✅ | — |
| §2 | Worked example P10001 (38, Poor) | — | `test_ps2_worked_example_p10001_is_poor` → our mapping gives 34, Poor | 🟡 | Difference documented only in the test docstring → add to `SCORING_METHOD.md`. |
| §3 | Flag Poor/Very poor with key issues | `score.issues` (threshold `ISSUE_SUBSCORE_THRESHOLD`), `ranking.portfolio_row` | `test_ps_style_poor_home_is_flagged_poor` | ✅ | — |
| §3 | Rank by 100×(E_b−E_a)/E_b, E = imports + gas, same convention | `pipeline._package` → `ImprovementPotential`; `ranking.rank_poor_homes` | `test_improvement_potential_matches_ps2_formula`; validation Spearman 0.89 vs 0.64 (total kWh) | ✅ | — |
| §3 | Zero/unavailable baseline → unavailable | `_package` (status unavailable + reason) | `test_zero_baseline_gives_unavailable_not_zero_percent` | ✅ | Changed this session: estimated baselines are now ranked and labelled `estimated` (`test_estimated_baseline_still_reports_potential…`). |
| §3 | Electricity and gas separately; solar cuts imports, not demand | `energy.EnergyState.purchased` | `test_solar_reduces_imports_not_demand`, `test_heat_pump_raises_electricity…` | ✅ | — |
| §3 | Large homes not penalised for size | intensity per m²; ranking by % | `test_intensity_is_per_m2…`; evaluation "big-house trap" baseline | ✅ | — |
| §4 | Feasible only; Recommend / Refer / Not suitable | `engines/retrofit.plan_candidates` (`needs_survey`, `infeasible`, `not_applicable`, …) | `test_infeasible_retrofit_is_refused_with_a_reason`, `test_solar_consent_cases_are_check_first_not_ruled_out` | ✅ | — |
| §4 | Suitability H/M/L, saving, reason; order reflects interactions | `Recommendation`, stage ordering, `depends_on` | `test_respects_prerequisites`, `test_heat_pump_not_first_while_fabric_pending…` | ✅ | — |
| §4 | Unknown facts → survey, never treated as proof | `retrofit.py`; assumed inputs carry `uncertainty` | — | 🟠 | Inputs **assumed from age band** (e.g. cavity, loft depth) are still *recommended* at Medium suitability with a note, not routed to "check first" as the mechanism doc says. Decide the rule (see §8 decisions). |
| §4 | Documented catalogue with sources; impacts applied to the right quantity | `config/retrofit_catalogue.json` v1.1 (applicability, PS2 illustrative impact, costs + sources) | `reports/RETROFIT_IMPACTS.md` (generated) | 🟡 | Cost sources are partly secondary (e.g. NerdWallet, "typical market ranges"). Heat pump modelled at 55.7% of purchased energy vs the brief's illustrative 15–25%: physics-consistent, documented, not validated on real data. |
| §5 | Per-measure and package savings per fuel, kWh/yr; increases negative; interactions | `pipeline` sequential states, `_impact`; `PackageResult.interaction_kwh` | `test_package_not_sum…`, `test_heat_pump_raises_electricity…`, edge sweep invariants | ✅ | — |
| §5 | Heating separated before applying insulation impact | `energy.decompose` using degree-day split | `test_decomposition_reproduces_the_metered_baseline`, `test_annualisation_recovers…` | ✅ | — |
| §5 | Evidence-based calibration with limitations | `ml/registry.apply_real_realisation` (NEED DiD, median÷median) | realisation loft 1.42, cavity 0.50, solar 0.38 (`reports/REAL_DATA.md`) | 🟡 | **Not hand-audited yet (Phase 1).** Loft rate > 1 (engine under-predicts); real installers vs simulated homes are different populations; HP/glazing/controls/solid wall calibrated on simulated history only; `test_calibration_shrinks_fabric_savings` predates the real override → review. |
| §6 | ΔC = Σ ΔE_f × EF_f, documented factors | `engines/carbon.py`, `config/emission_factors.json` (`desnz-2025/1.0`) | `test_carbon_is_per_fuel_with_signs`; UI shows the formula with this home's values | 🟡 | Electricity 0.177 is **derived** (`verified: null`), not read from the condensed set; mechanism doc promises 2026 factors. UI does not show "gas carbon removed → electricity carbon added → net" as separate lines (receipt has them). |
| §7 | Value as a range; same home before/after; location/size/type/market | `ml/registry.ValueModel` (hedonic + conformal, regional index) | `test_value_is_a_range_with_caveat`, `test_no_band_change_means_no_indicative_uplift` | 🟡 | (a) **Circular**: uplift is learned from simulated sales whose EPC premiums the simulator *planted* (DATA_CARD discloses). (b) Test split influenced value-model selection (`model_card.json` `protocol_note`). (c) "Later sales" evaluation is a customer split, not temporal. |
| §7 | Thin evidence → unavailable | `_value` | `test_value_unavailable_without_floor_area` | 🟠 | Only the missing-area case is tested; no thin-cell rule. |
| §8 | Outputs, pipeline, what-if, LLM explains computed values | as §1; gate `trust/gate.py` v1.4 | `test_trust.py`, `test_llm_providers.py` (fake Ollama, zero cost) | ✅ (mechanism) / 🟠 (quality) | LLM targets (≥90% grounded, ≥90% accurate, <5% unsupported): `reports/GROUNDING.md` is **stale** (26.3% accurate, generated before hybrid style). Latest validation 41/50 (82%) was on an earlier prompt/gate; the current code is unmeasured. |
| §9 | Synthetic/public data within licence; no personal data | `data/DATA_CARD.md` (sources, licences, label rules) | doc; `test_real.py::test_file_is_the_published_one` | ✅ | — |
| §9 | Property/customer-level splits; no leakage | `data.py` splits; `ml/features` | `test_split_is_by_customer_and_disjoint`, `test_features_never_read_meters`, `test_no_forbidden_feature_names`, `test_product_code_never_imports_the_simulator_or_truth`, `test_value_cv_folds_are_grouped_by_customer` | ✅ | — |
| §9 | Consistent annualisation; missing months not zero | `features/annualise` | `test_missing_months_are_not_zero_filled`, `test_too_few_months_is_insufficient_not_a_guess` | ✅ | — |
| §9 | Current value separate from sale prices; prediction-time fields | `DATA_CARD.md` §2 | doc | ✅ | — |
| §10 | Customer memory (optional) | per-request `declined_measures` / `completed_measures` (`api.ScenarioRequest`, `retrofit.py`, `pipeline._apply_memory_to_inputs`) | `test_declined_measure_is_never_selected` | 🟠 | No persistent store, no budget constraint in NBA, no "how recommendations change as memory builds up" demo. |
| §11 | Documented splits; validation metrics; simple baselines | `evaluation/evaluate.py` (validation pass + test once), `report.py` | `reports/EVALUATION.md` "Validation set" table (generated) | ✅ | Validation section added this session (uncommitted). |
| §11 | Scenario-based tests (missing, conflicting, infeasible, interacting, HP electricity rise, insufficient info) | `evaluation/edge_sweep.py`, fixtures | `reports/EDGE_CASES.md` | 🟡 | **Stale**: generated before this session's engine changes → regenerate. |
| §11 | LLM evaluation on held-out scenarios | `evaluation/grounding.py` (test split) | `reports/GROUNDING.md` | 🟠 | Stale; metric definitions need tightening (claim-level vs explanation-level); validation and test must be kept separate. |
| §13 A | Working prototype | `greeniq/web/`, `api.py` | browser inspection (§6) | ✅ | UX gaps in §6. |
| §13 B | Code, data scripts, run instructions | `simulator/`, `cli.py`, README "Run it" | README | ✅ | Clean-setup run not re-verified this session. |
| §13 C | Trained models + inference | `models/*.joblib`, `ml/` | `test_models_never_break_the_pipeline` | ✅ | — |
| §13 D | Scoring method | `docs/SCORING_METHOD.md` | doc | ✅ | Add P10001 note. |
| §13 E | LLM prompts, model, evaluation | `trust/prompts.py`, `docs/LLM.md`, `reports/GROUNDING.md` | files | 🟠 | Evaluation stale. |
| §13 F | Architecture diagram | `docs/ARCHITECTURE.md`, `docs/assets/greeniq-system.svg` | files | 🟡 | Not checked against the current architecture. |
| §13 G | Evaluation report on the validation set | `reports/EVALUATION.md` | generated this session | 🟡 | Uncommitted. |
| §13 H | Responsible AI note | `docs/RESPONSIBLE_AI.md` | file | 🟡 | Not re-read for currency (calibration, data circularity). |
| §13 I | Held-out test predictions + schema | `reports/test_predictions.csv`, `TEST_PREDICTIONS_SCHEMA.md` | `test_held_out_predictions_are_test_split_only` | ✅ | — |

## 4. Product-mechanism document vs implementation

| Mechanism claim (GreenIQ_Product_Mechanism.pdf) | Status | Evidence / gap |
|---|---|---|
| Three-stage energy model (need → efficiency → bought) | ✅ | `engines/energy.EnergyState` |
| One engine, one shared results record, three readers | ✅ | `ComputedFacts` (facts_id, versions, receipts); NBA/UI/AI read it |
| NBA: retrofit / survey / question / no action, three reasons, benefit × confidence, order, "needs a human" queue | 🟠 | See §5. Ranking is benefit × suitability weight; reasons padded; no explicit human-review flag |
| Rating reconciled against metered use ("rating may be out of date") | ✅ | `conflicts` `stale_epc`, SAP adjusted for later work |
| Intensity judged **against similar homes** | ❌ | Intensity sub-score uses absolute knots; peers are shown separately, not used in the score |
| Actual-vs-expected split (fixable by building vs how it's used); under-heating homes flagged, **not top-ranked** | 🟠 | `real/benchmarks` emits low/high-use *signals*; ranking ignores them |
| Unknown facts → survey, never a blanket reject | 🟠 | Unknown → `needs_survey` ✅; *assumed* facts still recommended (see §3, §4 row) |
| Carbon breakdown gas removed → electricity added → net | 🟠 | In receipts, not as UI lines |
| Value: two outputs, range, tested on later sales, anchored on published premium studies | 🟠 | Synthetic sales with planted premiums; no published-study anchor; no temporal holdout |
| Datasets: NEED ✅ · EPC ❌ · London Smart Meter ❌ · HM Land Registry ❌ · government factors ✅ (2025, not 2026) · weather API ❌ (synthetic) · simulator ✅ | 🟠 | `data/raw` + `DATA_CARD.md` (EPC needs account creation; LSM/LR not joinable). **The mechanism doc overclaims these sources.** |
| Proof layers 1–5 (invariants, scenario suite, model eval vs baseline, LLM grounding, reproducibility) | 🟡 | Layers 1–3 ✅; layer 4 stale; layer 5 seeds ✅, clean-setup not re-verified |
| Customer memory | 🟠 | Per-request only |

## 5. Next Best Action — specific gaps (`greeniq/engines/nba.py`, 227 lines)

What exists (verified): deterministic selector over `ComputedFacts`; blockers first (high-severity conflict → survey; heating unknown → question; no baseline → meter readings; nothing feasible but surveys pending → survey); prerequisites enforced (`_eligible`); objectives `value_for_money` (carbon per £, £1k floor), `carbon`, `energy`; minimum benefit → `no_action`; alternatives list; reasons carry `fact_ref`. Tests: 10 in `tests/test_nba.py`.

| # | Gap | Evidence |
|---|---|---|
| N1 | Single composite rank (objective benefit × suitability weight). Evidence strength (real-home evidence vs engineering only), uncertainty and cost are not separate dimensions; trade-offs are not exposed. | `_rank` |
| N2 | "Confidence" is `min(home confidence, suitability)`; it does not affect ranking beyond the suitability weight. | `select_next_best_action` |
| N3 | Reasons are **padded to exactly three** with generic facts (confidence, score) when fewer substantive reasons exist. | `_pad` |
| N4 | `why_not_first` is generic ("ranks lower on the objective"); no comparative explanation (by how much, on what). | `_alternatives` |
| N5 | Output lacks direct electricity/gas/carbon/cost fields, per-action uncertainty, an explicit human-review flag and reason, and provenance beyond `method_version`. | `facts.NextBestAction` |
| N6 | Assumed-input candidates are recommended, not routed to an information request first. | `retrofit.py` + `_blocked` |
| N7 | Budget and other stated constraints are not used by NBA (only the Lab's "my budget" plan). | `api.lab(budget)` only |
| N8 | No "record a completed retrofit" action; memory is per-request. | — |
| N9 | No evaluation of NBA against a documented baseline policy (e.g. "cheapest feasible", "biggest saving"). | — |
| N10 | Alternatives truncated to 4. | `out[:4]` |

## 6. UX problems observed in the running app (this audit)

| # | Observed at | Problem |
|---|---|---|
| U1 | 1440 px, home P00007 | The next best action is one line inside the verdict banner; the first tab opens on the score table. Its cost, expected change and confidence are not on the first screen. |
| U2 | 800 px, tab 2 | "Saves electricity 0 gas ▼ 580" mixes "saves" with a decrease arrow — direction can be misread. |
| U3 | 1440 px, light theme | "Highly efficient" label on the darkest band segment is barely readable (contrast). |
| U4 | all | EPC rating vs GreenIQ score difference is only explained in the evidence pane. |
| U5 | 375 px, Many homes | Six KPI cards and wrapped tabs push the ranked queue below the fold; the top bar takes three rows. |
| U6 | ≤1100 px | The evidence pane becomes a hidden drawer with no visible entry point other than clicking a number. |
| U7 | 800 px, Compare | Third column clipped; horizontal scroll needed. |
| U8 | Compare groups → Heating | "Unknown: 100% poor" — percentage over homes with a known band; the denominator is not shown. |
| U9 | Overview vs tab | "1,017 flagged" vs "1,001 ranked" — the difference is explained only inside the Poor-homes tab. |
| U10 | What-if tab | Plan comparison (Lab) is behind a button inside the tab; low discoverability. |
| — | console | Only 9 stale errors from the pre-rewrite script were present (`app.js:88` old line); none attributable to the current code were seen, but the log was not cleared, so this is not proof of zero errors. |

## 7. Ranked implementation plan

| Rank | Phase | Work | Depends on | Acceptance criterion |
|---|---|---|---|---|
| 0 | — | Commit the current tested working tree (199 passing) to `beautiful` | approval | `git status` clean; CI-equivalent `pytest` green |
| 1 | 1 | §5 savings hand audit incl. calibration review (loft > 1, populations, HP evidence) | 0 | hand-worked tests for one home per measure; documented decision on each rate |
| 2 | 1 | §6 carbon: factor provenance decision (2025 derived vs 2026); per-fuel breakdown lines in UI | 0 | factor file verified; breakdown visible and tested |
| 3 | 1 | §7 value: disclose/resolve circularity; temporal or fresh holdout; thin-evidence rule | decision D4 | range coverage on an untouched holdout; unavailable rule tested |
| 4 | 1 | Regenerate `EDGE_CASES.md`, `GROUNDING.md` (validation only); refresh ARCHITECTURE, RESPONSIBLE_AI, SCORING_METHOD (P10001); correct the mechanism doc's dataset claims | 1–3 | reports carry current git hash; docs match code |
| 5 | 2 | NBA rework (N1–N10): lexicographic eligibility → separated dimensions → documented rule; supported-reasons-only; comparative "why not"; full output contract; budget/constraints; baseline-policy evaluation | 1 | the 12 tests listed in the master prompt §5.5 pass; report vs baseline policy |
| 6 | 3 | Decision Lab: verify existing `lab.py`; add per-fuel carbon, dominated-package labelling, constraints | 5 | every scenario change hits `/scenarios`; tests |
| 7 | 4 | UX: NBA as primary focus (U1), unambiguous signs (U2), contrast (U3), EPC vs score (U4), mobile portfolio (U5–U7), denominators (U8–U9), Lab entry (U10) | 5, 6 | the 7 UX tasks in master prompt §7.4 checked in the browser at 1440/800/375 px |
| 8 | 5 | AI: re-measure on validation with current code; then one test run; claim-level metric definitions | 4 | numerator/denominator/version reported; targets met or gap stated |
| 9 | 6 | Customer memory store (optional) | 5 | completed work never re-recommended; constraints respected; memory never edits a computed figure |
| 10 | 7 | Clean-setup run, final evaluation, submission checklist | all | fresh clone → `uv sync` → serve → tests green |

## 8. Risks, blockers and decisions requiring approval

| # | Decision / risk | Options | Recommendation |
|---|---|---|---|
| D1 | Commit the 43-file working tree now | commit / keep uncommitted | Commit (tested; the working tree is the only copy) |
| D2 | Mechanism doc lists EPC, London Smart Meter, Land Registry, weather API — not used | correct the doc / acquire data | Correct the doc now; EPC bulk needs account creation (you would have to do it); Land Registry is a large OGL download (needs your approval) |
| D3 | Emission factors: DESNZ 2025 with derived electricity value vs 2026 | keep and disclose / switch | Switch only once the 2026 rows are verified from the official file |
| D4 | Value uplift is learned from simulator-planted premiums; test split influenced value selection | disclose only / anchor on published studies + new holdout | Disclose now; anchor on published EPC-premium studies if a source is approved |
| D5 | Loft realisation 1.42 (> 1) | accept / cap at 1.0 / per-segment | Accept with disclosure; review in Phase 1 |
| D6 | Heat pump 55.7% vs brief's 15–25% | keep physics / calibrate | Keep, documented; no real HP evidence in NEED |
| D7 | NBA ranking rule | composite score / lexicographic + visible trade-offs | Lexicographic eligibility, then a documented objective with trade-offs shown |
| D8 | LLM evaluation leakage | grounding eval uses the test split; prompt work used validation this session, earlier history unknown | Report validation now; treat test as contaminated unless a fresh holdout is defined |
| R1 | Small local model (Qwen 1.5B) may not reach 90% | larger free model / stricter hybrid | Measure first, then decide |
| R2 | Real-data limits | NEED has no heat-pump or glazing evidence; no property-level link to our homes | Keep labelled as engineering estimates |
