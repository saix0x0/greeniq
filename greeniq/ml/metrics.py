"""Regression metrics used throughout training and evaluation."""

from __future__ import annotations

import numpy as np


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    y, pred = np.asarray(y, float), np.asarray(pred, float)
    err = pred - y
    ss_tot = float(((y - y.mean()) ** 2).sum())
    nz = y > 0
    return {
        "n": int(len(y)),
        "mae": round(float(np.abs(err).mean()), 1),
        "rmse": round(float(np.sqrt((err ** 2).mean())), 1),
        "r2": round(1 - float((err ** 2).sum()) / ss_tot, 3) if ss_tot > 0 else None,
        "median_ape_pct": round(float(np.median(np.abs(err[nz]) / y[nz]) * 100), 1) if nz.any() else None,
    }
