# 11 · Implementation Specification (definitive)

> **Status: FINAL. This is the build contract for the base product.** Where this document
> is more specific than docs 01–10, **this document wins** (docs 01–10 remain the
> rationale). The PS2 PDF remains the source of truth for *requirements*. Claude-2
> implements exactly this; it makes only minor implementation decisions that are not
> settled here and records them in `docs/DECISIONS.md`.
>
> Every parameter is tagged **[E]** (evidence: a cited, verified source),
> **[E?]** (evidence from secondary sources: confirm against the named primary source
> during the build and record the result), or **[A]** (an engineering assumption:
> documented, configurable, disclosed in the UI and report). Assumptions carry IDs
> (`A-xx`) that receipts must reference.

---

## 0. What gets built (scope of the base product)

One integrated application, built in one pass:

| # | Capability | Section |
|---|---|---|
| 1 | Reproducible data pipeline: **real DESNZ NEED data** + documented synthetic augmentation | §3 |
| 2 | Canonical schema + validation + conflict detection | §3.5, §4 |
| 3–4 | Green Home Score (exact PS weights), monotonic mappings, explanations, rounding, classification | §5 |
| 5 | Poor / Very poor detection and ranking by improvement potential | §6.6 |
| 6 | Property-specific feasibility and prioritised recommendations | §6.4 |
| 7–8 | Per-retrofit and package savings with interactions, electricity and gas separately | §6 |
| 9 | Carbon from DESNZ 2026 factors | §6.7 |
| 10 | Property-value impact as a range | §7 |
| 11–12 | Grounded LLM explanations + what-if (validate → recompute → explain) | §8 |
| 13 | Frontend: portfolio, search, ranking, property detail, what-if, provenance | §11 |
| 14 | FastAPI + SQLite connecting everything | §9, §10 |
| 15 | Tests, held-out evaluation vs baselines, run instructions, submission docs | §12–§14 |

**Helpers available:** the teammate prototype `greenpath_home/` offers reusable ideas,
wording and tests. See `14_GREENPATH_PROTOTYPE_NOTES.md`. Those are suggestions only.
Where this spec or a better idea exists, that wins.

**Not in the base product (acceptable trade-offs, see `13_PACK_AUDIT.md`):** customer
memory (PS §10 is optional; the seam is reserved), EPC register data (needs
registration), the London smart-meter data (10 GB, electricity only), and Land Registry
transaction modelling.

---

## 1. Technology stack (final)

| Layer | Choice |
|---|---|
| Language/runtime | Python **3.11 or 3.12**; Node **20+** |
| Backend | **FastAPI** + Uvicorn, **Pydantic v2** (domain contract) |
| Storage | **SQLite** via **SQLAlchemy 2.x** ORM; file `data/greeniq.db` (regenerable) |
| Data processing | **pandas**, **numpy**, **pyarrow** (parquet), **odfpy** (read the NEED `.ods` metadata via `pandas.read_excel(engine="odf")`) |
| Models | **scikit-learn** (`HistGradientBoostingRegressor`, `LinearRegression`, `GroupShuffleSplit`), **joblib** for persistence. No XGBoost/LightGBM dependency: HGBR is the same gradient-boosting family and avoids native-build risk. |
| LLM | Official **`anthropic`** Python SDK, structured outputs (§8) |
| Tests | **pytest**, **hypothesis** (property-based monotonicity), FastAPI `TestClient` |
| Frontend | **React 18 + TypeScript + Vite**, **Tailwind CSS**, **Recharts**, **React Router**, **TanStack Query**; types generated with **openapi-typescript** from the backend's OpenAPI; tests with **Vitest + React Testing Library** |
| Run/serve | One Python CLI (`python -m greeniq.cli …`) + Makefile wrappers; FastAPI serves the built UI on one port (`:8000`); Vite dev server on `:5173` proxies `/api` |
| Deployment | Local only. No Docker, microservices, vector DB or queue. |

Pin exact versions in `backend/requirements.txt` and `frontend/package-lock.json` at
build time. Licences must be MIT/BSD/Apache.

## 2. Repository layout (final)

```
README.md  START_HERE_PROMPT.md  Makefile  .env.example  .gitignore
greenpath_home/                   # teammate prototype: KEEP; helpers & suggestions only (docs/14)
backend/
  pyproject.toml  requirements.txt
  greeniq/
    __init__.py  config.py  cli.py  schema.py  facts.py  pipeline.py
    reference/                      # versioned reference data (JSON), loaded at startup
      carbon_factors.json  retrofit_catalogue.json  engineering_params.json
      value_premiums.json  hpi_regional_2026_07.json  energy_prices.json
      need_code_map.json            # generated from the NEED metadata .ods by data/need_loader.py
      peer_benchmarks.json          # generated from TRAIN split
      calibration.json              # generated from TRAIN split (§6.5)
    data/      fetch_need.py  need_loader.py  augment.py  synthetic_fallback.py
               validate.py  split.py  build.py
    features.py
    engines/   score.py  rating.py  energy.py  retrofit.py  savings.py
               ranking.py  carbon.py  value.py  baseline_ml.py
    llm/       client.py  prompts.py  explain.py  templates.py  scenario_parser.py  verifier.py
    api/       main.py  routes.py  errors.py  serve_frontend.py
    db.py  tables.py  train.py  precompute.py  evaluate.py  smoke.py
  tests/       unit/  integration/  fixtures/golden_homes.json
frontend/      (Vite React TS app; src/api/schema.d.ts generated)
data/
  raw/need/anon2026_50k.csv  anon2026_50k.csv.sha256  NEED-2026-anonymised-dataset-metadata.ods
  processed/   (gitignored; regenerated)
  DATA_CARD.md
models/        energy_elec.joblib  energy_gas.joblib  value_hedonic.joblib  value_price_q.joblib  (committed: SR-C)
reports/       eval_report.md  metrics.json  holdout_predictions.csv  holdout_predictions.schema.json
               test_results.txt  llm_eval.jsonl (only if an LLM run happened)
docs/          pack (00–13) + generated: SCORING_METHODOLOGY.md  LLM.md  RESPONSIBLE_AI.md
               ARCHITECTURE.md  DECISIONS.md
```

---

## 3. Data strategy (final)

### 3.1 Sources (verified)

