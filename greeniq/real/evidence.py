"""Real-data evidence from NEED: an energy model scored on real homes, and real retrofit savings.

``uv run python -m greeniq real-evidence`` → models/need_energy.joblib, reports/REAL_DATA.md, reports/real_data.json

R2 · Energy model on real homes
    Target: real annual consumption (latest year, 2024; gas only for gas-heated homes).
    Features: property type, age band, floor-area band, region, EPC band, gas heating, conservatory,
    council-tax band, and loft / cavity / solar install flags. All are known before any meter
    reading, so there is no leakage. The deprivation index is deliberately NOT used.
    Baseline to beat: median of similar homes (type × floor-area band × age band, train split).
    Protocol: fit on train, choose settings on validation, score test once.

R3 · What retrofits really saved (difference-in-differences)
    For each home that got loft insulation, cavity wall insulation or solar PV in year y:
        installer change   s = (use[y-1] − use[y+1]) / use[y-1]
        control change     c = median of the same ratio over similar homes (same type, age band,
                               floor-area band, region) that never had any of the three installed,
                               for the same years
        saving             s − c        (removes national trends, prices and, for electricity, weather)\n    Reported as the MEDIAN over installers with a bootstrap 90% interval (ratios are heavy-tailed).
    Gas is weather-corrected by DESNZ; solar is measured on electricity (grid imports). Estimated on
    train + validation installers; the test installers are reported separately as a stability check.
    Caveats: NEED records the *latest* government-scheme install, which can be a top-up; the
    effect is an average over homes that chose to install (not a randomised trial).
"""

from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ..data import ROOT
from ..ml.metrics import regression_metrics
from .need import load_need, summary

REPORTS, MODELS = ROOT / "reports", ROOT / "models"
FEATURES = ["property_type", "age_code", "area_code", "region", "epc", "gas_main_heating", "conservatory",
            "council_tax_band", "loft_installed", "cavity_installed", "pv_installed"]
CATEGORICAL = ["property_type", "region", "epc", "council_tax_band"]
SEED = 20261011


def _X(d: pd.DataFrame, cats: dict[str, list]) -> pd.DataFrame:
    X = pd.DataFrame(index=d.index)
    for f in FEATURES:
        if f in CATEGORICAL:
            X[f] = d[f].map({v: i for i, v in enumerate(cats[f])}).astype(float)
        else:
            X[f] = d[f].astype(float)
    return X


def _peer(train: pd.DataFrame, target: str, rows: pd.DataFrame) -> np.ndarray:
    keys = [["property_type", "area_code", "age_code"], ["property_type", "area_code"], ["area_code"]]
    meds = [train.groupby(k)[target].agg(["median", "size"]) for k in keys]
    out = []
    for _, r in rows.iterrows():
        v = None
        for k, m in zip(keys, meds):
            idx = tuple(r[c] for c in k) if len(k) > 1 else r[k[0]]
            if idx in m.index and m.loc[idx, "size"] >= 30:
                v = m.loc[idx, "median"]
                break
        out.append(train[target].median() if v is None else v)
    return np.array(out)


