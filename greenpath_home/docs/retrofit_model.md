# Retrofit Recommendation Model

## Purpose

This stage answers: what should the homeowner improve first?

The current implementation is a documented rule-based model. It is suitable for
the first prototype because it is explainable, reproducible, and easy to audit.
It can later be replaced or calibrated with observed retrofit data.

## Feasibility Rules

| Retrofit | Feasible when |
| --- | --- |
| Roof or loft insulation | `insulation` is `none`, `poor`, or `partial` |
| Double glazing | `glazing` is `single` or `secondary` |
| Heat pump | heating is `gas_boiler`, `oil_boiler`, or `electric_resistance` |
| Solar panels | `solar` is false |
| Smart thermostat | `smart_controls` is false |

The engine does not recommend retrofits that are already present.

## Priority Order

1. Insulation
2. Glazing
3. Heat pump
4. Solar panels
5. Smart thermostat

This order reflects interactions. Fabric upgrades reduce heating demand before a
heating-system replacement is evaluated.

## Savings Assumptions

All savings are estimates, not guarantees.

| Retrofit | Individual estimate |
| --- | --- |
| Roof or loft insulation | 16% gas reduction for `none`/`poor`, 12% for `partial` |
| Double glazing | 10% gas reduction for `single`, 8% for `secondary` |
| Heat pump | Replaces 80% of gas heating load; added electricity is replaced gas / COP 3.0 |
| Solar panels | 30% reduction in grid electricity imports |
| Smart thermostat | 7% gas reduction |

Electricity and gas savings are reported separately. A negative electricity
saving means electricity use increases, which can happen when a heat pump
replaces gas heating.

## Package Calculation

Package savings are not a simple sum of individual savings. The engine applies
retrofits in priority order to the remaining post-upgrade consumption:

```text
baseline electricity/gas
→ insulation reduces gas
→ glazing reduces remaining gas
→ heat pump moves part of remaining gas demand to electricity
→ solar reduces remaining grid electricity import
→ smart controls reduce remaining gas
```

Improvement potential is:

```text
100 * package_net_saving_kwh / baseline_purchased_energy_kwh
```

If baseline energy is zero or unavailable, improvement potential is unavailable.