| Dataset | Use | Access / licence | Status |
|---|---|---|---|
| **NEED anonymised data 2026, 50,000-row sample** (DESNZ, published 11 Jun 2026) | **Backbone:** real property characteristics, real annual gas & electricity 2005–2024, real installs of cavity wall insulation, loft insulation and boilers with years | CSV 14.4 MB, `https://assets.publishing.service.gov.uk/media/6a282ad83b15d05a7ce31fb1/anon2026_50k.csv` · metadata ODS `https://assets.publishing.service.gov.uk/media/6a282d2be371d9d2c0052b39/NEED-2026-anonymised-dataset-metadata.ods` · page `https://www.gov.uk/government/statistics/national-energy-efficiency-data-framework-need-anonymised-data-2026` · **OGL v3.0**, no registration | **[E]** URL, size, years, licence verified |
| **DESNZ GHG conversion factors 2026** | Emission factors | `https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026` · OGL | Electricity **[E]** (verified in the official methodology report, Table 9); gas **[E?]** |
| **UK House Price Index, July 2026** (HM Land Registry) | Regional price levels for the synthetic current-value estimates | `https://www.gov.uk/government/news/uk-house-price-index-for-july-2026` · OGL | **[E]** |
| **DECC (2013) "An investigation of the effect of EPC ratings on house prices"** (Fuerst et al.) | Band price premiums (association) | `https://www.gov.uk/government/publications/an-investigation-of-the-effect-of-epc-ratings-on-house-prices` | **[E?]** headline figures via a university summary; confirm against the report |
| **Electrification of Heat Demonstration (interim)**, Energy Systems Catapult | ASHP seasonal performance (median SPF 2.80) | `https://es.catapult.org.uk/news/heat-pumps-shown-to-be-three-times-more-efficient-than-gas-boilers/` | **[E]** |
| **Ofgem price cap 1 Oct–31 Dec 2026** | Unit-rate ratio for the rating projection | `https://www.ofgem.gov.uk/energy-regulation/domestic-and-non-domestic/energy-pricing-rules/energy-price-cap` | **[E?]** |
| **Ofgem TDCV (from 1 Jul 2026)**: electricity 2,500, gas 9,500 kWh | Appliance-load cap for electrically heated homes | Ofgem summary of changes, 1 Jul–30 Sep 2026 | **[E]** |
| **SAP 2012 rating equations** (BRE) | Projected rating after retrofit (§6.3) | BRE SAP 2012 specification §13, eq. (257)–(258) | **[E?]** (ECF definition verified; constants checked by continuity at ECF = 3.5 → 51.2 on both branches) |
| *Not used in the base product:* EPC register (needs registration), London smart meter (10 GB, electricity only), Land Registry Price Paid (cannot be joined to EPC/NEED without credentials) | — | — | trade-offs A2–A4 |

> **Attribution (must appear in README, DATA_CARD and the `/about` page):** "Contains
> public sector information licensed under the Open Government Licence v3.0" (DESNZ
> NEED, DESNZ GHG factors, HM Land Registry UK HPI).

### 3.2 Pipeline

```
fetch_need ─► need_loader ─► (validate) ─► augment (seed 42) ─► split ─► build (parquet + SQLite)
     │ download fails & no committed copy
     └─► synthetic_fallback (same canonical schema; data_source = "synthetic_fallback", UI banner)
```

1. **fetch_need**: download the CSV and the ODS once to `data/raw/need/`, write a SHA-256
   file, and **commit them** (OGL allows redistribution with attribution) so later runs are
   offline. If the files already exist, verify the checksum and skip the download.
2. **need_loader**: read the ODS metadata → generate `need_code_map.json` (code → label
   for every coded field). Map NEED → canonical (§3.3). **If a column is renamed or
   absent, adapt the loader's column map, not the canonical schema, and record it in
   DATA_CARD.**
3. **validate**: rules in §3.5.
4. **augment**: synthetic fields (§3.4), every one with provenance `synthetic:<rule_id>`.
5. **split**: §3.6.
6. **build**: write `data/processed/*.parquet`, load SQLite, write `peer_benchmarks.json`
   and `calibration.json` (TRAIN only), then precompute results for every property
   (§9.3).

**Sample size:** the app DB holds a seeded random sample of `GREENIQ_SAMPLE_N`
(default **20,000**) eligible properties. **Calibration and evaluation always use all
eligible NEED rows.**

### 3.3 NEED → canonical mapping (real fields)

Expected NEED columns (names verified against DESNZ NEED documentation; code values
**must be confirmed from the 2026 metadata ODS**, with the expected codes from earlier
releases shown in brackets):

