"""Output contract: ComputedFacts, the immutable result of one analysis.

Every number the UI or the language layer can show lives here, next to its receipt.
A what-if produces a NEW ComputedFacts (it never mutates an old one).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contract import MeasureId, Receipt, Resolved
from .engines.carbon import CarbonResult
from .engines.retrofit import Excluded, Suitability
from .features.quality import Conflict, Question
from .score import ScoreResult


class FuelFigures(BaseModel):
    baseline_kwh: float | None
    after_kwh: float | None
    saving_kwh: float | None  # baseline − after; negative means consumption increases


class Impact(BaseModel):
    electricity: FuelFigures
    gas: FuelFigures
    net_saving_kwh: float
    carbon: CarbonResult


class BaselineEnergy(BaseModel):
    fuel: str
    annual_kwh: float | None
    basis: Literal["metered", "estimated", "zero", "not_applicable", "unavailable"]
    status: str
    heating_kwh: float | None = None
    baseload_kwh: float | None = None
    months_used: int = 0
    provider: str
    receipt: Receipt | None = None


class Flow(BaseModel):
    source: str
    target: str
    kwh: float


class ImprovementPotential(BaseModel):
    status: Literal["available", "unavailable"]
    pct: float | None = None
    e_baseline_kwh: float | None = None
    e_after_kwh: float | None = None
    reason: str | None = None
    indicative_pct: float | None = None  # from a model-estimated baseline; labelled, never ranked
    receipt: Receipt | None = None


class Recommendation(BaseModel):
    measure_id: str
    name: str
    stage: int
    stage_label: str
    order: int
    suitability: Suitability
    rationale: str
    evidence: list[str]
    depends_on: list[str]
    uncertainty: list[str]
    standalone: Impact
    in_package: Impact
    cost_low: int
    cost_high: int
    cost_basis: str
    grant_note: str | None = None
    real_evidence: str | None = None  # observed effect in real homes (DESNZ NEED), when available
    receipt: Receipt


class PackageResult(BaseModel):
    measures: list[str]
    order: Literal["recommended", "as_given"]
    impact: Impact
    sum_of_standalone_net_kwh: float
    interaction_kwh: float
    improvement_potential: ImprovementPotential
    score_after: int | None
    band_after: str | None
    score_range_after: tuple[int, int] | None = None
    sap_before: float | None
    sap_after: float | None
    epc_band_before: str | None
    epc_band_after: str | None
    cost_low: int
    cost_high: int
    components_after: dict[str, float | None] = Field(default_factory=dict)  # score contribution per component
    flows_after: list[Flow] = Field(default_factory=list)
    receipt: Receipt


class ValueResult(BaseModel):
    status: Literal["available", "unavailable"]
    current_value: int | None = None
    current_range: tuple[int, int] | None = None
    uplift_pct_range: tuple[float, float] | None = None
    uplift_gbp_range: tuple[int, int] | None = None
    value_after_range: tuple[int, int] | None = None
    band_before: str | None = None
    band_after: str | None = None
    caveat: str
    reason: str | None = None
    provider: str = "none"
    receipt: Receipt | None = None


class Scenario(BaseModel):
    """A what-if: which measures to model (None = the recommended package) and in what order."""

    name: str | None = Field(default=None, max_length=80)
    measures: list[MeasureId] | None = None
    order: Literal["recommended", "as_given"] = "recommended"


class ScenarioInfo(BaseModel):
    name: str | None
    requested: list[str] | None
    modelled: list[str]
    rejected: list[Excluded]
    order: str


class Confidence(BaseModel):
    level: Literal["high", "medium", "low"]
    value: float
    reasons: list[str]


class NBAReason(BaseModel):
    code: str
    text: str
    fact_ref: str  # path into this ComputedFacts, e.g. "plan[0].standalone.carbon.total_kg"


class NBAAction(BaseModel):
    kind: Literal["retrofit", "survey", "answer_question", "no_action"]
    ref: str | None = None  # measure id, question field or conflict code
    label: str


class NBAAlternative(BaseModel):
    action: NBAAction
    benefit: float | None = None
    why_not_first: str


class NextBestAction(BaseModel):
    """One action, selected from facts already computed (no new energy numbers are made here)."""

    action: NBAAction
    disposition: Literal["recommend", "refer_for_survey", "no_action"]
    headline: str
    reasons: list[NBAReason] = Field(min_length=3, max_length=3)
    objective: str
    benefit: float | None = None  # in the objective's unit
    benefit_unit: str | None = None
    confidence: Literal["high", "medium", "low"]
    alternatives: list[NBAAlternative] = Field(default_factory=list)
    blocked_by: str | None = None
    method_version: str


class ComputedFacts(BaseModel):
    facts_id: str
    property_id: str
    as_of: str
    versions: dict[str, str]
    property_summary: dict
    inputs: dict[str, Resolved]
    baseline: dict[str, BaselineEnergy]
    baseline_basis: Literal["metered", "estimated", "unavailable"]
    baseline_flows: list[Flow] = Field(default_factory=list)  # modelled end-use split of the baseline
    intensity_kwh_m2: Resolved
    baseline_emissions_kg: Resolved = Field(default_factory=lambda: Resolved(basis="missing"))
    sap: Resolved
    epc_band: str | None
    score: ScoreResult
    conflicts: list[Conflict]
    questions: list[Question]
    confidence: Confidence
    plan: list[Recommendation]
    excluded: list[Excluded]
    package: PackageResult | None
    value: ValueResult | None
    scenario: ScenarioInfo | None
    insights: list[str] = Field(default_factory=list)
    peer: "PeerComparison | None" = None  # this home vs similar REAL homes (DESNZ NEED)
    next_best_action: NextBestAction | None = None
    providers_used: dict[str, str]
    warnings: list[str]


from .real.benchmarks import PeerComparison  # noqa: E402

ComputedFacts.model_rebuild()
