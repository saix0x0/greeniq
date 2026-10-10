"""Build the EngineContext: weather, plus any trained providers found in models/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from .data import DATA_DIR, Weather
from .pipeline import EngineContext


@lru_cache(maxsize=1)
def load_weather(root: Path = DATA_DIR) -> Weather:
    return Weather(pd.read_csv(root / "raw" / "weather.csv"), pd.read_csv(root / "raw" / "weather_normals.csv"))


def load_context(with_models: bool = True) -> EngineContext:
    ctx = EngineContext(weather=load_weather())
    if with_models:
        try:
            from .ml.registry import attach_models
            attach_models(ctx)
        except (FileNotFoundError, ImportError):
            pass  # no trained models: the transparent baselines still give a complete result
    return ctx