| NEED field | Canonical field | Rule |
|---|---|---|
| `HH_ID` | `property_id` | `"P" + HH_ID` |
| `REGION` | `region` | ONS region codes [E12000001 North East … E12000009 South West; W99999999 Wales] → 10 region names |
| `PROP_TYPE` | `property_type`, `built_form` | [101 Detached, 102 Semi, 103 End terrace, 104 Mid terrace, 105 Bungalow, 106 Flat] → `house/detached`, `house/semi_detached`, `house/end_terrace`, `house/mid_terrace`, `bungalow/detached`, `flat/null` |
| `PROP_AGE` | `age_band` | 6 bands [pre-1930, 1930–49, 1950–66, 1967–82, 1983–95, 1996+] |
| `FLOOR_AREA_BAND` | `floor_area_band` | [1: ≤50, 2: 51–100, 3: 101–150, 4: >150 m²] |
| `EE_BAND` | `epc_band` | [A/B grouped, C, D, E, F, G] → `AB, C, D, E, F, G` |
| `WALL_CONS` | `wall_type` | cavity → `cavity`; other → `solid` **[A-01]** |
| `CWI`, `CWI_YEAR` | `wall_insulation`, retrofit_history | cavity + CWI with year ≤ baseline year → `full`; cavity built 1983+ → `full` **[A-02]**; otherwise `none` |
| `LOFT_DEPTH` | `loft_depth_band` | <150 mm / ≥150 mm / unknown |
| `LI`, `LI_YEAR` | retrofit_history; loft_mm ≥ 270 if installed | **[A-03]** |
| `MAIN_HEAT_FUEL` + gas validity | `heating_system`, `main_fuel` | gas → boiler; other + off-gas (`Gcons…Valid = O`) + electricity ≥ 5,000 kWh → `electric_storage_heaters` **[A-04]**; other + electricity < 5,000 → **excluded** (presumed oil/LPG/solid; outside PS2's electricity + gas convention), counted in DATA_CARD |
| `BOILER`, `BOILER_YEAR` | `heating_system`, retrofit_history | gas boiler installed ≥ 2005 or age band 1996+ → `gas_condensing_boiler`, else `gas_noncondensing_boiler` **[A-05]** (condensing boilers became mandatory for new gas boilers in England & Wales from April 2005) |
| `Gcons{Y}`, `Gcons{Y}Valid` | `annual_energy(gas)` | baseline year **Y\*** = most recent year with ≥ 60% valid electricity rows (expected 2024). `V` → value; `O` → 0 (off-gas, genuinely zero); anything else → **missing** |
| `Econs{Y}`, `Econs{Y}Valid` | `annual_energy(electricity)` | `V` and 100 ≤ kWh ≤ 25,000 (NEED validity rule) → value; else **missing** |
| `IMD_*` | **not used** | excluded as a socio-economic proxy (Responsible AI) |

`annual_energy` keeps every valid year (needed for §6.5 calibration). The baseline is year
Y\*. Properties whose baseline energy is missing are **kept** (≈ the insufficient-data
path), up to 5% of the app sample.

### 3.4 Synthetic augmentation (seeded, disclosed, per-field provenance)

| Field | Rule | ID |
|---|---|---|
| `floor_area_m2` | uniform within band; band 4: 151 + Exponential(mean 45), capped at 400 | A-06 |
| `bedrooms` | flat: clip(round(area/30), 1, 3); other: clip(round(area/28), 1, 6) | A-07 |
| `floor_level` (flats) | ground 0.35 / mid 0.35 / top 0.30 | A-08 |
| `has_loft` | houses, bungalows, top-floor flats | derived |
| `loft_insulation_mm` | band <150: {0, 50, 100} p {0.15, 0.35, 0.50}; band ≥150: {150, 200, 270, 300} p {0.20, 0.30, 0.35, 0.15}; LI installed → max(270, value); unknown → null | A-09 |
| `floor_insulation` | ground-contact homes: age 1996+ → full p0.7 / partial 0.1 / none 0.2; older → none 0.85 / partial 0.10 / full 0.05; upper flats → `not_applicable` | A-10 |
| `glazing` | pre-1930: single 0.12, partial_double 0.10, double 0.76, triple 0.02; other ages: 0.03 / 0.05 / 0.88 / 0.04 | A-11 |
| `solar_pv_kwp` | houses/bungalows p = 0.06 → U{2.5, 3.0, 3.5, 4.0}; then the real annual electricity import is reduced by the modelled self-consumption (§6.2), floor 500 kWh, so the data stay consistent | A-12 |
| `controls` | condensing boiler: none .05, programmer .10, prog+stat .35, prog+stat+TRVs .40, smart .10; non-condensing: .15/.25/.35/.22/.03; storage heaters: none .30, programmer .70 (manual/auto charge control) | A-13 |
| `roof_suitable_for_solar` | houses/bungalows p 0.8; flats false | A-14 |
| `conservation_or_listed` | p 0.04 (pre-1930: 0.12) | A-15 |
| `customer_id` | 85% own one property; 15% grouped into owners with 2–5 properties, same region | A-16 |
| Monthly readings (baseline year) | `month_kwh = annual × profile[m] × (1 + N(0, 0.05))`, renormalised so the 12 months sum exactly to the real annual value; then 10% of properties lose k ∈ {1, 2, 3, 4} random months (MCAR) and 2% lose all of Dec–Feb gas | A-17 |
| `current_value_estimate_gbp` | `HPI_region × type_factor × (area/90)^0.7 × (1 + premium[band]) × LogNormal(0, 0.12)`, then rescaled so each region's mean equals its HPI average. type_factor: detached 1.45, semi 1.00, end/mid terrace 0.85, bungalow 1.15, flat 0.75. **Stored separately from sales history.** | A-18 |
| `sales_history` | 0/1/2/3 sales with p .35/.35/.20/.10 between 2010 and 2025; `price = value × index(year) × LogNormal(0, 0.10)`; index linear from 0.62 (2010) to 1.00 (2026) **[A-19]**; `epc_band_at_sale` = current band, or one band worse with p 0.5 if the sale preceded a recorded CWI/LI install | A-18/19 |

Synthetic labels follow published relationships (DECC premiums, HPI levels). **This makes
the value-model evaluation a pipeline validation, not real-world evidence**, and the
report must say so.

### 3.5 Validation and conflict rules (`validate.py`)

Each property gets `data_quality_flags: list[{code, severity, field, message}]`.

| Code | Rule | Effect |
|---|---|---|
| `MISSING_<FIELD>` | a required field is null | the affected score component becomes **unavailable** (§5.3); affected retrofits get `needs_survey` |
| `INSUFFICIENT_MONTHS_<FUEL>` | < 9 observed months, or gas with no Dec/Jan/Feb month | that fuel's annual value is unavailable → baseline from the ML estimate (§6.8), confidence Low |
| `OUTLIER_<FUEL>` | electricity > 25,000 or gas > 60,000 kWh/yr | treated as missing |
| `CONFLICT_HEATING_FUEL` | gas boiler but gas < 1,000 kWh/yr, or electric/heat-pump heating but gas > 3,000 kWh/yr | warning; confidence Low; explained in the UI |
| `CONFLICT_EPC_VS_USE` | band AB/C with intensity > 2.0 × peer median, or F/G with intensity < 0.4 × peer median | warning; confidence lowered |
| `CONFLICT_USE_VS_MODEL` | `abs(ln(actual/ML prediction)) > ln(2.5)` | warning |

No conflict ever silently changes an input. Conflicts are surfaced, explained and lower confidence.

### 3.6 Splits and leakage prevention

- `GroupShuffleSplit` on **`customer_id`** (seed 42): 70% train, then the remaining 30%
  split 50/50 into val/test. A customer, and therefore all their properties, belongs to
  exactly one split. Persist to `data/processed/splits.parquet`.
- Annual-energy, readings, sales and retrofit-history rows inherit their property's split.
- **Fitted on TRAIN only:** peer benchmarks, calibration factors, ML models, the value
  model and its bootstrap. **VAL:** sanity checks and report. **TEST:** final metrics,
  touched once by `evaluate.py`.
- **Prediction-time features only:** models never see consumption-derived fields,
  sales prices, future installs or `current_value_estimate_gbp`.

---

## 4. Canonical schema (`schema.py`, Pydantic v2, `extra="forbid"`)

```python
class Property(BaseModel):
    property_id: str; customer_id: str; label: str            # label e.g. "Semi-detached, North West (P12345)"
    region: Region; property_type: Literal["house","bungalow","flat"]
    built_form: Literal["detached","semi_detached","end_terrace","mid_terrace"] | None
    age_band: AgeBand; floor_area_band: Literal["le50","51_100","101_150","gt150"]
    floor_area_m2: float; bedrooms: int; floor_level: Literal["ground","mid","top"] | None
    epc_band: Literal["AB","C","D","E","F","G"] | None
    wall_type: Literal["cavity","solid"] | None
    wall_insulation: Literal["none","partial","full"] | None
    has_loft: bool; loft_insulation_mm: int | None
    floor_insulation: Literal["none","partial","full","not_applicable"] | None
    glazing: Literal["single","partial_double","double","triple"] | None
    heating_system: Literal["gas_condensing_boiler","gas_noncondensing_boiler",
                            "electric_storage_heaters","electric_direct","air_source_heat_pump"] | None
    main_fuel: Literal["mains_gas","electricity"]
    controls: Literal["none","programmer","programmer_thermostat",
                      "programmer_thermostat_trvs","smart_thermostat"] | None
    solar_pv_kwp: float                                        # 0 = none
    roof_suitable_for_solar: bool; conservation_or_listed: bool
    current_value_estimate_gbp: float | None                   # prediction-time baseline, NOT a sale price
    provenance: dict[str, str]                                 # field -> "need:<COL>" | "synthetic:A-xx" | "derived"
    data_source: Literal["need","synthetic_fallback","fixture"]

class MonthlyReading(BaseModel): property_id: str; month: str; electricity_kwh: float|None; gas_kwh: float|None
class AnnualEnergy(BaseModel): property_id: str; year: int; electricity_kwh: float|None; gas_kwh: float|None; source: str
class RetrofitHistory(BaseModel): property_id: str; retrofit_id: str; completion_year: int; source: str
class Sale(BaseModel): sale_id: str; property_id: str; sale_date: date; price_gbp: float; epc_band_at_sale: str
class Scenario(BaseModel): retrofit_ids: list[RetrofitId] = []; input_changes: list[InputChange] = []; text: str | None = None
```

Every engine output value is a **`Quantity`**: `{value: float|None, unit: str,
display: str, status: "ok"|"estimated"|"unavailable", reason: str|None,
receipt_id: str}`. **`ComputedFacts`** (§8.1) is the merged, immutable result of one
computation.

---

## 5. Green Home Score (`engines/score.py`)

### 5.1 Fixed weights (PS §2, exact)
`energy_efficiency 0.25 · consumption_intensity 0.20 · insulation 0.15 · heating 0.15 ·
glazing 0.10 · renewables 0.10 · smart_energy 0.05` (sum 1.00, asserted at import).

### 5.2 Sub-score mappings (all monotonic non-decreasing in "betterness")

| Component | Input | Mapping | Evidence |
|---|---|---|---|
| **Energy efficiency** | recorded `epc_band` only (baseline); projected SAP (scenario) | band → SAP-band midpoint: A 96, B 86, **AB 90.5**, C 74.5, D 61.5, E 46.5, F 29.5, G 10.5. Scenario: `clamp(projected_SAP, 1, 100)` (§6.3) | Official EPC band thresholds A ≥92, B 81–91, C 69–80, D 55–68, E 39–54, F 21–38, G 1–20 **[E]**; midpoint choice **[A-20]** |
| **Consumption intensity** | `I = (annual elec import + annual gas) / floor_area_m2` vs peer median `I_peer` | `r = I / I_peer`: r ≤ 0.5 → 100; 0.5–1.0 linear 100 → 50; 1.0–2.0 linear 50 → 0; ≥ 2.0 → 0 | Peer group = property-type group (detached, semi, terrace, bungalow, flat) × floor-area band, **TRAIN** medians; n < 30 → type-only; still < 30 → global **[A-21]**. Normalising by m² and peers keeps big homes from being penalised for size (PS §3). |
| **Insulation** | walls, loft, floor | element scores: walls none 0 / partial 50 / full 100; loft mm 0→0, 1–99→25, 100–149→50, 150–199→70, 200–269→85, ≥270→100; floor none 0 / partial 50 / full 100. Weighted walls 0.45, roof 0.35, floor 0.20, **renormalised over applicable elements** (no loft / upper flat = not applicable, which is not "missing") | 270 mm recommended loft depth (Energy Saving Trust guidance) **[E?]**; element weights **[A-22]** |
| **Heating** | `heating_system` | air_source_heat_pump 100 · gas_condensing_boiler 70 · gas_noncondensing_boiler 45 · electric_storage_heaters 30 · electric_direct 15 | Ordered by delivered-heat efficiency and carbon **[A-23]** |
| **Glazing** | `glazing` | single 0 · partial_double 40 · double 75 · triple 100 | **[A-24]** |
| **Renewables** | `solar_pv_kwp` | `100 × min(1, kWp / 4.0)` | 4 kWp typical domestic maximum **[A-25]** |
| **Smart energy management** | `controls` | none 0 · programmer 25 · programmer_thermostat 50 · programmer_thermostat_trvs 75 · smart_thermostat 100 | **[A-26]** |

**Double counting (justification, required by PS §2).** Energy efficiency uses only the
*recorded rating*. Intensity uses only *metered energy and floor area*. The other five
components use only *physical attributes*. No raw input field feeds two components.
The rating is itself derived from fabric and systems, so the components are correlated.
PS2 mandates both components with fixed weights, so the correlation is accepted and
disclosed.

### 5.3 Aggregation, missing data, rounding, classification
- Available components → `S = Σ wₖ sₖ`.
- **Missing component(s)** (input null): never imputed. Compute bounds
  `S_lo = Σ_avail wₖ sₖ` and `S_hi = S_lo + Σ_missing wₖ × 100`. `score_status =
  "partial"`. The reported score is the **range** `round(S_lo)–round(S_hi)`. Classification
  = the band if both ends fall in the same band, else **"Insufficient information"**,
  listing the missing inputs.
- **Rounding:** `round_half_up(x) = floor(x + 0.5)` (not Python banker's rounding).
  Classify the **rounded** integer.
- **Bands:** 80–100 Highly efficient · 65–79 Good · 50–64 Moderate · 30–49 Poor · 0–29 Very poor.
- **Explanation payload:** per component `{subscore, weight, contribution = w×s
  (1 dp), input values, mapping rule text, assumption IDs}`.

---

## 6. Energy, retrofit, savings, carbon (`engines/`)

### 6.1 Annualisation (`features.py`)
For fuel f over the observed months `M` of baseline year Y\*:
`A_f = Σ_{m∈M} x_m / Σ_{m∈M} p_f[m]`. **Valid only if |M| ≥ 9, and for gas M contains
Dec, Jan or Feb.** Otherwise unavailable (never zero-filled). With all 12 months present
this equals the plain sum (test). Profiles **[A-27]**:

```
gas  (Jan..Dec): .150 .130 .115 .080 .050 .035 .030 .030 .040 .075 .115 .150
elec (Jan..Dec): .095 .085 .088 .080 .077 .072 .073 .075 .076 .084 .090 .105
electrically heated homes: p = 0.4·elec + 0.6·gas
```
**Purchased energy** `E = A_elec_import + A_gas` (kWh/yr), the PS §3 convention, used
identically for baseline and after.

### 6.2 Deterministic energy model (`engines/energy.py`)
**Baseline end-use decomposition [A-28]:**
- *Gas-heated:* gas → space 0.75, hot water 0.22, cooking 0.03. Electricity demand
  `D = import + PV self-consumption` → appliances & lighting.
- *Electrically heated:* `D = import + PV self-consumption`; appliances = min(2,500 [E:
  Ofgem TDCV], 0.5·D); remainder → space 0.80 / hot water 0.20.
- **Efficiencies (delivered heat per kWh) [A-29]:** condensing gas 0.88; non-condensing
  0.72; storage/direct electric 1.00; **ASHP SPF 2.80 [E: EoH interim median]**. Useful
  heat `Q_space = fuel_space × η`, `Q_water = fuel_water × η`.

**Fabric heat-loss index [A-30]:**
`L = Σ_e share_e × U_e / U_ref_e + share_vent` with shares walls 0.35, roof 0.19,
windows 0.15, floor 0.10, ventilation 0.21, and

| Element | U by state (W/m²K) | U_ref |
|---|---|---|
| Walls | cavity none 1.5 · cavity partial 1.0 · cavity full 0.5 · solid none 2.0 · solid partial 1.15 · solid full 0.30 | 1.5 |
| Roof (loft mm) | 0: 2.3 · 1–99: 0.68 · 100–149: 0.40 · 150–199: 0.29 · 200–269: 0.21 · ≥270: 0.16 | 2.3 |
| Windows | single 4.8 · partial_double 3.3 · double 1.8 · triple 0.9 | 4.8 |
| Floor | none 0.7 · partial 0.45 · full 0.25 | 0.7 |
| Not applicable (party roof/floor in flats) | fixed ratio U/U_ref = 0.15 (not retrofittable) | — |

A fabric change scales space heat: `Q_space' = Q_space × L'/L`. Calibration (single
measure on an otherwise uninsulated home): loft 0→270 mm ≈ 17.7% space-heat reduction;
single→double glazing ≈ 9.4%, consistent with the PS §4 illustrative ranges (12–18%,
8–12%). Unknown elements use the "none" state for the *baseline index only* and mark the
affected savings `estimated`.

**Measures (applied to the evolving state, in plan order):**

| Measure | Effect |
|---|---|
| loft / cavity / solid wall / floor / glazing | update U_e → `Q_space × L'/L` |
| smart thermostat | `Q_space × (1 − c)`, c by current controls: none 0.10, programmer 0.08, programmer_thermostat 0.06, +TRVs 0.05 (PS §4 range 5–10%) **[A-31]** |
| air-source heat pump | space and hot-water fuel → electricity = `(Q_space + Q_water) / 2.80`; gas space/water → 0 (cooking gas remains) |
| solar PV (default 3.5 kWp; 2.5 if floor area < 70) | generation `G = kWp × yield[region]` **[A-32]** (kWh/kWp/yr: SW 1000, SE 980, London 950, East 950, E Mids 920, W Mids 900, Wales 900, Yorks 870, NW 860, NE 850); import reduction = `min(0.25 G, 0.35 × electricity demand after earlier measures)` **[A-33]** (never more than 35% of demand; a typical 2,500–4,000 kWh home lands at ≈20–32%, inside the PS 20–35% range; export is not "purchased energy") |

Fuel after = useful heat / η of the (possibly new) system; electricity = appliances +
electric heating − PV self-consumption. **Every output is per fuel.**

### 6.3 Rating projection (`engines/rating.py`)
`SAP0` = band midpoint (§5.2). Invert SAP 2012: if `SAP0 ≥ 51.18` then `ECF0 = (100 −
SAP0)/13.95`, else `ECF0 = 10^((117 − SAP0)/121)`. Cost ratio `ρ = cost_after /
cost_before`, with `cost = 26.32p × elec_import + 7.97p × gas` (Ofgem cap unit rates
Oct–Dec 2026 [E?]; standing charges and PV export income excluded **[A-34]**).
`ECF1 = ECF0 × ρ`; `SAP1 = 100 − 13.95·ECF1` if `ECF1 < 3.5`, else `117 −
121·log10(ECF1)`; clamp to [1, 100]; projected band from the thresholds. The deflator
cancels, so only the functional form matters. Label it "projected rating (estimate)".

### 6.4 Retrofit catalogue, feasibility, suitability, order (`engines/retrofit.py`)

`retrofit_catalogue.json` (costs are **indicative order-of-magnitude [A-35]**, not quotes):

| id | Applicable when (all true) | Base suitability | Group | Indicative cost |
|---|---|---|---|---|
| `loft_insulation` | `has_loft` and loft_mm < 270 | High if < 100; Medium 100–199; Low 200–269 | 1 fabric | £300–£800 |
| `cavity_wall_insulation` | wall_type = cavity and insulation ∈ {none, partial} | High (none) / Medium (partial) | 1 | £1,000–£3,000 |
| `solid_wall_insulation` | wall_type = solid and insulation ∈ {none, partial} | Medium; Low if conservation/listed | 1 | £8,000–£20,000 |
| `floor_insulation` | ground-contact home and floor ∈ {none, partial} | Medium | 1 | £1,500–£4,000 |
| `double_glazing` | glazing ∈ {single, partial_double} | High (single) / Medium (partial); Low if conservation/listed | 1 | £5,000–£12,000 |
| `smart_thermostat` | wet central heating (gas boiler or heat pump) and controls ≠ smart | High if ≤ programmer, else Medium | 2 controls | £150–£300 |
| `air_source_heat_pump` | heating ≠ heat pump | High if insulation sub-score *after planned fabric measures* ≥ 50, else Medium ("insulate first"); flats → `needs_survey` | 3 heating | £8,000–£14,000 before grants |
| `solar_pv` | house/bungalow, `roof_suitable_for_solar`, kWp = 0 | High; Medium if conservation/listed | 4 generation | £5,000–£7,500 |

- **Status:** `recommended` · `needs_survey` (required input unknown, or the flat heat-pump
  case) · `not_applicable` (with reason) · `already_installed`.
- **Downgrade:** a measure whose *individual* purchased-energy saving is < 2% of baseline
  drops one suitability level (floor Low).
- **Recommended package** = status `recommended` with suitability High or Medium.
- **Order:** group 1 → 2 → 3 → 4 (fabric before heat pump, per PS §4); within a group,
  sort by individual saving, largest first.
- **Interaction notes** are deterministic strings, e.g. "Insulating first reduces the heat
  the heat pump must supply, so its electricity use is lower than if installed alone."

### 6.5 Savings (`engines/savings.py`) and calibration
- **Individual:** `ΔE_f[m] = E_f(base) − E_f(base + {m})`, per fuel.
- **Package:** apply the ordered measures sequentially. Marginal `ΔE_f[m_k] =
  E_f(after k−1) − E_f(after k)`. Package total = `E_f(base) − E_f(after all)` (= sum of
  marginals). **Interaction effect** = Σ individual − package, shown per fuel.
- **Sign:** `ΔE_f = baseline − after`. Negative = increase, displayed "−1,240 kWh
  (increase)". It is never dropped or absolute-valued.
- **In-use calibration (real data, TRAIN only) [E method / A-36 assumptions]:** for NEED
  homes with a CWI (or LI) install in year y ∈ [2008, Y\*−1] and valid gas in y−1 and y+1:
  observed saving `s_i = (G_{y−1} − G_{y+1}) / G_{y−1}`. Control change `c` = median of the
  same ratio over non-installers (no CWI/LI/boiler in y−1..y+1) in the same region ×
  property type × age band × year. DiD saving = median(s_i) − c. The engine's predicted
  saving for the same homes uses the pre-install state (cavity none; loft 50 mm assumed
  pre-LI **[A-36]**). `k_CWI = observed / predicted`, `k_LI` likewise, each clipped to [0.2,
  1.2]. `k_fabric` = installer-weighted mean, applied to all fabric measures' space-heat
  reductions. If there are < 50 installers, k = 1 and the flag is recorded. Results and
  bootstrap 90% CIs go in `calibration.json` and the eval report. **The UI shows the
  calibrated saving and the receipt shows both.**
- **Display:** kWh to the nearest 10, % to the nearest 1, always labelled "estimate".
- **Confidence:** High (metered baseline ≥ 11 months, no conflicts) · Medium (9–10 months,
  or any `estimated` element) · Low (ML-estimated baseline, or any conflict flag).

### 6.6 Poor performers and ranking (`engines/ranking.py`)
- **Improvement potential** `IP = 100 × (E_base − E_after_package) / E_base` (§6.1
  convention). `E_base` unavailable → IP unavailable ("no reliable metered baseline");
  `E_base = 0` → unavailable ("zero purchased energy"). Also report `ΔE_elec`, `ΔE_gas`.
- **Flagged** = classification Poor or Very poor (a determinable score). **Key issues**
  (rules): intensity ratio > 1.3 → "High energy use per m² (r× typical for similar
  homes)"; insulation sub-score < 50 → "Poor insulation: {elements}"; heating ∈
  {non-condensing, storage, direct} → "Inefficient heating system"; glazing ∈ {single,
  partial} → "Single glazing"; no PV → "No renewable generation"; controls ≤ programmer →
  "Basic heating controls".
- **Ranking:** flagged homes by IP descending, ties by |package ΔE| descending; homes
  with unavailable IP are listed after them with reasons.

### 6.7 Carbon (`engines/carbon.py`, `carbon_factors.json`)
```json
{"electricity": {"kg_co2e_per_kwh": 0.13096, "basis": "UK electricity, generation, location-based (Scope 2)",
                 "source": "DESNZ GHG conversion factors 2026", "verified": "official methodology report, Table 9"},
 "gas":         {"kg_co2e_per_kwh": 0.18231, "basis": "Natural gas, kWh gross CV (Scope 1)",
                 "source": "DESNZ GHG conversion factors 2026", "verified": "secondary sources; confirm in condensed set"},
 "include_td_losses": false, "td_losses_kg_co2e_per_kwh": 0.01299}
```
`ΔC_kg = ΔE_elec × EF_elec + ΔE_gas × EF_gas`. Positive = reduction. Report the baseline
emissions, the after emissions, the per-fuel contributions and the net. Display t CO₂e
to 1 dp and kg to the nearest 10. If the gas row cannot be confirmed during the build,
keep 0.18231 and mark the fact `verified=false` in `/api/meta`.

### 6.8 ML baseline energy model (`engines/baseline_ml.py`, `train.py`)
- **Purpose:** (a) estimate a baseline when the metered annual value is unavailable
  (flag `estimated`, confidence Low); (b) the `CONFLICT_USE_VS_MODEL` check; (c) the
  PS-suggested regression component, evaluated on **real** held-out NEED data.
- **Model:** one `HistGradientBoostingRegressor` per fuel on `log1p(annual kWh)`
  (`max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=50,
  l2_regularization=1.0, random_state=42`). Gas model on gas-heated homes only.
- **Features (real NEED, prediction-time only):** region, property-type group, age band,
  floor-area band, EPC band, wall type, CWI installed by Y\*, loft-depth band, main fuel,
  condensing boiler.
- **Baseline to beat:** TRAIN peer median (type × floor band × age band).
- **Interval:** VAL residual ratio 10th/90th percentiles → an interval for estimated
  baselines.

---

## 7. Property-value impact (`engines/value.py`)

- **Hedonic model (the uplift):** OLS on `ln(price)` over **TRAIN** sales with region
  dummies, property-type dummies, `ln(floor_area)`, age-band dummies, sale-year dummies
  and **EPC-band-at-sale dummies (G = reference)**. Bootstrap B = 200 (seed 42,
  resampling properties) → the distribution of each band coefficient.
- **Uplift for a scenario:** `Δ = β[band_after] − β[band_before]` (projected band, §6.3).
  The range is the bootstrap 5th–95th percentile of `exp(Δ) − 1`, plus a point estimate
  from the full fit. £ range = `current_value_estimate × (1 + lo … 1 + hi)`, rounded to
  the nearest £1,000. Unchanged band → "no band change projected: no indicative value
  change". Missing `current_value_estimate` → % range only, with the reason.
- **Price-level model (evaluation + missing-value fallback):** HGBR with
  `loss="quantile"` at q = 0.1/0.5/0.9 on the same features. TEST: MAPE and 80%-interval
  coverage vs a baseline (regional HPI × type factor).
- **Mandatory wording** (UI, explanations, report): *"Indicative estimate based on
  historical and market relationships in our prepared dataset (synthetic sales calibrated
  to UK HPI July 2026 and published EPC-band price associations, DECC 2013). It is an
  association, not a proven causal effect of the retrofit, and not a valuation."*
- **Generator premiums** `value_premiums.json` (relative to G) [E?]: F 0.06, E 0.06, D
  0.08, C 0.10, AB 0.14.

---

## 8. LLM explanation and what-if (`llm/`)

### 8.1 The facts registry (`facts.py`), the only thing the LLM sees
`ComputedFacts.facts: dict[fact_id, Fact]`, where `Fact = {id, label, value, unit,
display, kind: "computed"|"input"|"assumption"|"constant", receipt_id}`. `display` is the
exact string the UI shows. IDs are dotted and stable, for example `score.total`,
`score.range_low`, `score.band`, `score.component.insulation.subscore`,
`score.component.insulation.contribution`, `energy.baseline.electricity_kwh`,
`energy.baseline.gas_kwh`, `retrofit.loft_insulation.individual.gas_kwh`,
`package.delta.electricity_kwh`, `package.improvement_potential_pct`,
`carbon.package.reduction_t`, `carbon.factor.electricity`, `value.uplift.pct_low`,
`value.uplift.gbp_high`, `scenario.delta.gas_kwh`, and structural constants
(`constant.score.max` = 100, `constant.weight.insulation` = 15%,
`constant.band.poor` = "30–49").

### 8.2 Model calls (structured outputs only; no free-text parsing)
- **Model:** env `GREENIQ_LLM_MODEL`, default **`claude-opus-5-5`**, with
  `output_config={"effort": "low"}` (explanations are simple; effort is the cost
  lever). `max_tokens=4000`, timeout 30 s, `max_retries=2`.
- **Mechanism (one call shape):**
  ```python
  resp = client.beta.messages.create(
      model=settings.llm_model, max_tokens=4000, system=SYSTEM_PROMPT,
      messages=[{"role": "user", "content": facts_view_json_plus_question}],
      output_config={"effort": "low",
                     "format": {"type": "json_schema", "schema": Model.model_json_schema()}},
      betas=["server-side-fallback-2026-07-01"], fallbacks="default",   # refusal fallback
  )
  if resp.stop_reason == "refusal": -> template
  text = next(b.text for b in resp.content if b.type == "text"); out = Model.model_validate_json(text)
  ```
  The schemas use `extra="forbid"` (`additionalProperties: false`) with all fields
  required. **Do not use forced `tool_choice`: it returns HTTP 400 on Claude Opus 5.5.**
  Structured outputs are the supported mechanism. If the API rejects the fallbacks beta
  together with `output_config.format`, call `client.messages.create` without
  `betas`/`fallbacks`, keep structured outputs, and record it in `docs/DECISIONS.md`. On
  any exception, invalid JSON or refusal → **template**.
- **Mode:** `GREENIQ_NARRATOR=auto|template|anthropic`. `auto` → anthropic if credentials
  resolve, else template. **The app is fully functional in template mode.**

**Call 1, `explain`**: input = facts view (`id, label, display, unit` only, never raw
floats) + optional user question + the property's catalogue status list. Output:
```python
class Sentence(BaseModel): text: str; fact_ids: list[str]
class Section(BaseModel):  topic: Literal["score","improvements","savings","carbon","value","data_quality","scenario_change"]; sentences: list[Sentence]
class ExplanationOut(BaseModel): answer_type: Literal["explanation","insufficient_information"]; headline: Sentence; sections: list[Section]
```
**Call 2, `parse_scenario`** (only when the user types free text): output
`ScenarioProposalOut {retrofit_ids: list[RetrofitId enum], input_changes:
list[{field: EditableField enum, value: str}], unrecognised: list[str]}`. Template mode
uses a deterministic synonym matcher (e.g. "heat pump|ASHP" → `air_source_heat_pump`).

**System prompt (`prompts.py`, verbatim intent):** *"You explain a home-energy assessment
that has already been calculated. Use ONLY the facts provided. Every sentence that states
a number, a rating, a recommendation or a comparison must list the fact_ids it relies on,
and must use the numbers exactly as written in each fact's display string. Never
calculate, estimate, round differently, extrapolate or introduce any figure. Call
savings, carbon and value figures estimates. Never say a value increase is guaranteed or
caused by a retrofit; it is an indicative association. If the facts cannot answer the
question, set answer_type to insufficient_information and say what is missing."*

### 8.3 Verifier (`verifier.py`), structured grounding, not naive matching
For each sentence (including the headline):
1. Every cited `fact_id` exists in the facts sent → else **UNKNOWN_REFERENCE**.
2. Every numeric token in the text (normalise £, commas, %, "t", "kWh") must equal the
   number in the `display` of **one of the sentence's own cited facts** (exact match on
   the displayed number) → else **UNSUPPORTED_NUMBER**. A number matching some *other*
   fact still fails, because citations bind.
