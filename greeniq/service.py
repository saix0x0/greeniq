"""Application service: the one place the API gets facts from.

Holds the dataset and engine context, runs ``analyse_home`` (the only source of numbers),
and caches results in SQLite keyed by an *engine key* (engine versions + model card +
data fingerprint). Change any engine, model or data file and the cache is rebuilt.
Routes never compute anything; they call this service.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
import threading
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from .context import load_context
from .data import DATA_DIR, ROOT, load_dataset
from .engines.catalogue import assumption
from .engines.ranking import RANKING_VERSION, TIERS, portfolio_row, priority_tier, rank_poor_homes
from .facts import ComputedFacts, Scenario
from .pipeline import analyse_home

VAR_DIR = ROOT / "var"
DB_PATH = VAR_DIR / "greeniq.sqlite"
BANDS = ["Very poor", "Poor", "Moderate", "Good", "Highly efficient"]


class UnknownProperty(KeyError):
    pass


def _fingerprint(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        if p.exists():
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:12]


def nba_row(f: ComputedFacts) -> dict:
    n = f.next_best_action
    return {"nba_disposition": n.disposition, "nba_kind": n.action.kind, "nba_ref": n.action.ref,
            "nba_label": n.action.label, "nba_headline": n.headline, "nba_confidence": n.confidence}


class GreenIQService:
    def __init__(self, db_path: Path = DB_PATH):
        self.ds = load_dataset()
        self.ctx = load_context()
        self._ids = set(self.ds.property_ids)
        sample = analyse_home(self.ds.property(self.ds.property_ids[0]), self.ctx)
        model_card = ROOT / "models" / "model_card.json"
        self.engine_key = hashlib.sha256(json.dumps(
            {"v": sample.versions, "providers": sample.providers_used, "cal": self.ctx.calibration,
             "rows": RANKING_VERSION,
             "models": _fingerprint([model_card]),
             "data": _fingerprint(sorted((DATA_DIR / "raw").glob("*.csv")))}, sort_keys=True).encode()).hexdigest()[:16]
        self.versions = sample.versions
        self.providers = sample.providers_used
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute("CREATE TABLE IF NOT EXISTS portfolio (engine_key TEXT, property_id TEXT, row TEXT, "
                         "PRIMARY KEY (engine_key, property_id))")
        self._rows = self._load_or_build_rows()

    # --- facts ---------------------------------------------------------------------------
    def facts(self, property_id: str) -> ComputedFacts:
        if property_id not in self._ids:
            raise UnknownProperty(property_id)
        return self._facts_cached(property_id)

    @lru_cache(maxsize=512)
    def _facts_cached(self, property_id: str) -> ComputedFacts:
        return analyse_home(self.ds.property(property_id), self.ctx)

    def scenario(self, property_id: str, scenario: Scenario | None, constraints: dict) -> ComputedFacts:
        """A what-if always reruns the engines; it never edits an earlier result."""
        if property_id not in self._ids:
            raise UnknownProperty(property_id)
        return analyse_home(self.ds.property(property_id), self.ctx, scenario=scenario, constraints=constraints)

    def lab(self, property_id: str, budget: float, objective: str) -> "LabResult":
        if property_id not in self._ids:
            raise UnknownProperty(property_id)
        return self._lab_cached(property_id, round(budget, -2), objective)

    @lru_cache(maxsize=128)
    def _lab_cached(self, property_id: str, budget: float, objective: str):
        from .lab import decision_lab

        return decision_lab(self.ds.property(property_id), self.ctx, budget, {"objective": objective})

    # --- portfolio ------------------------------------------------------------------------
    def _load_or_build_rows(self) -> list[dict]:
        cur = self._db.execute("SELECT row FROM portfolio WHERE engine_key = ?", (self.engine_key,))
        rows = [json.loads(r[0]) for r in cur.fetchall()]
        if len(rows) == len(self._ids):
            return sorted(rows, key=lambda r: r["property_id"])
        rows = []
        for pid in self.ds.property_ids:
            f = analyse_home(self.ds.property(pid), self.ctx)
            row = {**portfolio_row(f), **nba_row(f), "age_band": f.property_summary["age_band"],
                   "score_basis": f.score.status, "has_epc": f.sap.basis == "observed"}
            row["tier"] = priority_tier(row)
            rows.append(row)
        with self._lock, self._db:
            self._db.execute("DELETE FROM portfolio WHERE engine_key != ?", (self.engine_key,))
            self._db.executemany("INSERT OR REPLACE INTO portfolio VALUES (?, ?, ?)",
                                 [(self.engine_key, r["property_id"], json.dumps(r)) for r in rows])
        return rows

    def rows(self) -> list[dict]:
        return self._rows

    def search(self, q: str | None = None, band: str | None = None, region: str | None = None,
               property_type: str | None = None, disposition: str | None = None, poor_only: bool = False,
               sort: str = "property_id", limit: int = 50, offset: int = 0, ids: str | None = None,
               group_by: str | None = None, group: str | None = None, tier: str | None = None) -> dict:
        rows = self._rows
        if ids:
            want = [i.strip().upper() for i in ids.split(",") if i.strip()]
            by = {r["property_id"]: r for r in rows}
            rows = [by[i] for i in want if i in by]
        if group_by in GROUP_KEYS and group is not None:
            rows = [r for r in rows if _group_value(r, group_by) == group]
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in r["property_id"].lower() or ql in (r.get("customer_id") or "").lower()
                    or ql in r["region"] or ql in r["property_type"]]
        if band:
            rows = [r for r in rows if r["band"] == band]
        if region:
            rows = [r for r in rows if r["region"] == region]
        if property_type:
            rows = [r for r in rows if r["property_type"] == property_type]
        if disposition:
            rows = [r for r in rows if r["nba_disposition"] == disposition]
        if poor_only:
            rows = [r for r in rows if r["is_poor"]]
        if tier:
            rows = [r for r in rows if r.get("tier") == tier]
        if sort == "priority":
            order = {t: i for i, t in enumerate(TIERS)}
            rows = sorted(rows, key=lambda r: (order.get(r.get("tier"), 9), r["potential_pct"] is None,
                                               -(r["potential_pct"] or 0), r["property_id"]))
        elif sort == "potential":
            rows = sorted(rows, key=lambda r: (r["potential_pct"] is None, -(r["potential_pct"] or 0), r["property_id"]))
        elif sort == "score":
            rows = sorted(rows, key=lambda r: (r["score"] is None, r["score"] or 0, r["property_id"]))
        elif sort == "carbon":
            rows = sorted(rows, key=lambda r: (r["carbon_saving_kg"] is None, -(r["carbon_saving_kg"] or 0), r["property_id"]))
        elif sort == "value":
            rows = sorted(rows, key=lambda r: (r["value_uplift_pct_high"] is None, -(r["value_uplift_pct_high"] or 0),
                                               r["property_id"]))
        return {"total": len(rows), "offset": offset, "limit": limit, "items": rows[offset:offset + limit]}

    def standing(self, property_id: str) -> dict:
        """Where this home's score sits among homes scored by the SAME engine version in this portfolio
        (mid-rank percentile: share scoring lower + half of ties). Relative rank, not a probability."""
        me = next((r for r in self._rows if r["property_id"] == property_id), None)
        if me is None:
            raise UnknownProperty(property_id)
        if me["score"] is None:
            return {"available": False, "reason": "This home's score is a range (an input is missing), so it is not ranked."}

        def pct(pool):
            xs = [r["score"] for r in pool if r["score"] is not None]
            lower = sum(1 for x in xs if x < me["score"])
            ties = sum(1 for x in xs if x == me["score"])
            return {"percentile": round(100 * (lower + 0.5 * ties) / len(xs), 0), "homes": len(xs),
                    "median_score": statistics.median(xs)}
        same = [r for r in self._rows if r["property_type"] == me["property_type"] and r["age_band"] == me["age_band"]]
        out = {"available": True, "score": me["score"], "all": pct(self._rows),
               "similar": {**pct(same), "definition": f"{me['property_type'].replace('_', ' ')} homes, {me['age_band'].replace('_', ' ')}"},
               "population": "homes in this (simulated) portfolio, scored with the same engine version",
               "method": "mid-rank percentile: % scoring lower + half of equal scores"}
        if out["similar"]["homes"] < assumption("benchmark.min_similar_homes"):
            out["similar"] = {"available": False, "reason": f"only {out['similar']['homes']} similar homes; too few to rank"}
        return out

    def groups(self, by: str) -> dict:
        if by not in GROUP_KEYS:
            raise ValueError(f"group by one of: {', '.join(GROUP_KEYS)}")
        return group_summary(self._rows, by)

    def portfolio(self) -> dict:
        rows = self._rows
        scored = [r for r in rows if r["score"] is not None]
        poor_known = [r for r in rows if r["is_poor"] is not None]
        avail = [r for r in rows if r["potential_status"] == "available"]
        after = [r for r in rows if r["score"] is not None and r["score_after"] is not None]

        def dist(key):
            out = defaultdict(lambda: dict.fromkeys(BANDS + ["Undetermined"], 0))
            for r in rows:
                out[r[key] or "unknown"][r["band"] or "Undetermined"] += 1
            return dict(sorted(out.items()))

        carbon_by_region = defaultdict(float)
        for r in avail:
            carbon_by_region[r["region"]] += max(r["carbon_saving_kg"] or 0, 0)
        total_c = sum(carbon_by_region.values()) or 1.0
        nba_counts = Counter((r["nba_disposition"], r["nba_label"]) for r in rows)
        ranking = rank_poor_homes([dict(r) for r in rows])
        return {
            "engine_key": self.engine_key,
            "n_homes": len(rows),
            "data_label": "synthetic dataset (simulated world, see data/DATA_CARD.md)",
            "kpis": {
                "avg_score": {"value": round(statistics.mean(r["score"] for r in scored), 1), "n": len(scored),
                              "excluded": len(rows) - len(scored),
                              "note": "mean of point scores; homes with only a score range are excluded"},
                "avg_score_after": {"value": round(statistics.mean(r["score_after"] for r in after), 1),
                                    "before_same_homes": round(statistics.mean(r["score"] for r in after), 1),
                                    "n": len(after), "note": "if every home's recommended package were installed (estimate)"},
                "opportunity": {
                    "gwh": round(sum((r["electricity_saving_kwh"] or 0) + (r["gas_saving_kwh"] or 0) for r in avail) / 1e6, 2),
                    "electricity_gwh": round(sum(r["electricity_saving_kwh"] or 0 for r in avail) / 1e6, 2),
                    "gas_gwh": round(sum(r["gas_saving_kwh"] or 0 for r in avail) / 1e6, 2),
                    "tco2e": round(sum(r["carbon_saving_kg"] or 0 for r in avail) / 1000, 0),
                    "n": len(avail), "basis": "estimated",
                    "note": "net purchased-energy saving of each home's recommended package; metered homes only; "
                            "negative electricity means heat pumps add electricity while cutting gas"},
                "poor_pct": {"value": round(100 * sum(1 for r in poor_known if r["is_poor"]) / len(poor_known), 1),
                             "count": sum(1 for r in poor_known if r["is_poor"]), "n": len(poor_known)},
                "value": {
                    "homes": sum(1 for r in rows if r["value_uplift_pct_high"] is not None),
                    "band_improves": sum(1 for r in rows if (r["value_uplift_pct_high"] or 0) > 0),
                    "median_uplift_pct": [_median([r["value_uplift_pct_low"] for r in rows if r["value_uplift_pct_high"]]),
                                          _median([r["value_uplift_pct_high"] for r in rows if r["value_uplift_pct_high"]])],
                    "note": "indicative range from historical EPC-band price relationships in the (synthetic) sales data; "
                            "not a valuation and not causal; median over homes whose EPC band improves"},
                "coverage": {"metered_pct": round(100 * sum(r["baseline_basis"] == "metered" for r in rows) / len(rows), 1),
                             "epc_pct": round(100 * sum(bool(r.get("has_epc")) for r in rows) / len(rows), 1),
                             "complete_score_pct": round(100 * sum(r["score_basis"] == "complete" for r in rows) / len(rows), 1)},
            },
            "bands": BANDS,
            "band_distribution": {"all": dist_all(rows), "region": dist("region"), "property_type": dist("property_type"),
                                  "age_band": dist("age_band")},
            "opportunity_by_region": [{"region": k, "tco2e": round(v / 1000, 0), "share_pct": round(100 * v / total_c, 1)}
                                      for k, v in sorted(carbon_by_region.items(), key=lambda x: -x[1])],
            "group_keys": GROUP_KEYS,
            "tiers": [{"key": k, "label": lab, "meaning": m, "homes": sum(1 for r in rows if r.get("tier") == k)}
                      for k, (lab, m) in TIERS.items()],
            "triage": {d: sum(1 for r in rows if r["nba_disposition"] == d)
                       for d in ("recommend", "refer_for_survey", "no_action")},
            "next_actions": [{"disposition": d, "label": lab, "count": c} for (d, lab), c in nba_counts.most_common(10)],
            "ranking": {"method": ranking["method"], "version": ranking["version"],
                        "ranked": len(ranking["ranked"]), "unavailable": len(ranking["unavailable"]),
                        "top": ranking["ranked"][:10]},
            "versions": self.versions,
            "providers": self.providers,
        }


GROUP_KEYS = {"region": "Region", "property_type": "Property type", "age_band": "Age", "heating_system": "Heating",
              "epc_band": "EPC band", "band": "Score band", "baseline_basis": "Energy data"}


def _group_value(r: dict, key: str) -> str:
    v = r.get(key)
    return "Not certain" if key == "band" and v is None else (v or "unknown")


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def group_summary(rows: list[dict], key: str) -> dict:
    """Every PS2 output per group (region, type, age, heating, EPC band, score band, data quality).
    Pure aggregation of each home's computed facts; nothing is re-estimated."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[_group_value(r, key)].append(r)
    out = []
    for g, rs in groups.items():
        scored = [r["score"] for r in rs if r["score"] is not None]
        known = [r for r in rs if r["is_poor"] is not None]
        av = [r for r in rs if r["potential_status"] == "available"]
        val = [r for r in rs if r["value_uplift_pct_high"] is not None]
        out.append({
            "group": g, "homes": len(rs),
            "avg_score": round(statistics.mean(scored), 1) if scored else None,
            "avg_score_after": round(statistics.mean(r["score_after"] for r in rs if r["score_after"] is not None), 1)
            if any(r["score_after"] is not None for r in rs) else None,
            "poor_pct": round(100 * sum(r["is_poor"] for r in known) / len(known), 1) if known else None,
            "poor_homes": sum(1 for r in known if r["is_poor"]),
            "median_potential_pct": _median([r["potential_pct"] for r in av]),
            "electricity_saving_mwh": round(sum(r["electricity_saving_kwh"] or 0 for r in av) / 1000, 1),
            "gas_saving_mwh": round(sum(r["gas_saving_kwh"] or 0 for r in av) / 1000, 1),
            "carbon_saving_t": round(sum(r["carbon_saving_kg"] or 0 for r in av) / 1000, 1),
            "carbon_saving_t_per_home": round(sum(r["carbon_saving_kg"] or 0 for r in av) / 1000 / len(av), 2) if av else None,
            "median_uplift_pct": [_median([r["value_uplift_pct_low"] for r in val]),
                                  _median([r["value_uplift_pct_high"] for r in val])] if val else None,
            "homes_with_savings": len(av), "homes_with_value": len(val),
            "metered_pct": round(100 * sum(r["baseline_basis"] == "metered" for r in rs) / len(rs), 0),
        })
    order = {"band": BANDS + ["Not certain"], "epc_band": list("ABCDEFG")}.get(key)
    out.sort(key=lambda x: (order.index(x["group"]) if order and x["group"] in order else 99, x["group"]))
    return {"by": key, "label": GROUP_KEYS[key], "groups": out,
            "note": "Savings, carbon and potential sum or take medians over homes whose improvement potential is available; "
                    "value over homes with a value estimate. All per-home figures are engine estimates."}


def dist_all(rows: list[dict]) -> dict:
    c = Counter(r["band"] or "Undetermined" for r in rows)
    return {b: c.get(b, 0) for b in BANDS + ["Undetermined"]}
