# GreenPath Home

Prototype for **Megathon X: Singularity | Lloyds Green Home Score and Retrofit
Recommendation Engine**.

Everything for the project lives inside this single folder:

```text
greenpath_home/
```

The system is deterministic and auditable. The LLM must not invent scores,
savings, carbon values, or property-value estimates. A later LLM layer should
only explain the outputs produced by these modules.

## Important Data Note

This prototype currently uses **generated sample data**, not real customer data
and not final public datasets. The files in `data/sample/` are created by
`scripts/generate_sample_data.py` so the scoring, retrofit, carbon, and value
calculation pipeline can be tested end to end.

That means the current numbers demonstrate that the system works technically,
but they should not be presented as real-world evidence. For the final
submission, we need to replace or supplement the generated data with documented
datasets and clearly record sources, licences, assumptions, and limitations.

Real or stronger datasets needed next:

- **Property/EPC data**: energy rating, property type, age, floor area,
  insulation, heating, glazing, and recommendations.
- **Energy usage data**: electricity and gas consumption that can be annualised
  at property level or simulated from documented benchmarks.
- **Retrofit catalogue**: feasibility conditions, indicative costs, and expected
  impacts from documented sources.
- **Emissions factors**: official electricity and gas kg CO2e/kWh values with
  source and units.
- **Sales/property value data**: current value or sales history, region, property
  type, size, date, and energy rating at sale.

The current generated data is useful for building and testing the pipeline; the
final version needs real public data, a larger documented simulator, or a
carefully documented combination of both.

## What It Does

- Calculates a Green Home Score from 0 to 100.
- Classifies homes as Highly efficient, Good, Moderate, Poor, or Very poor.
- Flags Poor and Very poor homes.
- Recommends feasible retrofits.
- Estimates electricity and gas savings separately.
- Calculates carbon reduction from per-fuel emissions factors.
- Estimates indicative property-value impact as a range.
- Generates one combined customer report matching the problem statement outputs.

## Folder Structure

```text
greenpath_home/
├── data/sample/
│   ├── emissions_factors.csv
│   ├── energy_usage.csv
│   └── properties.csv
├── docs/
│   ├── brief_compliance_checklist.md
│   ├── carbon_model.md
│   ├── data_and_scoring.md
│   ├── retrofit_model.md
│   └── value_model.md
├── scripts/
│   ├── calculate_carbon.py
│   ├── estimate_value_impact.py
│   ├── generate_customer_report.py
│   ├── generate_sample_data.py
│   ├── rank_poor_homes.py
│   ├── recommend_retrofits.py
│   └── score_properties.py
├── src/green_home/
│   ├── __init__.py
│   ├── carbon.py
│   ├── retrofits.py
│   ├── scoring.py
│   └── value.py
└── tests/
    ├── test_carbon.py
    ├── test_retrofits.py
    ├── test_scoring.py
    └── test_value.py
```

## Quick Start

Run these from inside `greenpath_home/`:

```bash
python3 scripts/generate_sample_data.py
python3 scripts/generate_customer_report.py
python3 scripts/rank_poor_homes.py
python3 -m unittest discover -s tests
```

Individual pipeline steps:

```bash
python3 scripts/score_properties.py
python3 scripts/recommend_retrofits.py
python3 scripts/calculate_carbon.py
python3 scripts/estimate_value_impact.py
```

## Script Functions

### `scripts/generate_sample_data.py`

- `main()` creates the sample folder and writes all sample files.
- `write_properties()` writes synthetic property records.
- `write_energy_usage()` writes monthly electricity and gas usage.
- `write_emissions_factors()` writes prototype electricity and gas emissions factors.

### `scripts/score_properties.py`

- `main()` scores all sample properties.
- `read_properties(path)` loads property records from CSV.
- `read_energy_usage(path)` loads monthly energy readings by property.
- `print_scores(results)` prints score, class, contributions, and key issues.

### `scripts/recommend_retrofits.py`

