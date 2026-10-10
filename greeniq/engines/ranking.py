"""Rank poorly performing homes by improvement potential (PS2 §3).

Only homes classified Poor or Very poor are ranked. A home is ranked if its improvement potential
is available (non-zero baseline; a model-estimated baseline is ranked and labelled "estimated").
Homes whose potential is unavailable (zero or no baseline, or no feasible measure) are listed
separately with the reason, never slotted in with a guessed number. Ties are
broken by property ID, so the ranking is deterministic.
"""

from __future__ import annotations

from ..facts import ComputedFacts

RANKING_VERSION = "ranking/1.2"  # 1.2: priority tier (worklist), from the engine's own outputs


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
        "potential_basis": ip.basis if ip else None,
        "potential_reason": (ip.reason if ip else "No feasible measures or no energy baseline."),
        "electricity_saving_kwh": pk.impact.electricity.saving_kwh if pk else None,
        "gas_saving_kwh": pk.impact.gas.saving_kwh if pk else None,
        "carbon_saving_kg": pk.impact.carbon.total_kg if pk else None,
        "score_after": pk.score_after if pk else None,
        "band_after": pk.band_after if pk else None,
        "top_issue": top.label if top else None,
        "issues": [i.label for i in f.score.issues[:3]],
        "heating_system": f.property_summary.get("heating_system_recorded"),
        "epc_band": f.package.epc_band_before if pk and pk.epc_band_before else
        (f.property_summary.get("epc_band_recorded")),
        "epc_band_after": pk.epc_band_after if pk else None,
        "package_measures": pk.measures if pk else [],
        "cost_low": pk.cost_low if pk else None,
        "cost_high": pk.cost_high if pk else None,
        "value_status": f.value.status if f.value else "unavailable",
        "value_current": f.value.current_value if f.value else None,
        "value_uplift_pct_low": f.value.uplift_pct_range[0] if f.value and f.value.uplift_pct_range else None,
        "value_uplift_pct_high": f.value.uplift_pct_range[1] if f.value and f.value.uplift_pct_range else None,
        "value_after_low": f.value.value_after_range[0] if f.value and f.value.value_after_range else None,
        "value_after_high": f.value.value_after_range[1] if f.value and f.value.value_after_range else None,
        "n_measures": len(f.plan),
        "conflicts": [c.code for c in f.conflicts],
    }


# Worklist tiers, in the way an insurer's referral queue works: every home lands in exactly one tier, decided
# only by outputs the engines already computed (no new thresholds). Within a tier, homes are ordered by
# improvement potential (PS2 §3), then by ID.
TIERS = {
    "act_now": ("Act now", "Rated Poor or Very poor, with a feasible next step ready to recommend."),
    "check_first": ("Check first", "A fact that changes the advice is missing or conflicting: survey or ask before acting."),
    "worth_doing": ("Worth doing", "Not rated poor, but a feasible upgrade is still worth recommending."),
    "no_action": ("No action now", "No remaining measure clears the minimum benefit, or the home looks unoccupied."),
}


def priority_tier(row: dict) -> str:
    d = row.get("nba_disposition")
    if d == "refer_for_survey":
        return "check_first"
    if d == "recommend":
        return "act_now" if row.get("is_poor") else "worth_doing"
    return "no_action"


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