3. A sentence with a number or a named retrofit/component but **no citations** →
   **UNCITED_CLAIM**.
4. Named retrofits/components must appear among the cited facts' entities → else
   **UNSUPPORTED_ENTITY**.
5. Forbidden claims (regex, case-insensitive): `guarantee(d|s)?`, `definitely`,
   `proven`, `will (increase|raise|boost) (the |your )?(home |property )?value`,
   `certain(ly)?` → **FORBIDDEN_CLAIM**.

Assembly: drop failing sentences. If the headline fails, > 20% of sentences fail, or any
section empties → **full template fallback**. The response carries `grounding = {mode:
"llm"|"template", sentences_total, sentences_supported, dropped:[{text, reason}]}` and the
UI shows "Verified: n/n statements traced to calculations". Template output uses the same
`Sentence` structure and must pass the verifier (test).

### 8.4 What-if (`POST /api/properties/{id}/scenarios`)
1. **Resolve the request:** explicit `retrofit_ids` / `input_changes`, or `text` →
   `parse_scenario`.
2. **Validate:** ids exist; feasibility for this property (§6.4) → infeasible items go to
   `rejected[]` with reasons and are **not applied**. Editable fields (`glazing`,
   `heating_system`, `controls`, `solar_pv_kwp` 0–10, `loft_insulation_mm` 0–400,
   `wall_insulation`, `floor_insulation`) are domain-checked. Contradictions (e.g. a heat
   pump plus `heating_system` set to a gas boiler; solar on a flat) → rejected with a
   reason. If nothing valid remains → HTTP 422 `INFEASIBLE_SCENARIO` with the reasons.