- `main()` scores each property and recommends retrofits.
- `print_plan(classification, plan)` prints suitability, savings, and reasons.

### `scripts/calculate_carbon.py`

- `main()` calculates carbon impact for retrofit plans.
- `read_emissions_factors(path)` loads electricity and gas factors from CSV.
- `print_carbon_plan(classification, plan, factors)` prints per-retrofit and package carbon impact.

### `scripts/estimate_value_impact.py`

- `main()` estimates value impact for all properties.
- `print_estimate(estimate)` prints rating movement, uplift range, and value range.

### `scripts/rank_poor_homes.py`

- `main()` filters Poor and Very poor homes, ranks them by improvement potential, and prints key issues.

### `scripts/generate_customer_report.py`

- `main()` runs the full score to value-impact pipeline.
- `print_report(record, score, plan, package_carbon, value)` prints the final customer-facing output.

## Core Module Functions

### `src/green_home/scoring.py`

Classes:

- `PropertyRecord`: property features used by scoring and recommendations.
- `EnergyReading`: one electricity/gas reading.
- `ComponentScore`: one component sub-score, weight, contribution, and reason.
- `ScoreResult`: final score, classification, annualised energy, intensity, and issues.

Functions:

- `classify_score(score)`: maps a score to the required classification.
- `score_property(property_record, energy_readings)`: calculates the full Green Home Score.

Important helpers:

- `_annualise(values)`: annualises observed monthly kWh.
- `_energy_intensity(...)`: calculates purchased energy per square metre.
- `_score_energy_rating(rating)`: maps EPC-like rating to a sub-score.
- `_score_energy_intensity(intensity)`: maps kWh/m2/year to a sub-score.
- `_key_issues(...)`: lists reasons a home is inefficient.

### `src/green_home/retrofits.py`

Classes:

- `FuelSavings`: electricity and gas savings kept separately.
- `RetrofitRecommendation`: retrofit, priority, suitability, savings, and reason.
- `RetrofitPlan`: recommendations, package savings, and improvement potential.

Functions:

- `recommend_retrofits(property_record, score_result)`: returns the prioritized retrofit plan.

Important helpers:

- `_individual_recommendations(...)`: applies retrofit feasibility rules.
- `_package_savings(...)`: applies retrofits sequentially to account for interactions.

### `src/green_home/carbon.py`

Classes:

- `EmissionsFactors`: electricity and gas kg CO2e/kWh values and source.
- `CarbonEstimate`: electricity, gas, net kg CO2e, net tonnes CO2e, and source.

Functions:

- `calculate_carbon(savings, factors)`: converts per-fuel kWh savings to carbon reduction.

### `src/green_home/value.py`

Classes:

- `ValueImpactEstimate`: baseline value, rating movement, uplift range, value range, basis, and limitation.

Functions:

- `estimate_value_impact(property_record, score_result, retrofit_plan)`: estimates indicative value impact.

Important helpers:

- `_estimate_post_retrofit_rating(...)`: estimates post-retrofit rating.
- `_rating_band_improvement(...)`: counts rating-band movement.
- `_uplift_range(bands)`: maps rating improvement to percentage uplift range.
- `_basis(...)`: creates the audit explanation for the estimate.

## Match To The Problem Statement

Implemented:

- fixed weighted Green Home Score;
- monotonic component mappings;
- component contribution explanations;
- Poor and Very poor home detection;
- poor-home ranking by improvement potential;
- feasible retrofit recommendations;
- per-fuel electricity and gas savings;
- interaction-aware package savings;
- carbon reduction using per-fuel emissions factors;
- property-value impact as a range;
- limitation text for value impact;
- no LLM involvement in calculations.

Still prototype:

- data is synthetic;
- retrofit impacts are documented rules;
- emissions factors are prototype placeholders;
- value impact is a rule-based estimate;
- no train/validation/test split yet;
- no dashboard yet;
- no grounded LLM explanation or what-if interface yet.

See `docs/brief_compliance_checklist.md` for the detailed checklist.
