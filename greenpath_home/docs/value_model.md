# Property Value Impact Model

## Purpose

This stage estimates whether the proposed retrofit package could increase
property value. The output is a range, not a single value.

The LLM must not invent property-value estimates. It may only explain the values
produced by this model.

## Prototype Method

The current version is a documented rule-based estimator:

1. Start with the current property value from `properties.csv`.
2. Estimate a post-retrofit energy rating from the package improvement
   potential and retrofit mix.
3. Convert the rating-band improvement into an indicative uplift range.
4. Apply that range to the current value.

## Rating Improvement Rules

The prototype estimates rating movement as follows:

| Condition | Added rating bands |
| --- | ---: |
| Package improvement potential is at least 20% | +1 |
| Package improvement potential is at least 45% | +1 |
| Insulation, glazing, and heat pump are all recommended | +1 |
| Solar is recommended and package improvement is at least 30% | +1 |

The estimated post-retrofit rating is capped at `A`.

## Uplift Range

| Rating-band improvement | Indicative value uplift |
| --- | ---: |
| 0 | 0-1% |
| 1 | 1-3% |
| 2 | 2-5% |
| 3+ | 4-8% |

Example:

```text
Current value: GBP 350,000
Rating change: E -> C
Uplift range: 2-5%
Potential value: GBP 357,000-GBP 367,500
```

## Limitations

This prototype does not establish a causal retrofit effect. It is an indicative
estimate based on documented assumptions. A later version should train and
evaluate a model using sales history, property type, size, region, market date,
and energy rating while avoiding data leakage.