3. **Recompute** the full pipeline on the scenario state → new `ComputedFacts`.
4. **Diff** key outputs (score, band, sub-scores, per-fuel kWh, IP, carbon, projected
   band, value range) → `scenario.delta.*` facts.
5. **Explain** the diff (§8.2–8.3).
6. **Persist** the scenario and return `ScenarioResult {scenario_id, applied, rejected,
   before, after, delta, explanation, grounding, warnings}`. A calculation exception →
   HTTP 500 `CALCULATION_FAILED`, with no explanation generated.

---

## 9. Backend API (`api/`), storage, precompute

### 9.1 Routes (all JSON, prefix `/api`)

| Method | Route | Response |
|---|---|---|
| GET | `/health` | `{status, data_source, narrator_mode, engine_version, models_loaded}` |
| GET | `/meta` | provenance: datasets (url, licence, sha256, retrieved_at), factors (+ verified flags), assumption register (A-01…), split counts, eval headline metrics (from `reports/metrics.json` if present), limitations |
| GET | `/portfolio/summary` | counts by band, mean score, partial-score count, flagged count, score histogram (10-point bins), totals: baseline elec/gas kWh and tCO₂e, package savings elec/gas kWh and tCO₂e, breakdowns by region and property type |
| GET | `/properties` | query `q, region, property_type, band, flagged, sort (score|ip|intensity), order, page, page_size≤100` → `{items: PropertySummary[], total}` |
| GET | `/properties/{id}` | `PropertyDetail {property, data_quality_flags, annual_energy, monthly_readings}` |
| GET | `/properties/{id}/report` | `PropertyReport` = ComputedFacts structured: score (+ components, status, range), classification, issues, plan (recommended, needs_survey, not_applicable), savings (individual, package, interaction), carbon, value, confidence, receipts |
| GET | `/properties/{id}/explanation?question=` | `ExplanationResponse {explanation, grounding, mode}` |
| POST | `/properties/{id}/scenarios` | body `Scenario` → `ScenarioResult` |
| GET | `/properties/{id}/scenarios` | saved scenarios |
| GET | `/rankings/poor-performing` | `limit, offset, region` → ranked list `{rank, property summary, ip_pct, delta_elec_kwh, delta_gas_kwh, issues, status}` |
| GET | `/properties/{id}/peers` | percentile of intensity and score within the peer group |
| GET | `/catalogue` | the retrofit catalogue |

