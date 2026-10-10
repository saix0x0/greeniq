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
from .engines.ranking import portfolio_row, rank_poor_homes
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
               sort: str = "property_id", limit: int = 50, offset: int = 0) -> dict:
        rows = self._rows
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
        if sort == "potential":
            rows = sorted(rows, key=lambda r: (r["potential_pct"] is None, -(r["potential_pct"] or 0), r["property_id"]))
        elif sort == "score":
            rows = sorted(rows, key=lambda r: (r["score"] is None, r["score"] or 0, r["property_id"]))
        return {"total": len(rows), "offset": offset, "limit": limit, "items": rows[offset:offset + limit]}

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
                "coverage": {"metered_pct": round(100 * sum(r["baseline_basis"] == "metered" for r in rows) / len(rows), 1),
                             "epc_pct": round(100 * sum(bool(r.get("has_epc")) for r in rows) / len(rows), 1),
                             "complete_score_pct": round(100 * sum(r["score_basis"] == "complete" for r in rows) / len(rows), 1)},
            },
            "bands": BANDS,
            "band_distribution": {"all": dist_all(rows), "region": dist("region"), "property_type": dist("property_type"),
                                  "age_band": dist("age_band")},
            "opportunity_by_region": [{"region": k, "tco2e": round(v / 1000, 0), "share_pct": round(100 * v / total_c, 1)}
                                      for k, v in sorted(carbon_by_region.items(), key=lambda x: -x[1])],
            "triage": {d: sum(1 for r in rows if r["nba_disposition"] == d)
                       for d in ("recommend", "refer_for_survey", "no_action")},
            "next_actions": [{"disposition": d, "label": lab, "count": c} for (d, lab), c in nba_counts.most_common(10)],
            "ranking": {"method": ranking["method"], "version": ranking["version"],
                        "ranked": len(ranking["ranked"]), "unavailable": len(ranking["unavailable"]),
                        "top": ranking["ranked"][:10]},
            "versions": self.versions,
            "providers": self.providers,
        }


def dist_all(rows: list[dict]) -> dict:
    c = Counter(r["band"] or "Undetermined" for r in rows)
    return {b: c.get(b, 0) for b in BANDS + ["Undetermined"]}