def energy_model(d: pd.DataFrame, log=print) -> tuple[dict, dict]:
    cats = {c: sorted(d[c].dropna().unique().tolist()) for c in CATEGORICAL}
    mask = [f in CATEGORICAL for f in FEATURES]
    res, models = {}, {"features": FEATURES, "categories": cats}
    for fuel, target, rows in (("electricity", "elec_2024", d),
                               ("gas", "gas_2024", d[d["gas_main_heating"]])):
        rows = rows[rows[target].notna()]
        tr, va, te = (rows[rows["split"] == s] for s in ("train", "validation", "test"))
        best = None
        for lr in (0.05, 0.1):
            for leaves in (15, 31):
                for iters in (200, 400):
                    m = HistGradientBoostingRegressor(loss="poisson", learning_rate=lr, max_leaf_nodes=leaves,
                                                      max_iter=iters, min_samples_leaf=40, categorical_features=mask,
                                                      random_state=SEED)
                    m.fit(_X(tr, cats), tr[target])
                    mae = float(np.abs(m.predict(_X(va, cats)) - va[target]).mean())
                    if best is None or mae < best[0]:
                        best = (mae, {"learning_rate": lr, "max_leaf_nodes": leaves, "max_iter": iters}, m)
        m = best[2]
        y = te[target].to_numpy()
        gbm, peer = m.predict(_X(te, cats)), _peer(tr, target, te)
        by_type = {t: regression_metrics(y[(te["property_type"] == t).to_numpy()],
                                         gbm[(te["property_type"] == t).to_numpy()])["median_ape_pct"]
                   for t in sorted(te["property_type"].unique())}
        res[fuel] = {"rows": {"train": len(tr), "validation": len(va), "test": len(te)}, "params": best[1],
                     "test": {"global_median": regression_metrics(y, np.full(len(y), tr[target].median())),
                              "peer_median": regression_metrics(y, peer), "gbm": regression_metrics(y, gbm)},
                     "gbm_median_ape_by_type": by_type,
                     "promoted": "gbm" if regression_metrics(va[target], m.predict(_X(va, cats)))["mae"]
                     < regression_metrics(va[target], _peer(tr, target, va))["mae"] else "peer"}
        models[fuel] = m
        t = res[fuel]["test"]
        log(f"  real {fuel}: test MAE peer {t['peer_median']['mae']:.0f} · gbm {t['gbm']['mae']:.0f} kWh "
            f"(R² {t['gbm']['r2']}) on {len(te)} real homes")
    return res, models


def _did(d: pd.DataFrame, measure: str, fuel: str, rng) -> dict:
    flag, year = {"loft": ("loft_installed", "loft_year"), "cavity": ("cavity_installed", "cavity_year"),
                  "solar_pv": ("pv_installed", "pv_year")}[measure]
    col = "gas_{}" if fuel == "gas" else "elec_{}"
    base = d[d["gas_main_heating"]] if fuel == "gas" else d
    never = base[~(base["loft_installed"] | base["cavity_installed"] | base["pv_installed"])]
    inst = base[base[flag] & base[year].between(2006, 2023)]
    cells = ["property_type", "age_code", "area_code", "region"]
    out = {}
    for split_name, split_set in (("estimate", ("train", "validation")), ("check", ("test",))):
        rows = []
        for y, grp in inst[inst["split"].isin(split_set)].groupby(inst[year].astype(int)):
            pre, post = col.format(y - 1), col.format(y + 1)
            if pre not in d or post not in d:
                continue
            g = grp[grp[pre].notna() & grp[post].notna()]
            ctrl = never[never[pre].notna() & never[post].notna()]
            ctrl = ctrl.assign(r=(ctrl[pre] - ctrl[post]) / ctrl[pre])
            fine = ctrl.groupby(cells)["r"].agg(["median", "size"])
            coarse = ctrl.groupby(["property_type", "area_code"])["r"].agg(["median", "size"])
            for _, r in g.iterrows():
                k = tuple(r[c] for c in cells)
                if k in fine.index and fine.loc[k, "size"] >= 10:
                    c = fine.loc[k, "median"]
                elif (r["property_type"], r["area_code"]) in coarse.index:
                    c = coarse.loc[(r["property_type"], r["area_code"]), "median"]
                else:
                    continue
                s = (r[pre] - r[post]) / r[pre]
                rows.append((s - c, (s - c) * r[pre], r[pre]))
        if not rows:
            out[split_name] = {"n": 0}
            continue
        a = np.array(rows)
        # Median, not mean: ratios from homes with small "before" use are heavy-tailed and swamp a mean.
        boots = [np.median(a[rng.integers(0, len(a), len(a)), 0]) for _ in range(1000)]
        out[split_name] = {"n": int(len(a)), "saving_pct": round(100 * float(np.median(a[:, 0])), 2),
                           "ci90_pct": [round(100 * float(np.percentile(boots, 5)), 2),
                                        round(100 * float(np.percentile(boots, 95)), 2)],
                           "mean_pct_unrobust": round(100 * float(a[:, 0].mean()), 2),
                           "saving_kwh": round(float(np.median(a[:, 1])), 0),
                           "pre_use_kwh_median": round(float(np.median(a[:, 2])), 0)}
    return out


