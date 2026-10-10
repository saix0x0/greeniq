"""Historical retrofits as natural experiments: predicted vs observed per-fuel savings.

For each home that installed a measure during the meter window we know (from the
installer record) its state before the work, and we have meter reads before and after.

    observed saving  = annualised(12 months before) − annualised(12 months after)
                       (both weather-normalised by degree-day regression, so a cold
                        or mild year does not masquerade as a saving)
    predicted saving = the engine's standalone saving for that measure, run on the
                       pre-retrofit record with only pre-retrofit meter data

These cases train the per-measure realisation rates (train split) and evaluate the
energy engine against reality (test split). Nothing from the hidden truth is used.
"""

from __future__ import annotations

import dataclasses
import json

import pandas as pd

from ..contract import FUELS
from ..data import Dataset, annualise_property
from ..facts import Scenario
from ..pipeline import EngineContext, analyse_home


@dataclasses.dataclass
class RetrofitCase:
    property_id: str
    measure_id: str
    install_month: str
    pre: object  # Property before the work
    observed: dict[str, float]  # per-fuel saving, kWh/yr
    pre_as_of: str
    pre_annual: dict[str, float]  # per-fuel baseline before the work


def build_cases(ds: Dataset, ctx: EngineContext, property_ids: set[str]) -> tuple[list[RetrofitCase], dict]:
    rh = ds.tables["retrofit_history"]
    cases, skipped = [], {"insufficient_meters": 0, "not_in_split": 0}
    for row in rh.itertuples(index=False):
        if row.property_id not in property_ids:
            skipped["not_in_split"] += 1
            continue
        now = ds.property(row.property_id)
        install = pd.Period(row.install_month, freq="M")
        pre_as_of, post_as_of = str(install - 1), str(install + 12)
        before = json.loads(row.before_json)
        pre = now.model_copy(update={**before, "retrofits_completed": []})
        a_pre = annualise_property(pre, ctx.weather, pre_as_of)
        a_post = annualise_property(now, ctx.weather, post_as_of)
        if not all(a_pre[f].usable and a_post[f].usable for f in FUELS):
            skipped["insufficient_meters"] += 1
            continue
        observed = {f: a_pre[f].annual_kwh - a_post[f].annual_kwh for f in FUELS}
        cases.append(RetrofitCase(row.property_id, row.measure_id, row.install_month, pre, observed, pre_as_of,
                                  {f: a_pre[f].annual_kwh for f in FUELS}))
    return cases, skipped


def predict_case(case: RetrofitCase, ctx: EngineContext, calibration: dict[str, float] | None = None) -> dict | None:
    """Engine-predicted standalone per-fuel saving for the case's measure (None if not modelled)."""
    c = dataclasses.replace(ctx, as_of=case.pre_as_of, calibration=calibration if calibration is not None else {},
                            energy_estimator=None, value_model=None)
    f = analyse_home(case.pre, c, scenario=Scenario(measures=[case.measure_id]))
    if f.package is None or f.package.measures != [case.measure_id]:
        return None
    return {"electricity": f.package.impact.electricity.saving_kwh, "gas": f.package.impact.gas.saving_kwh}
