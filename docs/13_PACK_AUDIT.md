# 13 · Pack Audit (architecture finalisation)

> Audit of the architecture pack at commit **`0ad452d`** (main) against the
> implementation-readiness requirements. Line numbers refer to that commit. Remote state
> was checked before editing: `main` = `0ad452d`. Branch `atharva` changes only two
> README lines. Branch `beautiful` is identical to main. Neither contains application
> code, and neither was modified.
>
> **Re-checked before pushing:** `main` had advanced to `934fa71` (Pranit, "Add
> GreenPath Home prototype": a new `greenpath_home/` folder, a `.gitignore`, and a
> 5-line README note). The finalisation was applied **on top of** that commit. The
> prototype and the README note are preserved, and the prototype is classified as
> helpers/suggestions in `14_GREENPATH_PROTOTYPE_NOTES.md`.

## BLOCKING GAPS (prevented reliable one-pass implementation) — all corrected

| # | Finding | Evidence (file:line @0ad452d) | Resolution |
|---|---|---|---|
| B1 | The handoff asked for a **starter build** and delegated all method/stack decisions to the builder ("You own the HOW"), with memory "seamed or minimal", which conflicts with a complete one-pass base product | `START_HERE_PROMPT.md:13-16`, `:33-34`, `:72-73`, `:88-90` | `START_HERE_PROMPT.md` rewritten as an executable handoff to `11_IMPLEMENTATION_SPEC.md` |
| B2 | Eleven research questions were left **open** (score mappings, intensity benchmark, energy model, catalogue, factors, value method, data, LLM, metrics, stack, memory) | `docs/05_RESEARCH_PLAYBOOK.md:28-38` | Resolved in `11` §1–§12; `05` now marks each RQ resolved and points to the spec |
| B3 | **No data selection:** DR requirements listed, but no dataset, fields, access, joins or synthetic rules | `docs/02_PROBLEM_DECODED.md:79-85`; no dataset spec anywhere | `11` §3: NEED 2026 50k (verified URL, OGL), field mapping, augmentation A-06…A-19, validation, splits |
| B4 | **No sub-score mappings or thresholds**, only weights | `docs/01_GUARDRAILS.md:53`; `docs/02_PROBLEM_DECODED.md:48` | `11` §5.2–5.3 (tables, evidence tags, missing-data bounds, rounding) |
| B5 | **No savings/interaction algorithm** ("physics-lite / catalogue model" undefined) | `docs/03_ARCHITECTURE.md` component table (Energy engine row, `:118`) | `11` §6.2–6.5 (end-use model, heat-loss index, sequential package, NEED-calibrated in-use factor) |
| B6 | **No value method or source** ("documented rating-premium band") | `docs/03_ARCHITECTURE.md` Value engine row (`:121`) | `11` §7 (hedonic OLS + bootstrap; DECC 2013 premiums; HPI July 2026; mandatory wording) |
| B7 | **Emission factors not chosen** | `docs/01_GUARDRAILS.md:58` | `11` §6.7: DESNZ 2026, electricity 0.13096 (verified in the official report), gas 0.18231 (confirm) |
| B8 | Grounding relied **solely on naive number matching**, which the brief prohibits | `docs/04_RUNTIME_FLOWS.md:131-149`; `docs/10_MECHANISMS_HANDBOOK.md:166-168`; `docs/07_TRUST_AND_EVALUATION.md:73` | `11` §8.1–8.3: facts registry + structured outputs with per-sentence `fact_ids` + citation-bound verifier; 04/07/10 annotated |
| B9 | **No API routes, schemas, DB entities or screens**: roles only | `docs/03_ARCHITECTURE.md` §3–4; `docs/06_BUILD_FRAMEWORK.md` §4 ("roles, not prescriptions") | `11` §4, §9, §11 |
| B10 | **Stack undecided** | `docs/06_BUILD_FRAMEWORK.md:34`; `docs/05_RESEARCH_PLAYBOOK.md:37` | `11` §1–§2 |
| B11 | The definition of done allowed **placeholder engines** and a starter scope | `docs/06_BUILD_FRAMEWORK.md:36`, `:54`, `:70-73` | `06` now points its definition of done at `11`; placeholders allowed only transiently during the build |