**Errors:** `{error: {code, message, details}}`, codes `NOT_FOUND` (404),
`VALIDATION_ERROR` (422), `INFEASIBLE_SCENARIO` (422), `CALCULATION_FAILED` (500).
Insufficient data is **not** an error: outputs carry `status: "unavailable"` +
`reason`. LLM failure is never an error (template).

### 9.2 Tables (`tables.py`)
`properties` (canonical columns + `provenance` JSON + `data_quality_flags` JSON) ·
`annual_energy` · `monthly_readings` · `retrofit_history` · `sales` · `splits` ·
`property_results` (property_id, engine_version, score, score_lo, score_hi, status, band,
ip_pct, delta_elec, delta_gas, delta_co2_kg, flagged, issues JSON, report JSON,
computed_at) · `scenarios` (id, property_id, request JSON, result JSON, created_at).
Indexes on region, property_type, band, flagged, ip_pct.

### 9.3 Precompute
`precompute.py` runs `analyse_property` for every property → `property_results`.
List/portfolio/ranking routes read precomputed rows. `/report` recomputes on demand
(fast, deterministic) and must equal the precomputed row (test).

---

## 10. Configuration (`.env.example`)
```
ANTHROPIC_API_KEY=                 # optional; template mode without it
GREENIQ_NARRATOR=auto              # auto | template | anthropic
GREENIQ_LLM_MODEL=claude-opus-5-5
GREENIQ_LLM_EFFORT=low
GREENIQ_LLM_TIMEOUT_S=30
GREENIQ_SAMPLE_N=20000             # 0 = all eligible
GREENIQ_SEED=42
GREENIQ_DB_PATH=data/greeniq.db
GREENIQ_DATA_SOURCE=auto           # auto | need | synthetic_fallback
CORS_ORIGINS=http://localhost:5173
```

