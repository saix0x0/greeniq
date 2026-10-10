"""GreenIQ's learned models and the simple baselines they must beat.

Energy (per fuel, annual purchased kWh from characteristics):
    PeerMedianEnergy   simple baseline: peer-group median kWh/m² × floor area
    PhysicsEnergy      engineering baseline: the engine's RdSAP-lite estimate
    GBMEnergy          gradient boosting (Poisson loss, native missing-value handling)

Value:
    RegionalPerM2Value simple baseline: regional median £/m² × floor area
    GBMValue           gradient boosting on log(price in today's terms) + split-conformal interval
    HedonicPremium     log-linear hedonic regression with EPC band dummies; property-clustered
                       bootstrap gives the uplift range (the PS2 "range, never a single number")
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ..contract import Property
from ..engines.energy import physics_estimate
from ..features.resolve import resolve_inputs
from .features import FEATURES, categorical_mask, feature_frame

SEED = 20261010


def heating_group(p: Property) -> str:
    hs = p.heating_system or "unknown"
    if hs.startswith("gas"):
        return "gas"
    if hs.endswith("heat_pump"):
        return "heat_pump"
    return "electric" if hs != "unknown" else "unknown"


# ------------------------------------------------------------------------------------------
# Energy
# ------------------------------------------------------------------------------------------

class PeerMedianEnergy:
    name = "peer-median baseline"

    def fit(self, props: list[Property], y: np.ndarray, min_n: int = 15):
        df = pd.DataFrame({"type": [p.property_type for p in props], "heat": [heating_group(p) for p in props],
                           "area": [p.floor_area_m2 for p in props], "y": y})
        ok = df["area"].notna()
        df.loc[ok, "int"] = df.loc[ok, "y"] / df.loc[ok, "area"]
        self.by_pair = {k: g["int"].median() for k, g in df[ok].groupby(["type", "heat"]) if len(g) >= min_n}
        self.by_heat = {k: g["int"].median() for k, g in df[ok].groupby("heat") if len(g) >= min_n}
        self.global_int = float(df.loc[ok, "int"].median())
        self.global_kwh = float(df["y"].median())
        return self

    def predict(self, props: list[Property]) -> np.ndarray:
        out = []
        for p in props:
            key = (p.property_type, heating_group(p))
            i = self.by_pair.get(key, self.by_heat.get(key[1], self.global_int))
            out.append(i * p.floor_area_m2 if p.floor_area_m2 else self.global_kwh)
        return np.array(out)


class PhysicsEnergy:
    name = "physics baseline (RdSAP-lite)"

    def __init__(self, weather):
        self.weather = weather

    def predict(self, props: list[Property], fuel: str, fallback: np.ndarray) -> np.ndarray:
        out = []
        for i, p in enumerate(props):
            if not p.heating_system:
                out.append(fallback[i])
                continue
            inp = resolve_inputs(p)
            est = physics_estimate(p.property_type, inp, p.heating_system, p.region, self.weather.normal_year(p.region),
                                   p.boiler_age_years)
            out.append(est[fuel])
        return np.array(out)


class GBMEnergy:
    name = "gradient boosting (HistGBR, Poisson)"

    def __init__(self, learning_rate=0.06, max_leaf_nodes=31, max_iter=400, l2_regularization=1.0,
                 min_samples_leaf=20):
        self.params = dict(learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes, max_iter=max_iter,
                           l2_regularization=l2_regularization, min_samples_leaf=min_samples_leaf)

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        self.model = HistGradientBoostingRegressor(loss="poisson", categorical_features=categorical_mask(),
                                                   early_stopping=False, random_state=SEED, **self.params)
        self.model.fit(X[FEATURES], y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[FEATURES])


# ------------------------------------------------------------------------------------------
# Value
# ------------------------------------------------------------------------------------------

class RegionalPerM2Value:
    name = "regional £/m² baseline"

    def fit(self, regions, areas, price_today):
        df = pd.DataFrame({"r": regions, "a": areas, "p": price_today})
        ok = df["a"].notna()
        self.per_m2 = {k: g["p"].div(g["a"]).median() for k, g in df[ok].groupby("r")}
        self.per_region = {k: g["p"].median() for k, g in df.groupby("r")}
        return self

    def predict(self, regions, areas) -> np.ndarray:
        return np.array([self.per_m2[r] * a if a is not None and a == a else self.per_region[r]
                         for r, a in zip(regions, areas)])


class GBMValue:
    name = "gradient boosting on log price (HistGBR) + split-conformal 80% interval"

    def __init__(self, learning_rate=0.05, max_leaf_nodes=31, max_iter=500, l2_regularization=1.0,
                 min_samples_leaf=20):
        self.params = dict(learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes, max_iter=max_iter,
                           l2_regularization=l2_regularization, min_samples_leaf=min_samples_leaf)
        self.q_lo = self.q_hi = None

    def fit(self, X: pd.DataFrame, log_price: np.ndarray):
        self.model = HistGradientBoostingRegressor(loss="squared_error", categorical_features=categorical_mask(),
                                                   early_stopping=False, random_state=SEED, **self.params)
        self.model.fit(X[FEATURES], log_price)
        return self

    def calibrate_interval(self, X_val: pd.DataFrame, log_price_val: np.ndarray, coverage: float = 0.8):
        """Split-conformal: interval from validation residual quantiles (no test data involved)."""
        resid = log_price_val - self.predict_log(X_val)
        a = (1 - coverage) / 2
        self.q_lo, self.q_hi = float(np.quantile(resid, a)), float(np.quantile(resid, 1 - a))
        self.coverage = coverage
        return self

    def predict_log(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[FEATURES])

    def predict(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        lp = self.predict_log(X)
        return np.exp(lp), np.exp(lp + self.q_lo), np.exp(lp + self.q_hi)


BANDS = ["A", "B", "C", "D", "E", "F", "G"]
HEDONIC_REF = "D"


class HedonicPremium:
    """log(price_today) = controls + Σ β_band · 1[band] ; β_D = 0. Bootstrap clusters by property."""

    name = "hedonic regression (EPC band premiums) + property-clustered bootstrap"

    def _design(self, df: pd.DataFrame) -> np.ndarray:
        # plain numpy (pandas comparisons cost ~5 ms per single-home call)
        reg = np.asarray(df["region"].tolist(), dtype=object)
        typ = np.asarray(df["property_type"].tolist(), dtype=object)
        age = np.asarray([a if isinstance(a, str) else "unknown" for a in df["age_band"].tolist()], dtype=object)
        band = np.asarray(df["band"].tolist(), dtype=object)
        cols = [np.ones(len(df))]
        cols += [(reg == r).astype(float) for r in ["south_east", "south_west", "midlands", "north", "wales", "scotland"]]
        cols += [(typ == t).astype(float) for t in ["detached", "terraced", "bungalow", "flat"]]
        cols += [(age == a).astype(float) for a in ["pre_1919", "1919_1944", "1965_1980", "1981_2002", "post_2002",
                                                    "unknown"]]
        cols.append(np.log(np.asarray(df["floor_area_m2"].tolist(), dtype=float)))
        cols += [(band == b).astype(float) for b in self.band_cols]
        return np.column_stack(cols)

    def fit(self, df: pd.DataFrame, n_boot: int = 300, min_band_n: int = 8, bootstrap: bool = True):
        """``df`` columns: property_id, region, property_type, age_band, floor_area_m2, band, log_price."""
        df = df[df["floor_area_m2"].notna()].reset_index(drop=True)
        counts = df["band"].value_counts()
        self.band_cols = [b for b in BANDS if b != HEDONIC_REF and counts.get(b, 0) >= min_band_n]
        self.band_n = {b: int(counts.get(b, 0)) for b in BANDS}
        X, y = self._design(df), df["log_price"].values
        self.coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        k = len(self.band_cols)
        self.point = dict(zip(self.band_cols, self.coef[-k:]))
        if not bootstrap:
            self.draws = np.array([self.coef[-k:]])
            return self
        rng = np.random.default_rng(SEED)
        pids = df["property_id"].unique()
        groups = {pid: idx for pid, idx in df.groupby("property_id").indices.items()}
        draws = []
        for _ in range(n_boot):
            pick = rng.choice(pids, size=len(pids), replace=True)
            idx = np.concatenate([groups[p] for p in pick])
            c, *_ = np.linalg.lstsq(X[idx], y[idx], rcond=None)
            draws.append(c[-k:])
        self.draws = np.array(draws)  # (n_boot, k)
        return self

    def predict_log(self, df: pd.DataFrame) -> np.ndarray:
        """Level prediction (log price, today's terms); NaN where floor area is unknown."""
        out = np.full(len(df), np.nan)
        ok = df["floor_area_m2"].notna().values
        if ok.any():
            sub = df[ok].copy()
            sub["band"] = sub["band"].where(sub["band"].isin(self.band_cols + [HEDONIC_REF]), HEDONIC_REF)
            out[ok] = self._design(sub) @ self.coef
        return out

    def premium_draws(self, band: str) -> np.ndarray | None:
        if band == HEDONIC_REF:
            return np.zeros(len(self.draws))
        if band not in self.band_cols:
            return None
        return self.draws[:, self.band_cols.index(band)]

    def uplift_range(self, band_before: str, band_after: str, lo: float = 10, hi: float = 90):
        """Indicative % uplift range (P10-P90 of bootstrap draws) from a band change, or None."""
        if band_before == band_after:
            return (0.0, 0.0)
        b0, b1 = self.premium_draws(band_before), self.premium_draws(band_after)
        if b0 is None or b1 is None:
            return None
        u = np.expm1(b1 - b0) * 100
        return float(np.percentile(u, lo)), float(np.percentile(u, hi))

    def summary(self) -> dict:
        out = {}
        for b in BANDS:
            d = self.premium_draws(b)
            if d is None:
                out[b] = {"n_sales": self.band_n.get(b, 0), "premium_pct": None}
            else:
                pt = 0.0 if b == HEDONIC_REF else float(self.point[b])
                out[b] = {"n_sales": self.band_n.get(b, 0), "premium_pct": round(float(np.expm1(pt) * 100), 2),
                          "p10": round(float(np.percentile(np.expm1(d) * 100, 10)), 2),
                          "p90": round(float(np.percentile(np.expm1(d) * 100, 90)), 2)}
        return out


def hedonic_frame(props: list[Property], saps: list[float | None]) -> pd.DataFrame:
    from ..score import sap_to_band
    return pd.DataFrame({
        "property_id": [p.property_id for p in props], "region": [p.region for p in props],
        "property_type": [p.property_type for p in props], "age_band": [p.age_band for p in props],
        "floor_area_m2": [p.floor_area_m2 for p in props],
        "band": [sap_to_band(s) if s is not None and s == s else HEDONIC_REF for s in saps],
    })


class ValueLevel:
    """Current-value model: one interface over candidate kinds, plus a split-conformal interval.

    kind = "regional" (simple baseline) | "hedonic" (log-linear OLS) | "gbm" (gradient boosting).
    Chosen by grouped cross-validation at training time; see greeniq/ml/train.py.
    """

    KINDS = ("regional", "hedonic", "gbm")
    LABELS = {"regional": "regional £/m² × floor area", "hedonic": "hedonic log-linear regression",
              "gbm": "gradient boosting on log price"}

    def __init__(self, kind: str, gbm_params: dict | None = None):
        assert kind in self.KINDS
        self.kind, self.gbm_params = kind, gbm_params or {}
        self.q_lo = self.q_hi = None
        self.coverage = None

    @property
    def name(self) -> str:
        return self.LABELS[self.kind]

    def fit(self, props: list[Property], saps: list[float | None], log_price: np.ndarray):
        self.regional = RegionalPerM2Value().fit([p.region for p in props], [p.floor_area_m2 for p in props],
                                                 np.exp(log_price))
        if self.kind == "hedonic":
            df = hedonic_frame(props, saps).assign(log_price=log_price)
            self.model = HedonicPremium().fit(df, bootstrap=False)
        elif self.kind == "gbm":
            self.model = GBMValue(**self.gbm_params).fit(feature_frame(props, saps), log_price)
        return self

    def predict_log(self, props: list[Property], saps: list[float | None]) -> np.ndarray:
        base = np.log(self.regional.predict([p.region for p in props], [p.floor_area_m2 for p in props]))
        if self.kind == "regional":
            return base
        if self.kind == "hedonic":
            lp = self.model.predict_log(hedonic_frame(props, saps))
            return np.where(np.isnan(lp), base, lp)
        return self.model.predict_log(feature_frame(props, saps))

    def set_interval(self, residuals: np.ndarray, coverage: float = 0.8):
        a = (1 - coverage) / 2
        self.q_lo, self.q_hi = float(np.quantile(residuals, a)), float(np.quantile(residuals, 1 - a))
        self.coverage = coverage
        return self

    def predict(self, props: list[Property], saps: list[float | None]):
        lp = self.predict_log(props, saps)
        return np.exp(lp), np.exp(lp + self.q_lo), np.exp(lp + self.q_hi)