def retrofit_evidence(d: pd.DataFrame, log=print) -> dict:
    rng = np.random.default_rng(SEED)
    res = {}
    for measure, fuel in (("loft", "gas"), ("cavity", "gas"), ("solar_pv", "electricity")):
        res[measure] = {"fuel": fuel, **_did(d, measure, fuel, rng)}
        e = res[measure]["estimate"]
        if e.get("n"):
            log(f"  real {measure}: {fuel} saving {e['saving_pct']}% (90% CI {e['ci90_pct']}) "
                f"≈ {e['saving_kwh']:.0f} kWh/yr, n={e['n']}")
    return res


def engine_comparison(log=print) -> dict:
    """What our engine predicts, on average, for the same measures in the app's homes (same fuel, %)."""
    from ..context import load_context
    from ..data import load_dataset
    from ..pipeline import analyse_home

    ds, ctx = load_dataset(), load_context(with_models=False)  # uncalibrated engineering engine
    acc = {"loft": [], "cavity": [], "solar_pv": []}
    mid = {"loft_insulation": "loft", "cavity_wall_insulation": "cavity", "solar_pv": "solar_pv"}
    for pid in ds.property_ids:
        f = analyse_home(ds.property(pid), ctx)
        if f.baseline_basis != "metered":
            continue
        for r in f.plan:
            if r.measure_id not in mid:
                continue
            fuel = "electricity" if r.measure_id == "solar_pv" else "gas"
            b = getattr(r.standalone, fuel).baseline_kwh
            if b and b > 0 and (fuel == "electricity" or f.baseline["gas"].basis == "metered"):
                acc[mid[r.measure_id]].append(100 * getattr(r.standalone, fuel).saving_kwh / b)
    out = {k: {"n_homes": len(v), "engine_mean_pct": round(float(np.mean(v)), 2) if v else None} for k, v in acc.items()}
    for k, v in out.items():
        log(f"  engine {k}: mean predicted saving {v['engine_mean_pct']}% over {v['n_homes']} app homes")
    return out


def run(log=print) -> dict:
    t0 = time.time()
    d = load_need()
    log("R1 · NEED loaded and validated")
    s = summary(d)
    log("R2 · energy model on real homes")
    energy, models = energy_model(d, log)
    MODELS.mkdir(exist_ok=True)
    joblib.dump(models, MODELS / "need_energy.joblib")
    log("R3 · real retrofit savings (difference-in-differences)")
    evidence = retrofit_evidence(d, log)
    engine = engine_comparison(log)
    for k in evidence:
        e = evidence[k].get("estimate", {})
        p = engine[k]["engine_mean_pct"]
        evidence[k]["engine_mean_pct"] = p
        evidence[k]["realisation_vs_engine"] = round(e["saving_pct"] / p, 2) if e.get("n") and p else None
    from .benchmarks import build
    bench = build(d, evidence)
    log(f"R4 · benchmarks written: {sum(len(v) for v in bench['peers'].values())} peer cells, evidence for {list(bench['evidence'])}")
    out = {"summary": s, "energy": energy, "retrofit_evidence": evidence, "seconds": round(time.time() - t0, 1)}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "real_data.json").write_text(json.dumps(out, indent=2, default=float))
    from .report import render
    (REPORTS / "REAL_DATA.md").write_text(render(out))
    log(f"done in {out['seconds']} s → reports/REAL_DATA.md")
    return out
