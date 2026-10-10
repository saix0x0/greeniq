"""Load the retrofit catalogue and emission factors (configuration as data)."""

from __future__ import annotations

import json
from functools import lru_cache

from ..config import CONFIG_DIR


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads((CONFIG_DIR / "retrofit_catalogue.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def emission_factors() -> dict:
    return json.loads((CONFIG_DIR / "emission_factors.json").read_text(encoding="utf-8"))


def measure(measure_id: str) -> dict:
    return catalogue()["measures"][measure_id]


def measure_name(measure_id: str) -> str:
    return measure(measure_id)["name"]


def stage_label(stage: int) -> str:
    return catalogue()["stages"][str(stage)]
