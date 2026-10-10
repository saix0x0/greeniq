"""Annualise monthly meter reads per fuel, weather-normalised, without zero-filling gaps.

Method: degree-day regression (the PRISM approach, Fels 1986). For each fuel we fit

    kWh_month = a · days_month + b · HDD_month        (a, b ≥ 0)

on the months we actually have, then evaluate it in a *normal* weather year:

    annual = a · 365 + b · HDD_normal_year

This does three jobs at once: it annualises incomplete data, it removes the effect of an
unusually cold or mild year, and it splits use into baseload (a · 365: hot water,
cooking, appliances) and space heating (b · HDD_normal). The heating share is what the
retrofit engine scales when insulation or a new heating system changes heat demand.

Coverage rules (documented in docs/METHODOLOGY.md):
- 12 of 12 months valid                                → ``metered_full``
- ≥ 6 months, incl. ≥ 2 cold (HDD ≥ 150) and ≥ 1 mild (HDD ≤ 80) → ``metered_partial``
- otherwise                                            → ``insufficient`` (no annual figure)
- every valid read is zero                             → ``zero`` (annual = 0; potential unavailable)
- no reads at all for the fuel                         → ``no_data``
A missing month is never treated as zero.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel

from ..contract import Receipt

ANNUALISE_VERSION = "degree-day-annualisation/1.0"
COLD_HDD, MILD_HDD = 150.0, 80.0
MIN_MONTHS = 6

FuelStatus = Literal["metered_full", "metered_partial", "insufficient", "zero", "no_data", "not_applicable"]


class AnnualFuel(BaseModel):
    fuel: str
    status: FuelStatus
    annual_kwh: float | None = None
    baseload_kwh: float | None = None
    heating_kwh: float | None = None
    months_used: int = 0
    months_missing: int = 0
    r2: float | None = None
    observed_sum_kwh: float | None = None
    receipt: Receipt | None = None

    @property
    def usable(self) -> bool:
        return self.status in ("metered_full", "metered_partial", "zero", "not_applicable")


def _fit(days: np.ndarray, hdd: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least squares for y = a·days + b·hdd with a, b ≥ 0 (two-variable active set)."""
    X = np.column_stack([days, hdd])
    candidates = []
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    if coef[0] >= 0 and coef[1] >= 0:
        candidates.append((coef[0], coef[1]))
    a_only = max(float(days @ y / (days @ days)), 0.0)
    candidates.append((a_only, 0.0))
    if hdd @ hdd > 0:
        candidates.append((0.0, max(float(hdd @ y / (hdd @ hdd)), 0.0)))
    best = min(candidates, key=lambda ab: float(((X @ np.array(ab)) - y) ** 2 @ np.ones(len(y))))
    pred = X @ np.array(best)
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0
    return float(best[0]), float(best[1]), r2


def annualise_fuel(
    fuel: str,
    reads: dict[str, float | None],
    window: list[str],
    hdd: dict[str, float],
    hdd_normal_year: float,
    days: dict[str, int],
) -> AnnualFuel:
    """Annualise one fuel over ``window`` (YYYY-MM strings, oldest first)."""
    if not reads:
        return AnnualFuel(fuel=fuel, status="no_data", months_missing=len(window),
                          receipt=_receipt(fuel, "no_data", None, {}, ["no meter reads for this fuel"]))
    months = [m for m in window if reads.get(m) is not None]
    n, missing = len(months), len(window) - len(months)
    y = np.array([reads[m] for m in months], dtype=float)
    observed = float(y.sum()) if n else None

    if n and float(np.abs(y).sum()) == 0.0:
        return AnnualFuel(fuel=fuel, status="zero", annual_kwh=0.0, baseload_kwh=0.0, heating_kwh=0.0,
                          months_used=n, months_missing=missing, observed_sum_kwh=0.0,
                          receipt=_receipt(fuel, "zero", 0.0, {"months_used": n},
                                           ["every valid read is zero: baseline energy is zero"]))

    h = np.array([hdd[m] for m in months], dtype=float)
    cold, mild = int((h >= COLD_HDD).sum()), int((h <= MILD_HDD).sum())
    enough = n == len(window) or (n >= MIN_MONTHS and cold >= 2 and mild >= 1)
    if not enough:
        return AnnualFuel(fuel=fuel, status="insufficient", months_used=n, months_missing=missing,
                          observed_sum_kwh=observed,
                          receipt=_receipt(fuel, "insufficient", None,
                                           {"months_used": n, "cold_months": cold, "mild_months": mild},
                                           [f"only {n} valid months ({cold} cold, {mild} mild); need ≥{MIN_MONTHS} "
                                            "including ≥2 cold and ≥1 mild"]))

    d = np.array([days[m] for m in months], dtype=float)
    a, b, r2 = _fit(d, h, y)
    base, heat = a * 365.0, b * hdd_normal_year
    status: FuelStatus = "metered_full" if n == len(window) else "metered_partial"
    return AnnualFuel(
        fuel=fuel, status=status, annual_kwh=round(base + heat, 1), baseload_kwh=round(base, 1),
        heating_kwh=round(heat, 1), months_used=n, months_missing=missing, r2=round(r2, 3),
        observed_sum_kwh=round(observed, 1),
        receipt=_receipt(fuel, status, round(base + heat, 1),
                         {"months_used": n, "months_missing": missing, "a_kwh_per_day": round(a, 3),
                          "b_kwh_per_hdd": round(b, 4), "hdd_normal_year": round(hdd_normal_year, 1),
                          "r2": round(r2, 3)},
                         ["weather-normalised to a normal year"] + (
                             [f"{missing} missing month(s) handled by regression, not zero-filled"] if missing else [])),
    )


def _receipt(fuel: str, status: str, value, inputs: dict, notes: list[str]) -> Receipt:
    return Receipt(
        output=f"energy.baseline.{fuel}", value=value, unit="kWh/yr", inputs=inputs,
        method="Degree-day regression kWh = a·days + b·HDD (PRISM), evaluated in a normal weather year",
        method_version=ANNUALISE_VERSION, provider="deterministic",
        sources=["Fels (1986) PRISM: Princeton Scorekeeping Method", "docs/METHODOLOGY.md §2"],
        notes=[f"status: {status}"] + notes,
    )
