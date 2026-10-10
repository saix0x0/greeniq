# Green Home Score: scoring method (submission artifact D)

> Code: [`greeniq/score.py`](../greeniq/score.py) · tables: [`greeniq/config/score_mappings.py`](../greeniq/config/score_mappings.py)
> · input defaults: [`greeniq/features/resolve.py`](../greeniq/features/resolve.py) · tests: [`tests/test_score.py`](../tests/test_score.py)
> · mapping version `score-mappings/1.1`

## 1. Formula (fixed by PS2)

**S = Σ wₖ · sₖ**, each sub-score sₖ ∈ [0, 100], weights fixed and summing to 1:

| Component | Weight | Input |
|---|---|---|
| Energy efficiency | **25%** | Recorded EPC rating (SAP score; band midpoint if only the letter is known) |
| Energy consumption intensity | **20%** | Annualised purchased energy (grid electricity imported + gas) per m² |
| Insulation | **15%** | Walls, loft and floor insulation |
| Heating system | **15%** | Heating system type, and boiler age for gas boilers |
| Windows and glazing | **10%** | Glazing type |
| Renewable energy | **10%** | Installed solar PV capacity (kWp) |
| Smart energy management | **5%** | Heating controls |

The final score is **rounded half up** to an integer (64.5 → 65; Python's built-in
`round` would give 64, so we don't use it). The band comes from the rounded score:

| Score | Band |
|---|---|
| 80–100 | Highly efficient |
| 65–79 | Good |
| 50–64 | Moderate |
| 30–49 | Poor |
| 0–29 | Very poor |

Every component reports its **raw input, sub-score, weight, contribution (wₖ·sₖ) and
"points available" (wₖ·(100 − sₖ))**. Points available is how much of the score that
component is holding back; issues are ranked by it.

## 2. Sub-score mappings

All mappings are **monotonic by construction**: numeric inputs use piecewise-linear
interpolation through monotone knots (clamped at the ends); categorical inputs use
ladders ordered worst → best with non-decreasing scores. Property-based tests
(Hypothesis) check that improving any single input never lowers the total score.

### Energy efficiency (25%)
SAP is already a 0–100 efficiency scale, so **sₖ = clamp(SAP, 0, 100)**. A SAP above
100 (a net exporter) scores 100. If only the band letter is recorded, we use the band's
SAP midpoint: G 10.5 · F 29.5 · E 46.5 · D 61.5 · C 74.5 · B 86 · A 96 (official
thresholds A ≥ 92, B 81–91, C 69–80, D 55–68, E 39–54, F 21–38, G 1–20).
With no recorded rating, the rating is *estimated* by the rating model and the
component is marked **estimated**.

### Energy consumption intensity (20%)
Purchased energy per m² per year → sub-score, decreasing:

| kWh/m²/yr | ≤ 40 | 100 | 150 | 200 | 275 | 400 | ≥ 500 |
|---|---|---|---|---|---|---|---|
| sub-score | 100 | 80 | 63 | 47 | 28 | 5 | 0 |

Anchor: a typical UK dual-fuel home (Ofgem TDCV 11,500 kWh gas + 2,700 kWh electricity)
of about 90 m² uses ≈158 kWh/m² and scores ≈60. **Because the input is per m², a large
home is never marked down for its size alone** (tested). Peer comparison ("homes like
yours") is shown separately as insight, not mixed into the score.

### Insulation (15%)
Weighted average of up to three elements (walls 50%, loft 35%, floor 15%). Elements that
**do not apply** are dropped and the rest renormalised: a ground- or mid-floor flat has no
loft, and a mid- or top-floor flat has no ground floor, so neither is penalised for them.

| Walls | uninsulated | insulated |
|---|---|---|
| Solid | 0 (U≈2.1) | 90 (U≈0.3) |
| Cavity | 30 (U≈1.5) | 80 (U≈0.5) |

| Loft depth (mm) | 0 | 25 | 50 | 100 | 150 | 200 | ≥ 270 |
|---|---|---|---|---|---|---|---|
| sub-score | 0 | 10 | 25 | 55 | 75 | 90 | 100 |

Floor: uninsulated 0, insulated 100.

### Heating system (15%)
| System | Score |
|---|---|
| Direct electric | 15 |
| Non-condensing gas boiler | 30 |
| Electric storage heaters | 40 |
| Condensing gas boiler | 62 |
| Air source heat pump | 92 |
| Ground source heat pump | 100 |

A single ordering is a judgement between running cost and carbon, so we state it:
heat pumps lead on both; condensing gas is cheap to run but fossil; storage heaters are
grid-carbon but expensive; non-condensing boilers waste 20–30% of their fuel; direct
electric is the most expensive heat. Gas boilers lose up to 12 points with age (0 up to
10 years, 10 at 20 years, 12 at 30+). **Rungs never overlap**: the oldest boiler on a rung
still scores above the rung below. A property-based test found an overlap in an earlier
draft (direct electric at 20 beat a 21-year-old non-condensing boiler), which is why direct
electric is 15.

### Windows and glazing (10%)
Single 0 · secondary 45 · double (pre-2002) 70 · double (2002+) 85 · triple 100.

### Renewable energy (10%)
Solar PV capacity: 0 kWp → 0 · 1 → 30 · 2 → 55 · 3 → 75 · ≥ 4 → 100 (≈4 kWp is a full
domestic array). Heat pumps are scored under heating only, so they are not counted twice.

### Smart energy management (5%)
None 0 · programmer + thermostat 40 · + TRVs 60 · smart thermostat 80 · smart + zoning 100.

## 2b. Calibration anchor (v1.0 → v1.1)

PS2 fixes the weights; the sub-score tables are ours. We calibrated them to one stated
anchor: **a typical UK home (Ofgem TDCV consumption, EPC D, condensing boiler, pre-2002
double glazing, partly insulated, no solar) should land in "Moderate"**. Version 1.0 was
harsher: 42% of the 3,000 dataset homes came out Poor/Very poor, and a typical EPC-D semi
scored 47 (Poor). Version 1.1 softened the intensity curve, loft depths of 100-200 mm,
unfilled cavities (25 → 30), pre-2002 double glazing (65 → 70) and the floor's weight within
insulation (20% → 15%). Monotonicity is unchanged and still tested. Resulting distribution:
Moderate 45% · Poor 32% · Very poor 1% · Good 13% · Highly efficient 1% · partial (no
band) 8%. Many homes score low on *renewables* (10% weight) because most have no solar.

## 3. Inputs that influence more than one component (PS2 asks us to justify these)

| Input | Components | Justification |
|---|---|---|
| Solar PV | Renewables (capacity) and intensity (fewer grid imports) | Renewables rewards on-site generation *capability*; intensity measures the purchased-energy *outcome*. PS2 defines purchased energy as grid imports, so a PV home legitimately buys less. |
| Fabric and heating | Energy efficiency (via the EPC rating) and insulation/heating | The EPC rating is itself an aggregate of fabric and systems. PS2 requires both a rating-based component and fabric/system components, so the overlap is by design; we keep the inputs distinct (the recorded SAP number vs. the physical attributes). |
| Floor area | Intensity only (denominator) | Used once, to normalise energy for size. |

## 4. Missing data: three honest states

| State | When | What we report |
|---|---|---|
| **complete** | Every component valued from observed (or logically derived) data | Score + band |
| **provisional** | Every component valued, but some from documented **age-band defaults** (RdSAP-style) or **model estimates** | Score + band, with those components marked "assumed"/"estimated" in the UI |
| **partial** | At least one component cannot be valued at all | **No point score.** The range the score could take (missing sub-scores at 0 and at 100). A band only if the whole range sits in one band. |

We never fill a missing component with zero or an average just to produce a number.

### Age-band defaults (used only when a field is unknown, always labelled "assumed")
| Field | Default |
|---|---|
| Wall type | Solid if built before 1919, otherwise cavity |
| Wall insulation | Insulated only for cavity walls built 1981 or later |
| Loft depth | 250 mm (2002+), 150 mm (1981–2002), 100 mm (earlier) |
| Floor insulation | Insulated only if built 2002 or later |
| Glazing | Double (2002+) for 2002+ homes, otherwise double (pre-2002) |
| Controls | Programmer + room thermostat (the most common set) |
| Solar PV | None |
| Boiler age | 12 years |
| Heating system, floor area, construction age | **No default**: left missing |
