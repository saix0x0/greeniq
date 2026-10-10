# ADR-003 · A simulated world, observed imperfectly, instead of synthetic labels

- **Status:** accepted · **Date:** 2026-10-10 · **Requirements:** DR-1..7, ER-1..3

## Context
PS2's public datasets (EPC, smart-meter, NEED, Price Paid) do not join at the individual
home level, and NEED is aggregated. PS2 allows synthetic data but penalises "arbitrary
synthetic labels".

## Decision
Build a seeded simulator (`greeniq/simulator/world.py`) with physics-lite heat loss,
weather, people, installers and a housing market. Expose only what a lender would see:
imperfect records, gappy monthly meters and sale prices. Keep the hidden truth in
`data/truth/` for evaluation only, and enforce with a test that product code never imports
it. Split by customer.

## Consequences
- ✅ Every evaluation target is an *observation* (meter reads, sale prices, the simulator's
  counterfactual), not a rule we wrote to match our engines.
- ✅ Realistic difficulty the engines don't know about: under-heating of leaky homes,
  installation quality, heat-pump SCOP spread, behaviour, record errors.
- ⚠️ Agreement with this world is not real-world validation. Every report says so.
- 🔁 Real loaders can replace the simulator behind `greeniq/data.py` without touching engines.
