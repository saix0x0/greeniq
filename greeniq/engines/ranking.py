"""Rank poorly performing homes by improvement potential (PS2 §04, FR-2).

Only homes classified Poor or Very poor are ranked. A home is ranked only if its improvement
potential is *available* (metered, non-zero baseline). Homes whose potential is unavailable
are listed separately with the reason, never slotted in with a guessed number. Ties are
broken by property ID, so the ranking is deterministic.
"""

from __future__ import annotations

from ..facts import ComputedFacts

RANKING_VERSION = "ranking/1.0"


def portfolio_row(f: ComputedFacts) -> dict:
    pk = f.package
    ip = pk.improvement_potential if pk else None
    top = f.score.issues[0] if f.score.issues else None
    return {
        "property_id": f.property_id,
        "customer_id": f.property_summary.get("customer_id"),
        "region": f.property_summary["region"],
        "property_type": f.property_summary["property_type"],
        "floor_area_m2": f.property_summary["floor_area_m2"],
        "score": f.score.score,
        "score_range": f.score.score_range,
        "band": f.score.band,
        "score_status": f.score.status,
        "is_poor": f.score.is_poor,
        "confidence": f.confidence.level,
        "baseline_basis": f.baseline_basis,
        "electricity_kwh": f.baseline["electricity"].annual_kwh,
        "gas_kwh": f.baseline["gas"].annual_kwh,
        "intensity_kwh_m2": f.intensity_kwh_m2.value,
        "potential_status": ip.status if ip else "unavailable",
        "potential_pct": ip.pct if ip else None,
        "potential_reason": (ip.reason if ip else "No feasible measures or no energy baseline."),
        "electricity_saving_kwh": pk.impact.electricity.saving_kwh if pk else None,
        "gas_saving_kwh": pk.impact.gas.saving_kwh if pk else None,
        "carbon_saving_kg": pk.impact.carbon.total_kg if pk else None,
        "score_after": pk.score_after if pk else None,
        "band_after": pk.band_after if pk else None,
        "top_issue": top.label if top else None,
        "n_measures": len(f.plan),
        "conflicts": [c.code for c in f.conflicts],
    }


def rank_poor_homes(rows: list[dict]) -> dict:
    poor = [r for r in rows if r["is_poor"]]
    ranked = sorted((r for r in poor if r["potential_status"] == "available"),
                    key=lambda r: (-r["potential_pct"], r["property_id"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    unavailable = sorted((r for r in poor if r["potential_status"] != "available"), key=lambda r: r["property_id"])
    return {"ranked": ranked, "unavailable": unavailable, "method": "100 × (E_baseline − E_after) / E_baseline, "
            "E = grid electricity imported + gas; Poor/Very poor homes only; ties by property ID",
            "version": RANKING_VERSION}
