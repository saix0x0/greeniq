"""Model registry: load trained artifacts and plug the *promoted* ones into the pipeline.

Promotion rule (decided at training time on the VALIDATION split, recorded in
models/model_card.json): an advanced provider is used only if it beat the simple
baseline. Otherwise the baseline stays. The test split plays no part in this choice.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib

from ..contract import Property, Receipt
from ..data import ROOT
from ..facts import ValueResult
from ..score import sap_to_band
from .features import feature_frame

MODELS_DIR = ROOT / "models"
VALUE_CAVEAT = ("Indicative estimate based on historical relationships between EPC bands and sale prices in our "
                "(synthetic) dataset, holding the home's other characteristics constant. Not a valuation, not a "
                "guarantee, and not proof that retrofitting causes a price rise.")


class EnergyEstimator:
    """Per-fuel annual kWh from characteristics (only used when meters are insufficient)."""

    def __init__(self, models: dict, choice: dict[str, str], version: str):
        self.models, self.choice, self.version = models, choice, version
        self.name = "energy model: " + ", ".join(f"{f}={c}" for f, c in choice.items())

    def predict(self, p: Property, inp) -> dict[str, float]:
        out = {}
        for fuel, kind in self.choice.items():
            m = self.models[fuel][kind]
            if kind == "gbm":
                out[fuel] = float(m.predict(feature_frame([p]))[0])
            else:
                out[fuel] = float(m.predict([p])[0])
        if p.has_gas_connection is False:
            out["gas"] = 0.0
        return {k: max(v, 0.0) for k, v in out.items()}


class ValueModel:
    def __init__(self, level, hedonic, version: str):
        self.level, self.hedonic, self.version = level, hedonic, version
        self.name = f"value: {level.name} + conformal interval; hedonic EPC-premium uplift"

    def estimate(self, p: Property, inp, sap_before: float | None, sap_after: float | None) -> ValueResult:
        if p.floor_area_m2 is None:
            return ValueResult(status="unavailable", caveat=VALUE_CAVEAT, provider=self.name,
                               reason="Floor area is needed for a value estimate.")
        point, lo, hi = (float(a[0]) for a in self.level.predict([p], [sap_before]))

        def r500(x):
            return int(round(x / 500.0) * 500)

        current, cur_rng = r500(point), (r500(lo), r500(hi))
        receipt = Receipt(output="value", value=current, unit="GBP (today's prices)",
                          inputs={"sap_before": sap_before, "sap_after": sap_after},
                          method=self.name, method_version=self.version, provider="ml",
                          sources=["models/model_card.json", "reports/EVALUATION.md §3"],
                          notes=[f"current-value interval: split-conformal {int(self.level.coverage * 100)}%",
                                 "uplift: P10-P90 of property-clustered bootstrap of EPC band premiums"])
        if sap_before is None or sap_after is None:
            return ValueResult(status="unavailable", current_value=current, current_range=cur_rng, caveat=VALUE_CAVEAT,
                               provider=self.name, receipt=receipt,
                               reason="No rating before/after, so no indicative value impact can be estimated.")
        b0, b1 = sap_to_band(sap_before), sap_to_band(sap_after)
        rng = self.hedonic.uplift_range(b0, b1)
        if rng is None:
            return ValueResult(status="unavailable", current_value=current, current_range=cur_rng, band_before=b0,
                               band_after=b1, caveat=VALUE_CAVEAT, provider=self.name, receipt=receipt,
                               reason=f"Too few sales in band {b0 if self.hedonic.premium_draws(b0) is None else b1} "
                                      "to estimate a premium.")
        lo_pct, hi_pct = round(rng[0], 1), round(rng[1], 1)
        reason = None
        if b0 == b1:
            reason = f"The package is not expected to change the EPC band ({b0}), so no indicative value impact."
        receipt.inputs.update({"band_before": b0, "band_after": b1})
        return ValueResult(
            status="available", current_value=current, current_range=cur_rng, uplift_pct_range=(lo_pct, hi_pct),
            uplift_gbp_range=(r500(current * lo_pct / 100), r500(current * hi_pct / 100)),
            value_after_range=(r500(current * (1 + lo_pct / 100)), r500(current * (1 + hi_pct / 100))),
            band_before=b0, band_after=b1, caveat=VALUE_CAVEAT, reason=reason, provider=self.name, receipt=receipt)


def load_card(models_dir: Path = MODELS_DIR) -> dict:
    return json.loads((models_dir / "model_card.json").read_text(encoding="utf-8"))


def attach_models(ctx, models_dir: Path = MODELS_DIR) -> None:
    """Attach promoted providers to an EngineContext (raises FileNotFoundError if untrained)."""
    card = load_card(models_dir)
    energy = joblib.load(models_dir / "energy_models.joblib")
    ctx.energy_estimator = EnergyEstimator(energy, card["energy"]["promoted"], card["version"])
    cal = card["calibration"]
    if cal["promoted"]:
        ctx.calibration = {k: v["rate"] for k, v in cal["rates"].items()}
        ctx.calibration_name = "calibrated (realisation rates learned from past retrofits)"
    value = joblib.load(models_dir / "value_models.joblib")
    ctx.value_model = ValueModel(value["level"], value["hedonic"], card["version"])
