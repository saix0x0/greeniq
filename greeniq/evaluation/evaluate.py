"""Evaluation harness: ``greeniq evaluate``. Reports every metric on the VALIDATION split (PS2 §13G),
then scores the held-out TEST split once with the same metrics.

This is the only place (besides the simulator) allowed to read the hidden truth
(``data/truth/hidden.csv``), and it does so only to *grade* outputs: the counterfactual
improvement potential, the score from true inputs, true feasibility and true value.

Outputs (all regenerated on every run, stamped with the git commit):
    reports/EVALUATION.md          human-readable report
    reports/metrics.json           every metric, machine-readable
    reports/test_predictions.csv   held-out predictions (schema in reports/TEST_PREDICTIONS_SCHEMA.md)
"""

from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ..context import load_context
from ..contract import FUELS, Resolved
from ..data import ROOT, load_dataset, load_splits, load_truth
from ..engines.catalogue import measure
from ..ml.features import feature_frame
from ..ml.metrics import regression_metrics
from ..ml.models import PhysicsEnergy, ValueLevel
from ..ml.registry import MODELS_DIR, load_card
from ..ml.retrofit_cases import build_cases, predict_case
from ..ml.train import energy_table, git_commit, value_table
from ..pipeline import analyse_home
from ..score import compute_score, sap_to_band
from ..simulator import world as W

REPORTS = ROOT / "reports"


# ------------------------------------------------------------------------------------------
# 1. Baseline energy models
# ------------------------------------------------------------------------------------------

def eval_energy(ds, splits, weather, split: str = "test") -> dict:
    df = energy_table(ds, splits)
    te = df[df["split"] == split].reset_index(drop=True)
    props = [ds.property(pid) for pid in te["property_id"]]
    X = feature_frame(props)
    models = joblib.load(MODELS_DIR / "energy_models.joblib")
    out = {}
    for fuel in FUELS:
        y = te[fuel].to_numpy(float)
        peer = models[fuel]["peer"].predict(props)
        phys = PhysicsEnergy(weather).predict(props, fuel, fallback=peer)
        gbm = models[fuel]["gbm"].predict(X)
        by_type = {}
        for t in sorted(te.assign(t=[p.property_type for p in props])["t"].unique()):
            m = np.array([p.property_type == t for p in props])
            by_type[t] = regression_metrics(y[m], gbm[m])["median_ape_pct"]
        out[fuel] = {split: {"global_median": regression_metrics(y, np.full(len(y), np.median(y))),
                              "peer_median": regression_metrics(y, peer), "physics": regression_metrics(y, phys),
                              "gbm": regression_metrics(y, gbm)},
                     "gbm_median_ape_by_type": by_type}
    return out


# ------------------------------------------------------------------------------------------
# 2. Savings: predicted vs observed on historical retrofits
# ------------------------------------------------------------------------------------------

def _naive(case) -> dict:
    """Fuel-blind rule of thumb: a flat % of total purchased energy, all credited to the heating fuel."""
    pct = measure(case.measure_id)["naive_flat_reduction"]
    total = case.pre_annual["electricity"] + case.pre_annual["gas"]
    heat_fuel = "gas" if (case.pre.heating_system or "").startswith("gas") else "electricity"
    fuel = "electricity" if case.measure_id == "solar_pv" else heat_fuel
    out = {"electricity": 0.0, "gas": 0.0}
    out[fuel] = pct * total
    return out


def eval_savings(ds, splits, ctx_engine, card, split: str = "test") -> dict:
    test_ids = set(splits.loc[splits["split"] == split, "property_id"])
    cases, skipped = build_cases(ds, ctx_engine, test_ids)
    rates = {k: v["rate"] for k, v in card["calibration"]["rates"].items()}
    rows = []
    for c in cases:
        eng = predict_case(c, ctx_engine, {})
        cal = predict_case(c, ctx_engine, rates)
        if eng is None or cal is None:
            continue
        rows.append({"measure": c.measure_id, **{f"obs_{f}": c.observed[f] for f in FUELS},
                     **{f"naive_{f}": v for f, v in _naive(c).items()},
                     **{f"eng_{f}": eng[f] for f in FUELS}, **{f"cal_{f}": cal[f] for f in FUELS}})
    df = pd.DataFrame(rows)
    res = {"cases": int(len(df)), "skipped": skipped, "methods": {}}
    for m in ("naive", "eng", "cal"):
        res["methods"][m] = {f: {"mae": round(float((df[f"{m}_{f}"] - df[f"obs_{f}"]).abs().mean()), 1),
                                 "bias": round(float((df[f"{m}_{f}"] - df[f"obs_{f}"]).mean()), 1)} for f in FUELS}
    hp = df[df["measure"] == "air_source_heat_pump"]
    if len(hp):
        res["heat_pump_cases"] = int(len(hp))
        res["heat_pump_observed_elec_increase_share"] = round(float((hp["obs_electricity"] < 0).mean()), 2)
        for m in ("naive", "eng", "cal"):
            res["methods"][m]["hp_electricity_sign_correct"] = round(
                float((np.sign(hp[f"{m}_electricity"]) == np.sign(hp["obs_electricity"])).mean()), 2)
    per = {}
    for meas, g in df.groupby("measure"):
        net = g["obs_electricity"] + g["obs_gas"]
        per[meas] = {"n": int(len(g)), "observed_net_mean": round(float(net.mean()), 0),
                     **{f"{m}_net_mae": round(float((g[f"{m}_electricity"] + g[f"{m}_gas"] - net).abs().mean()), 0)
                        for m in ("naive", "eng", "cal")}}
    res["per_measure"] = per
    return res


