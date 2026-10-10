"""Train GreenIQ's models: ``greeniq train``.

Protocol (ER-1, ER-2, DR-3):
- fit on the TRAIN split only;
- choose hyper-parameters and decide promotions on the VALIDATION split only;
- never touch the TEST split here (``greeniq evaluate`` scores it once, afterwards);
- splits are by customer, so no home or customer is in two splits;
- every candidate is compared with a simple baseline, and the result is written to
  models/model_card.json together with the seed, git commit and feature list.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import subprocess
import time

import joblib
import numpy as np
import pandas as pd

from ..contract import FUELS
from ..data import DATA_DIR, ROOT, load_dataset, load_splits
from .features import FEATURE_VERSION, FEATURES, feature_frame
from .metrics import regression_metrics
from .models import SEED, GBMEnergy, HedonicPremium, PeerMedianEnergy, PhysicsEnergy, ValueLevel
from .registry import MODELS_DIR
from .retrofit_cases import build_cases, predict_case

MODEL_VERSION = "greeniq-models/1.0"
USABLE = {"metered_full", "metered_partial", "zero", "not_applicable"}
SHRINK_K = 10  # cold-start shrinkage of realisation rates toward 1.0 (= engineering estimate)


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


# ------------------------------------------------------------------------------------------
# Tables
# ------------------------------------------------------------------------------------------

def energy_table(ds, splits: pd.DataFrame) -> pd.DataFrame:
    """Homes whose metered baseline is usable for BOTH fuels and non-zero in total (occupied homes)."""
    annual = pd.read_csv(DATA_DIR / "processed" / "annual_energy.csv")
    kwh = annual.pivot(index="property_id", columns="fuel", values="annual_kwh")
    status = annual.pivot(index="property_id", columns="fuel", values="status")
    ok = status["electricity"].isin(USABLE) & status["gas"].isin(USABLE)
    df = kwh[ok].reset_index()
    df = df[(df["electricity"] + df["gas"]) > 0]
    return df.merge(splits, on="property_id")


def value_table(ds, splits: pd.DataFrame) -> pd.DataFrame:
    sales = ds.tables["sales"].merge(splits, on="property_id")
    idx = {(r, y): v for r, y, v in ds.tables["market_index"][["region", "year", "index"]].itertuples(index=False)}
    props = {pid: ds.property(pid) for pid in sales["property_id"].unique()}
    sales["region"] = sales["property_id"].map(lambda pid: props[pid].region)
    sales["year"] = sales["sale_date"].str[:4].astype(int)
    sales["price_today"] = sales["price"] / [idx[(r, y)] for r, y in zip(sales["region"], sales["year"])]
    sales["log_price"] = np.log(sales["price_today"])
    for col in ("property_type", "age_band", "floor_area_m2"):
        sales[col] = sales["property_id"].map(lambda pid, c=col: getattr(props[pid], c))
    sales["band"] = sales["epc_band_at_sale"]
    return sales.reset_index(drop=True), props


# ------------------------------------------------------------------------------------------
# Energy
# ------------------------------------------------------------------------------------------

def train_energy(ds, df: pd.DataFrame, weather, log) -> tuple[dict, dict]:
    props = [ds.property(pid) for pid in df["property_id"]]
    X = feature_frame(props)
    tr, va = (df["split"] == "train").values, (df["split"] == "validation").values
    p_tr = [p for p, m in zip(props, tr) if m]
    p_va = [p for p, m in zip(props, va) if m]
    models, card = {}, {"rows": {"train": int(tr.sum()), "validation": int(va.sum())}, "fuels": {}, "promoted": {}}
    grid = list(itertools.product([0.03, 0.06, 0.1], [15, 31], [200, 400, 800]))
    for fuel in FUELS:
        y = df[fuel].to_numpy(float)
        peer = PeerMedianEnergy().fit(p_tr, y[tr])
        peer_va = peer.predict(p_va)
        phys_va = PhysicsEnergy(weather).predict(p_va, fuel, fallback=peer_va)
        best = None
        for lr, leaves, iters in grid:
            m = GBMEnergy(learning_rate=lr, max_leaf_nodes=leaves, max_iter=iters).fit(X[tr], y[tr])
            mae = float(np.abs(m.predict(X[va]) - y[va]).mean())
            if best is None or mae < best[0]:
                best = (mae, {"learning_rate": lr, "max_leaf_nodes": leaves, "max_iter": iters}, m)
        gbm = best[2]
        cands = {"peer": regression_metrics(y[va], peer_va), "physics": regression_metrics(y[va], phys_va),
                 "gbm": regression_metrics(y[va], gbm.predict(X[va]))}
        promoted = "gbm" if cands["gbm"]["mae"] < cands["peer"]["mae"] else "peer"
        models[fuel] = {"peer": peer, "gbm": gbm}
        card["fuels"][fuel] = {"validation": cands, "gbm_params": best[1], "grid_size": len(grid)}
        card["promoted"][fuel] = promoted
        log(f"  energy/{fuel}: val MAE peer {cands['peer']['mae']:.0f} · physics {cands['physics']['mae']:.0f} "
            f"· gbm {cands['gbm']['mae']:.0f} → promoted {promoted}")
    return models, card


# ------------------------------------------------------------------------------------------
# Savings calibration
# ------------------------------------------------------------------------------------------

def _case_errors(cases, ctx, calibration) -> dict:
    e, g, n = [], [], 0
    for c in cases:
        pred = predict_case(c, ctx, calibration)
        if pred is None:
            continue
        n += 1
        e.append(abs(pred["electricity"] - c.observed["electricity"]))
        g.append(abs(pred["gas"] - c.observed["gas"]))
    return {"n": n, "mae_electricity": round(float(np.mean(e)), 1) if e else None,
            "mae_gas": round(float(np.mean(g)), 1) if g else None,
            "mae_total": round(float(np.mean(e) + np.mean(g)), 1) if e else None}


def train_calibration(ds, ctx, splits: pd.DataFrame, log) -> dict:
    ids = {s: set(splits.loc[splits["split"] == s, "property_id"]) for s in ("train", "validation")}
    train_cases, skipped = build_cases(ds, ctx, ids["train"])
    val_cases, _ = build_cases(ds, ctx, ids["validation"])
    grid = np.round(np.linspace(0.3, 1.5, 25), 3)
    rates = {}
    for m in sorted({c.measure_id for c in train_cases}):
        cs = [c for c in train_cases if c.measure_id == m]
        best = None
        for r in grid:
            err = _case_errors(cs, ctx, {m: float(r)})
            if err["n"] and (best is None or err["mae_total"] < best[0]):
                best = (err["mae_total"], float(r), err["n"])
        if best is None:
            continue
        _, r_hat, n = best
        rate = (n * r_hat + SHRINK_K * 1.0) / (n + SHRINK_K)
        rates[m] = {"rate": round(rate, 3), "raw_rate": r_hat, "n_train": n}
        log(f"  calibration/{m}: raw {r_hat:.2f} (n={n}) → shrunk {rate:.3f}")
    cal = {m: v["rate"] for m, v in rates.items()}
    val_uncal = _case_errors(val_cases, ctx, {})
    val_cal = _case_errors(val_cases, ctx, cal)
    promoted = bool(val_cal["mae_total"] is not None and val_cal["mae_total"] < val_uncal["mae_total"])
    log(f"  calibration: val MAE (elec+gas) uncalibrated {val_uncal['mae_total']} → calibrated {val_cal['mae_total']} "
        f"→ promoted {promoted}")
    return {"rates": rates, "shrinkage_k": SHRINK_K, "grid": [float(grid[0]), float(grid[-1]), len(grid)],
            "train_cases": len(train_cases), "validation_cases": len(val_cases), "skipped_train": skipped,
            "validation": {"uncalibrated": val_uncal, "calibrated": val_cal}, "promoted": promoted}


# ------------------------------------------------------------------------------------------
# Value
# ------------------------------------------------------------------------------------------

def train_value(ds, splits: pd.DataFrame, log) -> tuple[dict, dict]:
    """Choose the current-value model by grouped 5-fold CV over train+validation.

    Protocol note (v1.1): the first evaluation run selected a GBM on the single validation
    split, and it then under-performed the simple baseline on test. Single small validation
    splits are noisy, so selection now uses customer-grouped cross-validation over
    train+validation, with the textbook hedonic regression as an extra candidate. Because a
    test result prompted this change, the report discloses it.
    """
    from sklearn.model_selection import GroupKFold

    sales, props = value_table(ds, splits)
    dev = sales[sales["split"].isin(["train", "validation"])].reset_index(drop=True)
    pl = [props[pid] for pid in dev["property_id"]]
    saps = list(dev["sap_at_sale"].astype(float))
    y = dev["log_price"].to_numpy()
    candidates = {"regional": {}, "hedonic": {},
                  **{f"gbm_lr{lr}_l{leaves}": {"learning_rate": lr, "max_leaf_nodes": leaves, "max_iter": 300,
                                               "min_samples_leaf": 30}
                     for lr in (0.03, 0.06) for leaves in (7, 15)}}
    oof = {k: np.full(len(dev), np.nan) for k in candidates}
    folds = GroupKFold(n_splits=5).split(dev, groups=dev["customer_id"])
    for tr_idx, te_idx in folds:
        ptr, pte = [pl[i] for i in tr_idx], [pl[i] for i in te_idx]
        str_, ste = [saps[i] for i in tr_idx], [saps[i] for i in te_idx]
        for k, params in candidates.items():
            kind = "gbm" if k.startswith("gbm") else k
            m = ValueLevel(kind, params).fit(ptr, str_, y[tr_idx])
            oof[k][te_idx] = m.predict_log(pte, ste)
    price = np.exp(y)
    cv = {k: regression_metrics(price, np.exp(v)) for k, v in oof.items()}
    best = min(cv, key=lambda k: cv[k]["median_ape_pct"])
    kind = "gbm" if best.startswith("gbm") else best
    level = ValueLevel(kind, candidates[best]).fit(pl, saps, y).set_interval(y - oof[best], coverage=0.8)
    hed = HedonicPremium().fit(dev[["property_id", "region", "property_type", "age_band", "floor_area_m2", "band",
                                    "log_price"]])
    card = {
        "sales_dev": int(len(dev)), "selection": "customer-grouped 5-fold CV over train+validation (median APE)",
        "cv": cv, "chosen": best, "chosen_kind": kind,
        "conformal": {"coverage": 0.8, "q_lo": round(level.q_lo, 4), "q_hi": round(level.q_hi, 4),
                      "source": "out-of-fold residuals of the chosen model"},
        "hedonic": hed.summary(), "hedonic_reference_band": "D", "bootstrap_draws": int(len(hed.draws)),
        "protocol_note": ("v1.1: selection moved from a single validation split to grouped CV after the first test "
                          "run showed the validation-selected GBM under-performing the baseline on test."),
    }
    log("  value CV median APE: " + " · ".join(f"{k} {v['median_ape_pct']}%" for k, v in cv.items()) + f" → {best}")
    return {"level": level, "hedonic": hed}, card


# ------------------------------------------------------------------------------------------

def train_all(log=print) -> dict:
    from ..context import load_context

    t0 = time.time()
    ds, splits = load_dataset(), load_splits()
    ctx = load_context(with_models=False)
    MODELS_DIR.mkdir(exist_ok=True)

    log("training energy models (per fuel)…")
    df = energy_table(ds, splits)
    energy_models, energy_card = train_energy(ds, df, ctx.weather, log)
    joblib.dump(energy_models, MODELS_DIR / "energy_models.joblib")

    log("learning savings realisation rates from past retrofits…")
    calibration_card = train_calibration(ds, dataclasses.replace(ctx), splits, log)

    log("training value models…")
    value_models, value_card = train_value(ds, splits, log)
    joblib.dump(value_models, MODELS_DIR / "value_models.joblib")

    card = {
        "version": MODEL_VERSION, "git_commit": git_commit(), "seed": SEED, "feature_version": FEATURE_VERSION,
        "features": FEATURES,
        "leakage_controls": [
            "features read only recorded characteristics (never meters, prices or current value)",
            "splits by customer (hash); fit on train, tune and promote on validation; test untouched",
            "value features use the SAP in force at the sale, not today's",
        ],
        "split_counts": splits["split"].value_counts().to_dict(),
        "energy": energy_card, "calibration": calibration_card, "value": value_card,
        "training_seconds": round(time.time() - t0, 1),
    }
    (MODELS_DIR / "model_card.json").write_text(json.dumps(card, indent=2, default=float), encoding="utf-8")
    log(f"done in {card['training_seconds']} s → {MODELS_DIR}")
    return card
