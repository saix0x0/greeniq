# Carbon Reduction Model

## Purpose

This stage converts retrofit energy savings into annual carbon impact.

The LLM must not calculate carbon values. It may only explain the values
produced by this deterministic calculation.

## Formula

For each fuel:

```text
carbon_change_kg = energy_saving_kwh * kg_co2e_per_kwh
```

Net carbon reduction:

```text
net_carbon_reduction_kg =
  electricity_saving_kwh * electricity_factor
  + gas_saving_kwh * gas_factor
```

Positive values are emissions reductions. Negative values are emissions
increases.

## Why Per-Fuel Calculation Matters

Retrofits can affect electricity and gas differently. A heat pump may reduce gas
use while increasing electricity use. The system must preserve those separate
fuel changes instead of converting only a combined kWh figure.

Example:

```text
electricity saving = -1,000 kWh/year
gas saving = 5,000 kWh/year
```

The electricity value is negative because grid electricity use increased.

## Input Data

Sample factors are stored in:

```text
data/sample/emissions_factors.csv
```

Current generated sample values:

| Fuel | kg CO2e/kWh | Source |
| --- | ---: | --- |
| electricity | 0.207 | prototype_sample_factor |
| gas | 0.183 | prototype_sample_factor |

These are starter prototype values. For a final submission, replace them with
documented emissions factors from an accepted source and keep the source and
units in the CSV.

## Output

The carbon engine reports:

- electricity carbon change in kg CO2e/year;
- gas carbon change in kg CO2e/year;
- net kg CO2e/year;
- net tonnes CO2e/year;
- emissions-factor source.