# ------------------------------------------------------------------------------------------
# 3. Value
# ------------------------------------------------------------------------------------------

def eval_value(ds, splits, truth, ctx, card) -> dict:
    sales, props = value_table(ds, splits)
    dev = sales[sales["split"].isin(["train", "validation"])].reset_index(drop=True)
    te = sales[sales["split"] == "test"].reset_index(drop=True)
    vm = joblib.load(MODELS_DIR / "value_models.joblib")
    level = vm["level"]
    p_dev, s_dev = [props[x] for x in dev["property_id"]], list(dev["sap_at_sale"].astype(float))
    p_te, s_te = [props[x] for x in te["property_id"]], list(te["sap_at_sale"].astype(float))
    y = te["price_today"].to_numpy()
    pt, lo, hi = level.predict(p_te, s_te)
    covered = (y >= lo) & (y <= hi)
    # every candidate, refit on train+validation, scored on test (transparency, not selection)
    cv = card["value"]["cv"]
    best_gbm = min((k for k in cv if k.startswith("gbm")), key=lambda k: cv[k]["median_ape_pct"])
    lr, leaves = best_gbm.split("_lr")[1].split("_l")
    cands = {"regional": ValueLevel("regional"), "hedonic": ValueLevel("hedonic"),
             best_gbm: ValueLevel("gbm", {"learning_rate": float(lr), "max_leaf_nodes": int(leaves), "max_iter": 300,
                                          "min_samples_leaf": 30})}
    test_all = {}
    for k, mdl in cands.items():
        mdl.fit(p_dev, s_dev, dev["log_price"].to_numpy())
        test_all[k] = regression_metrics(y, np.exp(mdl.predict_log(p_te, s_te)))
    out = {"sales": int(len(te)), "chosen": card["value"]["chosen"], "cv": cv, "test_all_candidates": test_all,
           "test_chosen": regression_metrics(y, pt),
           "interval_80": {"coverage": round(float(covered.mean()), 3),
                           "median_width_pct": round(float(np.median((hi - lo) / pt) * 100), 1)},
           "protocol_note": card["value"].get("protocol_note")}
    test_ids = splits.loc[splits["split"] == "test", "property_id"]
    tv = truth.set_index("property_id")["true_value_2026"]
    errs = []
    for pid in test_ids:
        f = analyse_home(ds.property(pid), ctx)
        if f.value and f.value.current_value:
            errs.append(abs(f.value.current_value / tv[pid] - 1))
    out["current_value_vs_truth_median_ape_pct"] = round(float(np.median(errs)) * 100, 1)
    out["current_value_homes"] = len(errs)
    hed = vm["hedonic"].summary()
    out["hedonic_premiums_vs_planted"] = {b: {**hed[b], "planted_pct": round(W.EPC_PREMIUM[b] * 100, 1)} for b in hed}
    return out


# ------------------------------------------------------------------------------------------
# 4-7. Pipeline-level evaluations on test homes
# ------------------------------------------------------------------------------------------