## 11. Frontend (screens, behaviour, data)

All numbers come from the API. Use backend `display` strings where provided. **No
hard-coded figures.** Every estimate shows an "estimate" tag. Clean, light theme with a
green accent; accessible contrast; responsive down to 375 px.

| Route | Screen | Content | API |
|---|---|---|---|
| `/` | **Portfolio dashboard** | data-source banner; KPI cards (properties, mean score, % Poor/Very poor, baseline MWh and tCO₂e, package savings elec/gas MWh and tCO₂e); band distribution chart; score histogram; region and type breakdown tables | `/portfolio/summary`, `/health` |
| `/properties` | **Search & select** | search (id, label), filters (region, type, band, flagged), sortable paginated table → row opens detail | `/properties` |
| `/rankings` | **Poor-performing ranking** | rank, property, band, score, IP %, **ΔE electricity and ΔE gas in separate columns**, issue chips, unavailable reasons | `/rankings/poor-performing` |
| `/properties/:id` | **Property detail** | score gauge + band + status/range + confidence + data-quality warnings; **7-component breakdown** (contribution vs weight; click → receipt drawer: inputs, rule, source, assumption IDs); **recommendations** (ordered cards: suitability, status, individual and in-package saving per fuel, cost range, reason, interaction note) + not-applicable/needs-survey lists; **savings & carbon** (baseline vs after bars per fuel, individual vs package table with interaction effect, carbon card with factor + source); **value range** (bar, £ and %, mandatory wording); **explanation panel** (mode badge, verified n/n, ask-a-question box); peers | `/properties/{id}`, `/report`, `/explanation`, `/peers` |
| `/properties/:id/what-if` | **Scenario builder** | feasible retrofit checklist (infeasible ones disabled with reasons), editable inputs, free-text box, Run → **before/after comparison** (score, band, sub-scores, per-fuel kWh, IP, carbon, projected band, value range) with deltas; rejected items with reasons; grounded explanation; saved scenarios | `POST/GET /scenarios`, `/catalogue` |
| `/about` | **Data, provenance & limitations** | datasets + licences + checksums, emission factors (+ verified flags), assumption register, splits, eval headline metrics, limitations, Responsible-AI summary | `/meta` |