## IMPORTANT GAPS — corrected

| # | Finding | Evidence | Resolution |
|---|---|---|---|
| I1 | Evaluation metrics were deferred ("choose exact metrics in an ADR") | `docs/07_TRUST_AND_EVALUATION.md:61` | `11` §12.2 (metrics, baselines, data per area; real-data evaluation of energy and CWI/LI savings) |
| I2 | No rule for partial scores when inputs are missing | `docs/01_GUARDRAILS.md:62-69` (principle only) | `11` §5.3 bounds method |
| I3 | Annualisation rule undefined | `docs/02_PROBLEM_DECODED.md:83` | `11` §6.1 |
| I4 | Required screens (portfolio, search, provenance) not specified | `docs/04_RUNTIME_FLOWS.md` (Flow D only) | `11` §11 |
| I5 | LLM model and interface unspecified ("any vendor/model"); forced tool calls would fail on the default model | `docs/08_EXTENSIBILITY_ROADMAP.md:55` | `11` §8.2 (`claude-opus-5-5`, effort low, structured outputs, no forced `tool_choice`, refusal fallback, template mode) |
| I6 | Wording still described a "starter" | `README.md:83`; `docs/08_EXTENSIBILITY_ROADMAP.md:3`; `docs/04_RUNTIME_FLOWS.md:4`; `docs/03_ARCHITECTURE.md:109` | updated to "base product" |
| I7 | No requirement → test traceability | — | `12_REQUIREMENTS_MATRIX.md` |

## Already satisfied (kept)

PS decoding and requirement IDs (`docs/02_PROBLEM_DECODED.md:44-111`), PS-fixed contracts
(`docs/01_GUARDRAILS.md:46-60`), truthfulness and data rules (`:62-84`), runtime flows
(`docs/04_RUNTIME_FLOWS.md:9-129`), scenario behaviours (`:169-178`), the failure-mode
table and Responsible-AI position (`docs/07_TRUST_AND_EVALUATION.md:30-45`, `:79-88`),
the mechanisms handbook (`docs/10`), the submission checklist (`docs/09`), ADR-001.

## ACCEPTABLE TRADE-OFFS (deliberate, defensible)

| # | Trade-off | Why defensible |
|---|---|---|
| A1 | Customer memory (PS §10) not in the base product | Optional per PS; the seam is reserved (`08`) |
| A2 | EPC register data not used | Requires registration/API key; NEED already carries the EPC-derived band and attributes for real homes under OGL |
| A3 | London smart-meter data not used | ~10 GB, electricity only, no property attributes; monthly profiles are documented assumptions (A-27) |
| A4 | Land Registry Price Paid not modelled | Cannot be joined to EPC/NEED at property level without credentials; value uses HPI-calibrated synthetic sales + published associations, labelled as such |
| A5 | Heat pump, PV, glazing, thermostat effects not validated against observed outcomes | NEED records only CWI/LI/boiler installs; engineering parameters are cited (EoH SPF 2.80) and fabric measures are calibrated on real installs |
| A6 | Oil/LPG/solid-fuel homes excluded | PS defines purchased energy as grid electricity + gas; exclusions counted in DATA_CARD |
| A7 | Some attributes are synthetic (exact floor area, glazing, PV, controls, loft mm…) | Per-field provenance; UI + DATA_CARD disclose; ML models use real fields only |
| A8 | Rating projection approximates SAP via a cost ratio | Official functional form; deflator cancels; labelled "projected (estimate)" |
| A9 | Two diagrams render wide (08 plug-in flow, 10 overview) | Cosmetic only |
| A10 | No Docker | Local one-command run satisfies reproducibility; avoids extra failure points |