def _true_inputs(row: dict) -> tuple[dict, float | None]:
    s, h = W.hidden_state(row)
    ob = lambda v: Resolved(value=v, basis="observed")  # noqa: E731
    na = Resolved(value=None, basis="not_applicable")
    inp = {
        "age_band": ob(s["age_band"]), "floor_area_m2": ob(s["floor_area_m2"]), "has_loft": ob(bool(s["has_roof"])),
        "has_ground_floor": ob(bool(s["has_ground_floor"])), "wall_type": ob(s["wall_type"]),
        "wall_insulated": ob(bool(s["wall_insulated"])),
        "loft_insulation_mm": ob(s["loft_mm"]) if s["has_roof"] else na,
        "floor_insulated": ob(bool(s["floor_insulated"])) if s["has_ground_floor"] else na,
        "glazing": ob(s["glazing"]), "heating_system": ob(s["heating_system"]),
        "boiler_age_years": ob(s["boiler_age"]) if s["heating_system"].startswith("gas") else na,
        "controls": ob(s["controls"]), "solar_pv_kwp": ob(float(s["pv_kwp"])),
        "sap_score": ob(float(row["true_sap_now"])),
    }
    if h["void"]:
        return inp, None
    ann = W.annual_normal(s, h)
    inp["intensity_kwh_m2"] = ob(ann["purchased"] / s["floor_area_m2"])
    return inp, ann["purchased"]


def eval_pipeline(ds, splits, truth, ctx, split: str = "test") -> tuple[dict, pd.DataFrame]:
    test_ids = list(splits.loc[splits["split"] == split, "property_id"])
    tr = truth.set_index("property_id")
    rows, score_rows = [], []
    feas = {"recommended": 0, "violations": 0, "violations_flagged_for_survey": 0, "truly_feasible": 0, "found": 0}
    feas_by_measure: dict[str, dict] = {}
    t0 = time.time()
    for pid in test_ids:
        p = ds.property(pid)
        f = analyse_home(p, ctx)
        row = tr.loc[pid].to_dict()
        row["property_id"] = pid
        s, h = W.hidden_state(row)
        true_inp, true_purchased = _true_inputs(row)

        # score robustness: recorded-data score vs score from the true state
        if true_purchased is not None:
            ts = compute_score(true_inp)
            score_rows.append({"status": f.score.status, "pred": f.score.score, "true": ts.score,
                               "pred_band": f.score.band, "true_band": ts.band,
                               "lo": f.score.score_range[0] if f.score.score_range else None,
                               "hi": f.score.score_range[1] if f.score.score_range else None})

        # feasibility vs the true state
        truly = W.truly_feasible(s)
        planned = {r.measure_id for r in f.plan}
        flagged = {r.measure_id for r in f.plan if any(k in u.lower() for u in r.uncertainty
                                                       for k in ("assumed", "not recorded", "survey", "confirm"))}
        for m, (ok, _) in truly.items():
            d = feas_by_measure.setdefault(m, {"recommended": 0, "violations": 0, "truly_feasible": 0, "found": 0})
            if m in planned:
                d["recommended"] += 1
                feas["recommended"] += 1
                if not ok:
                    d["violations"] += 1
                    feas["violations"] += 1
                    feas["violations_flagged_for_survey"] += m in flagged
            if ok:
                d["truly_feasible"] += 1
                feas["truly_feasible"] += 1
                if m in planned:
                    d["found"] += 1
                    feas["found"] += 1

        # counterfactual (oracle) improvement potential of OUR package on the TRUE home
        true_pot = None
        if f.package and true_purchased:
            st = dict(s)
            for m in f.package.measures:
                st = W.apply_measure(st, h, m)
            after = W.annual_normal(st, h)["purchased"]
            true_pot = 100 * (true_purchased - after) / true_purchased

        pk, ip = f.package, (f.package.improvement_potential if f.package else None)
        v = f.value
        rows.append({
            "property_id": pid, "customer_id": p.customer_id, "split": split,
            "score": f.score.score, "score_status": f.score.status, "band": f.score.band,
            "score_range_low": f.score.score_range[0] if f.score.score_range else None,
            "score_range_high": f.score.score_range[1] if f.score.score_range else None,
            "is_poor": f.score.is_poor, "confidence": f.confidence.level,
            "baseline_basis": f.baseline_basis,
            "baseline_electricity_kwh": f.baseline["electricity"].annual_kwh,
            "baseline_gas_kwh": f.baseline["gas"].annual_kwh,
            "intensity_kwh_m2": f.intensity_kwh_m2.value, "sap_used": f.sap.value, "sap_basis": f.sap.basis,
            "n_recommended": len(f.plan), "top_recommendation": f.plan[0].measure_id if f.plan else None,
            "package_measures": "|".join(pk.measures) if pk else None,
            "package_electricity_saving_kwh": pk.impact.electricity.saving_kwh if pk else None,
            "package_gas_saving_kwh": pk.impact.gas.saving_kwh if pk else None,
            "package_net_saving_kwh": pk.impact.net_saving_kwh if pk else None,
            "package_carbon_kg": pk.impact.carbon.total_kg if pk else None,
            "improvement_potential_status": ip.status if ip else None,
            "improvement_potential_pct": ip.pct if ip else None,
            "score_after": pk.score_after if pk else None, "epc_band_after": pk.epc_band_after if pk else None,
            "value_current_gbp": v.current_value if v else None,
            "value_uplift_pct_low": v.uplift_pct_range[0] if v and v.uplift_pct_range else None,
            "value_uplift_pct_high": v.uplift_pct_range[1] if v and v.uplift_pct_range else None,
            "conflicts": "|".join(c.code for c in f.conflicts),
            "floor_area_m2": p.floor_area_m2, "metered_total_kwh": (
                f.baseline["electricity"].annual_kwh + f.baseline["gas"].annual_kwh
                if f.baseline_basis == "metered" else None),
            "recorded_sap": p.sap_score,
            "_true_potential_pct": true_pot,
        })
    preds = pd.DataFrame(rows)
    sc = pd.DataFrame(score_rows)
    pointed = sc[sc["status"] != "partial"]
    partial = sc[sc["status"] == "partial"]
    score_eval = {
        "homes": int(len(sc)),
        "point_scores": int(len(pointed)),
        "score_mae_vs_true_inputs": round(float((pointed["pred"] - pointed["true"]).abs().mean()), 2),
        "band_agreement": round(float((pointed["pred_band"] == pointed["true_band"]).mean()), 3),
        "complete_only_mae": round(float((pointed[pointed.status == "complete"]["pred"]
                                          - pointed[pointed.status == "complete"]["true"]).abs().mean()), 2),
        "partial_homes": int(len(partial)),
        "partial_range_coverage": round(float(((partial["true"] >= partial["lo"]) & (partial["true"] <= partial["hi"])).mean()), 3)
        if len(partial) else None,
    }

    # ranking of poor homes by improvement potential vs the oracle
    poor = preds[(preds["is_poor"] == True) & (preds["improvement_potential_status"] == "available")  # noqa: E712
                 & preds["_true_potential_pct"].notna()].copy()
    truth_pot = poor["_true_potential_pct"]
    crit = {
        "greeniq_improvement_potential": poor["improvement_potential_pct"],
        "baseline_total_kwh (big-house trap)": poor["metered_total_kwh"],
        "baseline_worst_epc_first": -poor["recorded_sap"].fillna(poor["recorded_sap"].median()),
        "baseline_intensity": poor["intensity_kwh_m2"],
    }
    k = max(1, int(round(0.2 * len(poor))))
    true_top = set(poor.nlargest(k, "_true_potential_pct")["property_id"])
    area = poor["floor_area_m2"].fillna(poor["floor_area_m2"].median())
    ranking = {"poor_homes_ranked": int(len(poor)), "top_k": k, "methods": {},
               "true_potential_spearman_with_floor_area": round(float(spearmanr(truth_pot, area).statistic), 3)}
    for name, c in crit.items():
        top = set(poor.assign(c=c.values).nlargest(k, "c")["property_id"])
        ranking["methods"][name] = {
            "spearman_vs_true_potential": round(float(spearmanr(c, truth_pot, nan_policy="omit").statistic), 3),
            "top20pct_precision": round(len(top & true_top) / k, 3),
            "spearman_with_floor_area": round(float(spearmanr(c, area, nan_policy="omit").statistic), 3),
        }
    feas_eval = {**feas, "violation_rate": round(feas["violations"] / max(feas["recommended"], 1), 4),
                 "recall": round(feas["found"] / max(feas["truly_feasible"], 1), 3), "by_measure": feas_by_measure}
    timing = round((time.time() - t0) / len(test_ids) * 1000, 1)
    return {"score": score_eval, "ranking": ranking, "feasibility": feas_eval, "ms_per_home_with_models": timing}, preds


