"""Real-data benchmarks used inside the product: "homes like yours" and real retrofit evidence.

Built from the NEED **train** split by ``greeniq real-evidence`` into
``greeniq/config/real_benchmarks.json`` (small, committed), then read at runtime.

Peer comparison
    A home is matched to real NEED homes of the same property type, floor-area band and age band.
    Its annual gas and electricity are placed on the real distribution (percentile). Use far below
    similar homes is flagged as a *possible* sign of under-heating or low occupancy, never a
    diagnosis: it means real savings may be smaller than modelled. Use far above is flagged too.

Mapping from the app's fields to NEED's coarser bands (documented approximation):
    terraced → Mid terrace; age pre_1919 and 1919_1944 → "before 1930"; 1945_1964 and 1965_1980 →
    "1930-1972"; 1981_2002 → "1973-1999"; post_2002 → "2000 or later".
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import pandas as pd
from pydantic import BaseModel

from ..config import CONFIG_DIR

BENCH_FILE = CONFIG_DIR / "real_benchmarks.json"
TYPE_MAP = {"detached": "Detached", "semi_detached": "Semi detached", "terraced": "Mid terrace",
            "bungalow": "Bungalow", "flat": "Flat"}
AGE_MAP = {"pre_1919": 1, "1919_1944": 1, "1945_1964": 2, "1965_1980": 2, "1981_2002": 3, "post_2002": 4}
QS = list(range(5, 100, 5))
LOW, HIGH = 0.4, 2.5  # flags: below 40% or above 250% of the peer median
MEASURE_KEY = {"loft_insulation": "loft", "cavity_wall_insulation": "cavity", "solar_pv": "solar_pv"}


def area_code(m2: float) -> int:
    return 1 if m2 <= 50 else 2 if m2 <= 100 else 3 if m2 <= 150 else 4 if m2 <= 200 else 5


def build(d: pd.DataFrame, evidence: dict) -> dict:
    tr = d[d["split"] == "train"]
    peers = {}
    for fuel, col, rows in (("gas", "gas_2024", tr[tr["gas_main_heating"]]), ("electricity", "elec_2024", tr)):
        rows = rows[rows[col].notna()]
        cells = {}
        for keys, name in ((["property_type", "area_code", "age_code"], "fine"), (["property_type", "area_code"], "mid"),
                           (["area_code"], "coarse")):
            for k, g in rows.groupby(keys):
                k = k if isinstance(k, tuple) else (k,)
                if len(g) >= 30:
                    cells[f"{name}|" + "|".join(str(int(x)) if not isinstance(x, str) else x for x in k)] = {
                        "n": int(len(g)), "q": [float(v) for v in np.percentile(g[col], QS)],
                        "median": float(g[col].median())}
        peers[fuel] = cells
    ev = {}
    for m, r in evidence.items():
        e = r.get("estimate", {})
        if e.get("n"):
            ev[m] = {"fuel": r["fuel"], "saving_pct": e["saving_pct"], "ci90_pct": e["ci90_pct"], "n": e["n"],
                     "saving_kwh": e["saving_kwh"], "realisation_vs_engine": r.get("realisation_vs_engine")}
    out = {"source": "DESNZ NEED anonymised 2026, 50,000-row sample (train split), Open Government Licence v3.0",
           "peer_year": 2024, "quantiles": QS, "flags": {"low": LOW, "high": HIGH}, "peers": peers, "evidence": ev}
    BENCH_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    load.cache_clear()
    return out


@lru_cache(maxsize=1)
def load() -> dict | None:
    return json.loads(BENCH_FILE.read_text(encoding="utf-8")) if BENCH_FILE.exists() else None


class PeerFuel(BaseModel):
    fuel: str
    actual_kwh: float
    peer_median_kwh: float
    percentile: int  # 0-100: share of similar real homes using less
    ratio_to_median: float
    n_peers: int
    match: str  # which NEED cell was used
    flag: str | None = None


class PeerComparison(BaseModel):
    source: str
    peer_group: str
    fuels: list[PeerFuel]
    signals: list[str]


def _cell(peers: dict, ptype: str, area: int, age: int | None) -> tuple[str, dict] | None:
    keys = ([f"fine|{ptype}|{area}|{age}"] if age else []) + [f"mid|{ptype}|{area}", f"coarse|{area}"]
    for k in keys:
        if k in peers:
            return k, peers[k]
    return None


def compare(property_type: str, floor_area_m2: float | None, age_band: str | None,
            baseline: dict[str, tuple[float | None, str]]) -> PeerComparison | None:
    """baseline: fuel -> (annual kWh, basis). Only metered, non-zero fuels are compared."""
    b = load()
    if b is None or not floor_area_m2 or property_type not in TYPE_MAP:
        return None
    ptype, area, age = TYPE_MAP[property_type], area_code(floor_area_m2), AGE_MAP.get(age_band or "")
    fuels, signals = [], []
    for fuel in ("gas", "electricity"):
        kwh, basis = baseline.get(fuel, (None, "missing"))
        if basis != "metered" or not kwh:
            continue
        hit = _cell(b["peers"][fuel], ptype, area, age)
        if hit is None:
            continue
        key, c = hit
        pct = int(np.interp(kwh, c["q"], b["quantiles"], left=0, right=100))
        ratio = kwh / c["median"]
        flag = None
        if ratio < b["flags"]["low"]:
            flag = "much_lower"
            signals.append(f"{fuel.capitalize()} use is {ratio:.0%} of similar real homes. That can mean under-heating or "
                           "low occupancy (not proven), so real savings may be smaller than modelled.")
        elif ratio > b["flags"]["high"]:
            flag = "much_higher"
            signals.append(f"{fuel.capitalize()} use is {ratio:.1f}× similar real homes; worth checking the "
                           "property record and how the heating is used.")
        fuels.append(PeerFuel(fuel=fuel, actual_kwh=round(kwh), peer_median_kwh=round(c["median"]), percentile=pct,
                              ratio_to_median=round(ratio, 2), n_peers=c["n"], match=key.split("|")[0], flag=flag))
    if not fuels:
        return None
    group = f"{ptype.lower()}, {area_band_label(area)}" + (f", built {AGE_LABEL[age]}" if age else "")
    return PeerComparison(source=b["source"], peer_group=group, fuels=fuels, signals=signals)


AGE_LABEL = {1: "before 1930", 2: "1930-1972", 3: "1973-1999", 4: "2000 or later"}


def area_band_label(code: int) -> str:
    return {1: "50 m² or less", 2: "51-100 m²", 3: "101-150 m²", 4: "151-200 m²", 5: "over 200 m²"}[code]


def evidence_for(measure_id: str) -> str | None:
    b = load()
    k = MEASURE_KEY.get(measure_id)
    if b is None or k not in b["evidence"]:
        return None
    e = b["evidence"][k]
    what = "gas" if e["fuel"] == "gas" else "grid electricity"
    return (f"Real UK homes that installed this used {e['saving_pct']:.1f}% less {what} the year after "
            f"(90% interval {e['ci90_pct'][0]:.1f}% to {e['ci90_pct'][1]:.1f}%, {e['n']:,} homes, vs similar homes "
            "that did not; DESNZ NEED).")
