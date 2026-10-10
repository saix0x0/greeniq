# 14 · Teammate prototype `greenpath_home/`: helpers and suggestions

> **Status: SUGGESTIONS AND HELPERS, not requirements.** `greenpath_home/` is a working
> deterministic Python prototype a teammate pushed (commit `934fa71`). It is useful. Borrow
> its good ideas freely. **But wherever the spec (`11`) or a better idea exists, use the
> better one.** Nothing in this folder overrides `11_IMPLEMENTATION_SPEC.md`, and nothing
> in `11` requires copying this folder.
>
> **Rules:** keep the folder (don't delete or rewrite a teammate's work). Build the main
> product in `backend/` + `frontend/` per `11`. Borrow ideas, wording and test cases.
> Don't import the prototype as a dependency.

## ✅ Worth adopting (helpers)

| Prototype piece | Where | Use in the main build |
|---|---|---|
| One script per pipeline step (score, rank, recommend, carbon, value, report) | `greenpath_home/scripts/*.py` | Mirror as `greeniq.cli` sub-commands. A quick, keyless way to demo each stage |
| **One combined customer report** matching PS §8 "Expected outputs" | `scripts/generate_customer_report.py` | Add `cli report <property_id>` and a print-friendly report view of `/report`. Handy for the demo and judges |
| Plain-English reasons per component and key-issue phrasing | `src/green_home/scoring.py` (`_component_reason`, `_key_issues`) | Reuse the wording in receipts and template explanations (keep the citations/fact IDs from `11` §8) |
| Requirement → file compliance table | `docs/brief_compliance_checklist.md` | A good cross-check against `12_REQUIREMENTS_MATRIX.md` |
| An honest "this is sample data" note in the README | `greenpath_home/README.md` | Same tone for our DATA_CARD and the `/about` page |
| A `limitation` field on the value estimate | `src/green_home/value.py` | Matches our mandatory value wording (`11` §7) |
| `FuelSavings` with a net helper | `src/green_home/retrofits.py` | Same idea as our per-fuel `Quantity` outputs |
| **10 targeted tests** (classification boundaries, poor home flagged, better rating never lowers the score, only feasible retrofits, no already-installed upgrades, package ≠ simple sum, per-fuel carbon, electricity increase as a negative saving, value range from rating change, missing value → unavailable) | `greenpath_home/tests/` | Port these as **extra cases** into `backend/tests/` (they align with `11` §12.1) |

## 🔁 Superseded by the spec (ours is better; use `11`)

| Prototype choice | Spec choice | Why the spec wins |
|---|---|---|
| Generated sample data (a handful of homes) | DESNZ **NEED 2026** real data + documented augmentation (`11` §3) | Real consumption and characteristics; judges reward data quality |
| Emission factors 0.207 / 0.183 marked "prototype sample factor" | **DESNZ 2026: 0.13096 (electricity), 0.18231 (gas)** (`11` §6.7) | Official, current, cited |
| Annualise as `sum × 12 / n` | Seasonal-weighted with coverage rules (≥ 9 months; winter month for gas) (`11` §6.1) | Avoids summer/winter bias; explicit missing-data handling |
| Python `round()` | **round-half-up** (`11` §5.3) | Python rounds .5 to the nearest even number (`round(30.5)` → 30, `round(31.5)` → 32), so tied scores round inconsistently. Half-up is what "nearest integer" means to a reader |
| Flat % savings (insulation 16/12%, glazing 10/8%, heat pump replaces 80% of gas, solar 30%, thermostat 7%) | Heat-loss index + end-use model + ASHP SPF 2.80 + **NEED-calibrated in-use factor** (`11` §6.2–6.5) | Interactions by construction; anchored to observed savings |
| Value uplift from a band-steps table | Hedonic OLS + bootstrap range, DECC-anchored, non-causal wording (`11` §7) | A documented, evaluable method with uncertainty |
| Separate A and B ratings | NEED groups A/B (`11` §5.2) | Follows the real data |
| Order: insulation, glazing, heat pump, solar, smart controls | Fabric → **controls** → heat pump → solar (`11` §6.4) | Controls are cheap, and they affect the heating demand the heat pump is sized against |
| No LLM, API or UI | `11` §8–§11 | Required for the product |

## Suggestion for the team
If the prototype owner prefers a choice above over the spec's, raise it with evidence.
If it's better (more defensible, simpler, or better evaluated), adopt it and record it in
`docs/DECISIONS.md`. That's the "best idea wins" rule.