def eval_rating(ds, splits, ctx, split: str = "test") -> dict:
    """Hide recorded SAPs on held-out homes and estimate them; compare with a peer-median baseline."""
    tr_ids = set(splits.loc[splits["split"] == "train", "property_id"])
    te_ids = list(splits.loc[splits["split"] == split, "property_id"])
    train = [ds.property(pid) for pid in tr_ids]
    peer = pd.DataFrame([(p.property_type, p.age_band, p.sap_score) for p in train if p.sap_score is not None],
                        columns=["t", "a", "s"])
    by_pair = peer.groupby(["t", "a"])["s"].median().to_dict()
    by_type = peer.groupby("t")["s"].median().to_dict()
    est, base, true = [], [], []
    for pid in te_ids:
        p = ds.property(pid)
        if p.sap_score is None:
            continue
        hidden = p.model_copy(update={"sap_score": None, "epc_band": None, "epc_year": None, "retrofits_completed": []})
        f = analyse_home(hidden, ctx)
        if f.sap.basis != "estimated":
            continue
        est.append(f.sap.value)
        base.append(by_pair.get((p.property_type, p.age_band), by_type.get(p.property_type, peer["s"].median())))
        true.append(p.sap_score)
    true, est, base = map(np.array, (true, est, base))
    return {"homes": int(len(true)),
            "rating_model": {**regression_metrics(true, est), "band_accuracy": _band_accuracy(est, true)},
            "peer_median_baseline": {**regression_metrics(true, base), "band_accuracy": _band_accuracy(base, true)}}