---

## 12. Testing and evaluation

### 12.1 Automated tests (pytest; names are binding)
| Test | Proves |
|---|---|
| `test_weights_exact_and_sum` | the 7 weights equal PS values, sum 1 |
| `test_aggregation_matches_manual` | S = Σ w·s on fixtures |
| `test_subscores_monotonic` (hypothesis) | improving any single input never lowers its sub-score or S |
| `test_classification_boundaries` | 29/30, 49/50, 64/65, 79/80 boundaries; round-half-up (29.5 → 30) |
| `test_missing_component_bounds` | partial score range; "Insufficient information" when bands differ |
| `test_annualisation_full_year_equals_sum` / `_missing_months` / `_no_winter_gas_unavailable` | §6.1 |
| `test_purchased_energy_convention` | E = grid import + gas for both baseline and after |
| `test_split_integrity` | no property_id/customer_id in two splits; child rows follow |
| `test_no_leakage_features` | model feature lists exclude consumption, sales, value, future installs |
| `test_infeasible_retrofit_rejected` | loft on a mid-floor flat, solar on a flat, PV already present |
| `test_package_not_sum_and_marginals_telescope` | interactions; Σ marginals = package |
| `test_heat_pump_raises_electricity` | gas-boiler home + ASHP → ΔE_elec < 0, ΔE_gas > 0, net carbon per §6.7 |
| `test_fabric_ranges_match_ps` | loft 0→270 within 12–18%; glazing within 8–12% (uncalibrated) |
| `test_ip_unavailable_zero_or_missing_baseline` | §6.6 |
| `test_large_home_not_penalised` | scaled home with equal intensity gets equal intensity sub-score and IP |
| `test_carbon_factors_and_units` | ΔC from fixed ΔE values equals the hand calculation |
| `test_value_range_ordered_and_wording` | lo ≤ point ≤ hi; unchanged band → no change; wording present |
| `test_rating_projection_continuity_and_monotonic` | SAP inversion round-trip; lower cost → higher SAP |
| `test_whatif_recompute_consistency` | scenario facts equal a direct pipeline run on the modified home |
| `test_verifier_*` | accepts a grounded sentence; rejects an invented number, a number cited to the wrong fact, an uncited claim, an unknown fact id, a forbidden claim |
| `test_template_explanations_pass_verifier` | on all golden homes |
| `test_api_contract` | every route returns its schema on golden homes; error format |
| `test_precompute_matches_report` | §9.3 |

**Golden homes** (`tests/fixtures/golden_homes.json`, `data_source="fixture"`): G1 the
PS-style poor home (semi, band E, cavity unfilled, loft 50 mm, non-condensing boiler,
single glazing, no PV, programmer only, gas 15,000 / elec 4,000 kWh, 85 m²) → Poor or Very
poor, plan ordered fabric → controls → heat pump → solar; G2 efficient (band AB, full
insulation, ASHP, triple glazing, 4 kWp, smart) → Good or better; G3 a large 250 m²
detached home with intensity equal to G1-like peers (fairness); G4 a mid-floor flat (loft
and solar not applicable; heat pump `needs_survey`); G5 missing data (glazing and
controls null; 6 gas months) → score range + ML baseline; G6 conflict (heat pump with
12,000 kWh gas); G7 heat-pump switch scenario; G8 zero purchased energy → IP unavailable.

**Frontend:** Vitest renders each screen against fixtures exported from the real API
(`python -m greeniq.cli export-fixtures`); `npm run build` must succeed. **Smoke:**
`python -m greeniq.cli smoke` calls every route for G1–G8 and three sampled NEED homes,
including one scenario, and checks the built UI is served at `/`.

### 12.2 Evaluation (`evaluate.py` → `reports/`), never typed by hand
| Area | Metric | Baseline | Data |
|---|---|---|---|
| Energy (per fuel) | MAE kWh, median APE, R² (log), on TEST | TRAIN peer median | **real NEED** |
| Savings: CWI and LI | DiD observed median saving (TEST installers) vs engine calibrated and uncalibrated predictions; absolute error in pp; bootstrap CI | PS illustrative midpoint (loft 15% of space heat) and uncalibrated engine | **real NEED** |
| Annualisation | error vs known real annual totals after the synthetic month removal | naive sum × 12/n | real totals, synthetic gaps |
| Ranking | Spearman between IP rank and intensity rank; share of flagged homes with ≥ 1 recommended measure | intensity-only ranking | app sample |
| Score | distribution by band; monotonicity results; G1 outcome | — | app sample |
| Value | price MAPE, 80% coverage (TEST sales); band-premium recovery vs generator | regional HPI × type factor | **synthetic: labelled pipeline validation** |
| LLM | template mode: verifier pass rate (expect 100% by construction; stated as such). If an LLM run happens: grounded % (supported/total), numeric accuracy % (numbers matching cited facts / numeric claims), unsupported % pre-gate and delivered; plus a 30-sentence human-audit sheet (`reports/llm_audit.md`) | ungated LLM output | fixed set: G1–G8 × 4 customer questions + 5 adversarial prompts |

`holdout_predictions.csv` (TEST): property_id, split, actual and predicted elec/gas, peer
baseline elec/gas, score, band, ip_pct, package ΔE elec/gas, ΔC kg, value uplift pct
lo/hi. Schema in `holdout_predictions.schema.json`.

---

## 13. Commands (one-command paths)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt && pip install -e backend
npm --prefix frontend ci
python -m greeniq.cli all     # fetch → build data → train → precompute → build UI → eval → tests summary
python -m greeniq.cli serve   # http://localhost:8000  (UI + API; template mode without a key)
```
Sub-commands: `fetch, build-data, train, precompute, eval, test, smoke, export-fixtures,
build-ui, serve, all`. The Makefile mirrors them.

## 14. Generated documentation (submission SR-A…SR-I)
`README.md` (run, reproduce, architecture link, attribution, honest current state) ·
`data/DATA_CARD.md` (sources, licences, checksums, schema, mapping, augmentation
rules A-xx, exclusions with counts, splits, labels, limitations) ·
`docs/SCORING_METHODOLOGY.md` (§5 tables + justification) · `docs/LLM.md` (model,
prompts verbatim, schemas, verifier, modes, eval approach) · `docs/ARCHITECTURE.md`
(adapted from 03, plus the poster) · `docs/RESPONSIBLE_AI.md` (from 07 §4, updated with
the real data and exclusions) · `docs/DECISIONS.md` (minor build decisions) ·
`reports/*` (§12.2) · `reports/test_results.txt` (actual pytest/vitest output).

## 15. Assumption register (must appear in `/api/meta` and DATA_CARD)
A-01 … A-36 as defined inline above. Each entry: id, statement, value(s), rationale,
where used, how to change it (config key).
