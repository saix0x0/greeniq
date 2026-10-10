# Data And Scoring Notes

## Design Principle

The Green Home Score is transparent and reproducible. Every final score is a
weighted sum of seven monotonic component sub-scores. A better home condition
must never produce a lower component score.

The LLM must not calculate this score. It may only explain the outputs produced
by this scoring engine.

## Input Tables

### `properties.csv`

| Field | Meaning |
| --- | --- |
| `property_id` | Stable property identifier |
| `property_type` | Detached, semi-detached, terraced, flat, bungalow |
| `age_band` | Approximate construction period |
| `floor_area_m2` | Internal floor area in square metres |
| `bedrooms` | Bedroom count |
| `energy_rating` | EPC-like rating from A to G |
| `heating` | Main heating system |
| `insulation` | Current insulation state |
| `glazing` | Window/glazing state |
| `solar` | Whether solar panels are installed |
| `smart_controls` | Whether smart energy controls are installed |
| `region` | Broad region |
| `current_value_gbp` | Current baseline property-value estimate |

### `energy_usage.csv`

| Field | Meaning |
| --- | --- |
| `property_id` | Stable property identifier |
| `month` | Month in `YYYY-MM` format |
| `electricity_kwh` | Metered monthly electricity use |
| `gas_kwh` | Metered monthly gas use |

Monthly energy is annualised as:

```text
annual_kwh = observed_kwh_sum * 12 / observed_month_count
```

Missing months are not treated as zero. If a property has no usable energy
months, the energy-consumption component is set to 0 and the issue is surfaced.

## Green Home Score Formula

```text
S = sum(weight_k * subscore_k)
```

The final score is rounded to the nearest integer.

| Component | Weight |
| --- | ---: |
| Energy efficiency | 25% |
| Energy consumption intensity | 20% |
| Insulation | 15% |
| Heating system | 15% |
| Windows and glazing | 10% |
| Renewable energy | 10% |
| Smart energy management | 5% |

## Component Mappings

### Energy Efficiency

Based on the recorded energy rating only.

| Rating | Score |
| --- | ---: |
| A | 100 |
| B | 85 |
| C | 70 |
| D | 55 |
| E | 40 |
| F | 25 |
| G | 10 |

### Energy Consumption Intensity

Uses annualised purchased energy per square metre:

```text
(annual_electricity_kwh + annual_gas_kwh) / floor_area_m2
```

| kWh/m2/year | Score |
| --- | ---: |
| `<= 70` | 100 |
| `<= 110` | 85 |
| `<= 160` | 65 |
| `<= 220` | 45 |
| `<= 300` | 25 |
| `> 300` | 10 |

### Insulation

| State | Score |
| --- | ---: |
| excellent | 100 |
| good | 75 |
| partial | 45 |
| poor | 20 |
| none | 0 |

### Heating System

| State | Score |
| --- | ---: |
| heat_pump | 95 |
| district_heating | 80 |
| modern_gas_boiler | 65 |
| gas_boiler | 45 |
| electric_resistance | 30 |
| oil_boiler | 20 |

### Windows And Glazing

| State | Score |
| --- | ---: |
| triple | 100 |
| double | 75 |
| secondary | 50 |
| single | 20 |

### Renewable Energy

| State | Score |
| --- | ---: |
| true | 100 |
| false | 0 |

### Smart Energy Management

| State | Score |
| --- | ---: |
| true | 100 |
| false | 0 |

## Classification

| Score | Classification |
| --- | --- |
| 80-100 | Highly efficient |
| 65-79 | Good |
| 50-64 | Moderate |
| 30-49 | Poor |
| 0-29 | Very poor |

## Leakage And Limitations

- The sample generator creates synthetic data for prototyping only.
- Property-level train/validation/test splitting should be added before model
  training begins.
- The score uses current observable fields and annualised meter readings only.
- The score is not a retrofit savings model. Later stages should estimate
  energy, carbon, and value changes separately.