def _band_accuracy(pred, true) -> float:
    return round(float(np.mean([sap_to_band(a) == sap_to_band(b) for a, b in zip(pred, true)])), 3)


def eval_conflicts(ds, truth, ctx) -> dict:
    """Rule-based checks have no trained parameters, so they are graded on all homes."""
    tr = truth.set_index("property_id")
    tp = fp = fn = 0
    for pid in ds.property_ids:
        p = ds.property(pid)
        planted = bool(tr.loc[pid, "recorded_heating_error"])
        if not planted and not (p.heating_system and not p.heating_system.startswith("gas")):
            continue  # only homes where the conflict could fire
        f = analyse_home(p, ctx)
        flagged = any(c.code == "heating_system_vs_gas_use" for c in f.conflicts)
        tp += planted and flagged
        fp += (not planted) and flagged
        fn += planted and not flagged
    return {"heating_record_errors_planted": int(tp + fn), "detected": int(tp), "false_alarms": int(fp),
            "precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(tp + fn, 1), 3)}


# ------------------------------------------------------------------------------------------

def _finite(x):
    """NaN/inf are not JSON: write them as null (a metric that could not be computed)."""
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_finite(v) for v in x]
    if isinstance(x, float | np.floating) and not np.isfinite(x):
        return None
    return x


def evaluate_all(log=print) -> dict:
    t0 = time.time()
    ds, splits, truth = load_dataset(), load_splits(), load_truth()
    ctx_engine = load_context(with_models=False)
    ctx = load_context(with_models=True)
    card = load_card()
    REPORTS.mkdir(exist_ok=True)
    m = {"git_commit": git_commit(), "model_version": card["version"], "evaluated_at": time.strftime("%Y-%m-%d %H:%M"),
         "split_counts": splits["split"].value_counts().to_dict()}
    # PS2 §11/§13G: metrics and baseline comparisons on the VALIDATION set (where tuning happened),
    # then the same metrics once on the untouched TEST set as the held-out confirmation.
    log("validation set: energy, savings, pipeline, rating…")
    v_pipe, _ = eval_pipeline(ds, splits, truth, ctx, "validation")
    m["validation"] = {"energy": eval_energy(ds, splits, ctx.weather, "validation"),
                       "savings": eval_savings(ds, splits, ctx_engine, card, "validation"),
                       **v_pipe, "rating": eval_rating(ds, splits, ctx, "validation"),
                       "value_cv": card["value"]["cv"], "value_chosen": card["value"]["chosen"]}
    log("retrofit impacts on the brief's quantities…")
    from .impacts import write as write_impacts
    m["retrofit_impacts"] = write_impacts("validation")
    log("energy models…")
    m["energy"] = eval_energy(ds, splits, ctx.weather)
    log("savings vs observed retrofits…")
    m["savings"] = eval_savings(ds, splits, ctx_engine, card)
    log("value…")
    m["value"] = eval_value(ds, splits, truth, ctx, card)
    log("pipeline on test homes (score, ranking, feasibility)…")
    pipe, preds = eval_pipeline(ds, splits, truth, ctx)
    m.update(pipe)
    log("rating estimation…")
    m["rating"] = eval_rating(ds, splits, ctx)
    log("conflict detection…")
    m["conflicts"] = eval_conflicts(ds, truth, ctx)
    m["validation_card"] = {"energy": card["energy"], "calibration": card["calibration"]["validation"],
                            "calibration_rates": card["calibration"]["rates"]}
    preds.drop(columns=["_true_potential_pct"]).to_csv(REPORTS / "test_predictions.csv", index=False)
    (REPORTS / "metrics.json").write_text(json.dumps(_finite(m), indent=2, default=float), encoding="utf-8")
    from .report import render
    (REPORTS / "EVALUATION.md").write_text(render(m), encoding="utf-8")
    log(f"done in {time.time() - t0:.0f}s → reports/EVALUATION.md, metrics.json, test_predictions.csv")
    return m
