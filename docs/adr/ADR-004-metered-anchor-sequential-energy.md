# ADR-004 · Energy: metered anchor, degree-day split, sequential measures

- **Status:** accepted · **Date:** 2026-10-10 · **Requirements:** FR-2, FR-4, FR-5, DR-5, ER-5

## Context
PS2 needs per-fuel savings per measure and per package, with interactions, negative savings
for fuel switches, solar reducing imports rather than demand, and honest handling of
missing months and zero baselines.

## Options considered
| Option | Verdict |
|---|---|
| A · Catalogue percentages (e.g. "loft = 15%"), summed | Rejected: additive and not per fuel; PS2 explicitly warns against it |
| B · Full physics model of each home | Rejected: needs data we don't have; ignores how the household actually uses energy |
| **C · Degree-day annualisation → end-use decomposition anchored on meters → measures change physical inputs on one evolving state** | Chosen |

## Decision
Option C. Fabric measures remove a *fraction* of the metered heating (ΔHLC/HLC from an
RdSAP-style model). Heat pumps convert remaining heat to electricity at a SCOP fixed at
installation from heat loss per m². Solar offsets imports via self-consumption that
depends on demand. Improvement potential needs a metered, non-zero baseline.

## Consequences
- ✅ Package ≠ sum by construction; interactions are reported, not hidden.
- ✅ Order matters where it physically should (insulate before the heat pump).
- ⚠️ Engineering estimates over-predict real savings (performance gap). Phase 4 learns
  realisation rates from historical before/after retrofits and benchmarks them.
