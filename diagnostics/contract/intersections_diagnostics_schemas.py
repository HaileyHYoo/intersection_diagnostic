"""Intersections Diagnostics layer (V1 screening and diagnostic methodology, 29 Oct 2026).

Flow covered by this module (Dash callbacks are the backend):

    1. callback -> service       ScreeningRequest, DiagnosisRequest
    2. service -> core logic     ScreeningInput, DiagnosisInput
    3. core logic -> service     ScreeningResult, DiagnosisResult
    4. shared run store          ScreeningRun (Redis/Mongo, shared across users)
    5. service -> dcc.Store      ScreeningPanelData, DisplaySettings

Level 1 (network screening) runs Q2 -> Q1 + Q3 for every site in a region for one
completed 30-minute period. Level 2 (on-demand diagnosis) runs Q4 + Q5 for a single
Red site the operator clicks, reusing the saved Level 1 evidence of the same run.

The diagnostic report is rendered by the callback straight from DiagnosisResult and the
site's SiteScreeningResult; there is no separate report view model.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, ValidationInfo, model_validator

TOMTOM_UNAVAILABLE_MESSAGE = "TomTom confirmation unavailable for this intersection or analysis period."

def _is_trusted(info: ValidationInfo) -> bool:
    """Records reloaded from our own store were validated on write; skip the rule checks."""
    return bool(info.context and info.context.get("trusted"))

# Enums

class AssessmentStatus(str, Enum):
    """Status of Q1, Q3 and each Q3 component."""
    NORMAL = "normal"
    ABNORMAL = "abnormal"
    INSUFFICIENT_DATA = "insufficient_data"

class GateStatus(str, Enum):
    """Q2 detector gate outcome. INSUFFICIENT_DATA means missing records, never a measured zero."""
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"

class DeviationDirection(str, Enum):
    HIGH = "high"
    LOW = "low"

class PhaseServiceStatus(str, Enum):
    """Q3C approach-level classification against the 10th-90th percentile envelope."""
    NORMAL = "normal"
    ABNORMAL_LOW = "abnormal_low"
    ABNORMAL_HIGH = "abnormal_high"
    INSUFFICIENT_DATA = "insufficient_data"

class StabilityPolarity(str, Enum):
    """Which side of the Platform's Cycle Stability metric means poorer stability."""
    LOWER_IS_POORER = "lower_is_poorer"
    HIGHER_IS_POORER = "higher_is_poorer"

class SiteCategory(str, Enum):
    """Final per-site classification (Section 10 decision matrix)."""
    NORMAL = "normal"
    AMBER_TRAFFIC = "amber_traffic"        # Q1 abnormal, Q3 normal
    AMBER_SIGNAL = "amber_signal"          # Q1 normal, Q3 abnormal
    RED = "red"                            # Q1 and Q3 abnormal: Needs Attention
    GREY = "grey"                          # insufficient data
    DETECTOR_HEALTH_ISSUE = "detector_health_issue"  # observed Q2 failure

class LegendCategory(str, Enum):
    """Legend groups shown in the panel; both Amber kinds collapse into Monitor."""
    NEEDS_ATTENTION = "needs_attention"
    MONITOR = "monitor"
    NORMAL = "normal"
    INSUFFICIENT_DATA = "insufficient_data"
    DETECTOR_HEALTH_ISSUE = "detector_health_issue"

class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class ScatsAgreement(str, Enum):
    """Q5 deterministic comparison of TomTom impact against the SCATS-flagged approaches."""
    AGREE = "agree"
    DISAGREE = "disagree"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"

SITE_CATEGORY_TO_LEGEND: dict[SiteCategory, LegendCategory] = {
    SiteCategory.RED: LegendCategory.NEEDS_ATTENTION,
    SiteCategory.AMBER_TRAFFIC: LegendCategory.MONITOR,
    SiteCategory.AMBER_SIGNAL: LegendCategory.MONITOR,
    SiteCategory.NORMAL: LegendCategory.NORMAL,
    SiteCategory.GREY: LegendCategory.INSUFFICIENT_DATA,
    SiteCategory.DETECTOR_HEALTH_ISSUE: LegendCategory.DETECTOR_HEALTH_ISSUE,
}

# Shared models

class AnalysisPeriod(BaseModel):
    """The completed 30-minute screening period plus the 60-minute Q2 window ending with it."""
    start: datetime = Field(description="Start of the 30-minute period, timezone-aware", examples=["2026-10-30T08:00:00+11:00"])
    end: datetime = Field(description="End of the 30-minute period, timezone-aware", examples=["2026-10-30T08:30:00+11:00"])
    detector_window_start: datetime = Field(
        description="Start of the Q2 60-minute detector window; it ends at `end`",
        examples=["2026-10-30T07:30:00+11:00"],
    )
    weekday: int = Field(ge=0, le=6, description="ISO weekday - 1 (Monday = 0), used for baseline lookup")
    slot_index: int = Field(ge=0, le=47, description="30-minute slot of the day (00:00 = 0)", examples=[16])

    @model_validator(mode="after")
    def _check_windows(self):
        if (self.end - self.start).total_seconds() != 30 * 60:
            raise ValueError("analysis period must be exactly 30 minutes")
        if (self.end - self.detector_window_start).total_seconds() != 60 * 60:
            raise ValueError("detector window must be the 60 minutes ending at the period end")
        return self

class HistoricalComparison(BaseModel):
    """A current value against its same-weekday, same-slot baseline over the previous 8 weeks."""
    current: float | None = Field(description="Value for the analysis period; None when missing")
    reference: float | None = Field(default=None, description="Usual/reference value (baseline median)")
    p10: float | None = Field(default=None, description="Historical 10th percentile")
    p90: float | None = Field(default=None, description="Historical 90th percentile")
    n_history_obs: int = Field(ge=0, description="Valid historical observations after calendar/holiday exclusions")
    pct_diff: float | None = Field(default=None, description="100 x (current - reference) / reference")

class SiteRef(BaseModel):
    site_no: str = Field(description="SCATS site number", examples=["4521"])
    name: str = Field(default="", examples=["Lygon St & Grattan St"])
    coordinates: tuple[float, float] | None = Field(default=None, description="(lon, lat)")

class ApproachRef(BaseModel):
    approach_id: str = Field(description="Platform approach/link identifier", examples=["4521_N"])
    approach_name: str = Field(default="", description="Display name", examples=["Northbound"])

class TemplateRef(BaseModel):
    """Intersection Brain template registry entry used for a Q4/Q5 invocation."""
    template_id: str = Field(examples=["ID_Q4_SCATS_INTERPRETATION"])
    version: str = Field(examples=["1.0.0"])

# Request models (callback -> service)

class ScreeningRequest(BaseModel):
    """Built by the callback on layer activation and on each dcc.Interval tick.

    If the run it resolves to is the one already in the panel store, the callback
    returns no_update instead of re-rendering.
    """
    region: str = Field(description="Region tag", examples=["AU-VIC-Melbourne"])
    period_end: datetime | None = Field(
        default=None,
        description="End of the period to screen; None means the latest completed 30-minute period",
    )

class DiagnosisRequest(BaseModel):
    """Built by the callback when the operator clicks a Red site.

    Carries identifiers only. The service loads the period and the Q1/Q3 evidence from
    the saved ScreeningRun; never rebuild them from the client dcc.Store, which is not
    the audited evidence of the run. The service also rejects sites that are not Red
    in that run.
    """
    region: str = Field(examples=["AU-VIC-Melbourne"])
    screening_run_id: str = Field(description="Run whose saved Q1/Q3 evidence Q4/Q5 must use")
    site_no: str = Field(examples=["4521"])

class DisplaySettings(BaseModel):
    """Panel 'Apply' payload, kept in a dcc.Store(storage_type="local"); never sent to core logic."""
    scale_by_value: bool = False
    marker_radius_m: int = Field(default=150, ge=50, le=500)
    thresholds_veh_h: list[float] = Field(
        default_factory=lambda: [500, 1000, 2000, 5000],
        description="Ascending volume thresholds for binning marker radius",
    )
    hidden_legends: list[LegendCategory] = Field(default_factory=list)

# Service inputs (backend -> core logic)

class ScreeningConfig(BaseModel):
    """V1 thresholds; all configurable, defaults are the agreed V1 values."""
    detector_min_count_60min: int = Field(default=10, description="Q2: minimum count per detector over 60 min")
    baseline_weeks: int = Field(default=8)
    min_history_obs: int = Field(default=5)
    percentile_low: float = Field(default=10)
    percentile_high: float = Field(default=90)
    min_relative_diff_pct: float = Field(default=10, description="Q1 and Q3A materiality threshold")
    q3_min_abnormal: int = Field(default=2, description="Q3 is abnormal when at least this many components are")
    q3_min_assessed: int = Field(default=2, description="Q3 is insufficient when fewer components are assessable")

class ScreeningSite(SiteRef):
    detector_ids: list[str] = Field(default_factory=list, description="Detectors associated with the site, for Q2")
    approaches: list[ApproachRef] = Field(default_factory=list, description="Approaches for Q1 and Q3C")

class ScreeningInput(BaseModel):
    """Everything the Level 1 service function needs for one run."""
    run_id: str = Field(examples=["scr_AU-VIC-Melbourne_20261030T0830_b2026w44"])
    region: str
    period: AnalysisPeriod
    baseline_version: str = Field(description="Weekly baseline snapshot to compare against", examples=["2026-W44"])
    config: ScreeningConfig = Field(default_factory=ScreeningConfig)
    sites: list[ScreeningSite] = Field(description="Signalised sites in the region to screen")

class DiagnosisInput(BaseModel):
    """Everything the Level 2 service function needs for one selected Red site."""
    diagnosis_id: str = Field(examples=["diag_scr_..._4521"])
    screening_run_id: str
    region: str
    period: AnalysisPeriod = Field(description="Same period as the screening run; TomTom must use it too")
    site: ScreeningSite
    evidence: "SiteScreeningResult" = Field(description="Saved Q1/Q3 evidence for this site, unchanged")
    q4_template: TemplateRef
    q5_template: TemplateRef

    @staticmethod
    def affected_ids(evidence: "SiteScreeningResult") -> list[str]:
        """Q1 and Q3C affected approaches, Q1 first, without duplicates."""
        ids = list(evidence.q1.abnormal_approach_ids) if evidence.q1 else []
        if evidence.q3 and evidence.q3.phase_service:
            ids += [a for a in evidence.q3.phase_service.affected_approach_ids if a not in ids]
        return ids

    @property
    def affected_approach_ids(self) -> list[str]:
        """Passed to Q5 for the SCATS comparison."""
        return self.affected_ids(self.evidence)

# Service outputs (core logic -> backend) - Level 1 screening

class DetectorCount(BaseModel):
    detector_id: str = Field(examples=["4521_D07"])
    count_60min: int | None = Field(description="Vehicles over the 60-minute window; None when records are missing")
    passed: bool | None = Field(description="None when the count could not be evaluated")

class Q2DetectorGate(BaseModel):
    status: GateStatus
    detectors: list[DetectorCount] = Field(default_factory=list)

    @property
    def failed_detectors(self) -> list[DetectorCount]:
        return [d for d in self.detectors if d.passed is False]

class Q1Approach(ApproachRef):
    volume: HistoricalComparison = Field(description="30-minute volume (veh), sum of the latest two 15-min intervals")
    is_abnormal: bool
    direction: DeviationDirection | None = Field(default=None, description="Set when abnormal")
    status: AssessmentStatus

class Q1TrafficAbnormality(BaseModel):
    status: AssessmentStatus
    approaches: list[Q1Approach] = Field(default_factory=list, description="All evaluated approaches, flagged or not")

    @property
    def abnormal_approach_ids(self) -> list[str]:
        return [a.approach_id for a in self.approaches if a.is_abnormal]

class Q3CycleLength(BaseModel):
    status: AssessmentStatus
    cycle_length_s: HistoricalComparison

class Q3CycleStability(BaseModel):
    status: AssessmentStatus
    stability: HistoricalComparison = Field(description="Platform's existing Cycle Stability metric")
    polarity: StabilityPolarity = Field(description="Only the poorer side is flagged")

class Q3CPhaseServiceApproach(ApproachRef):
    service: HistoricalComparison
    status: PhaseServiceStatus

class Q3CPhaseService(BaseModel):
    status: AssessmentStatus
    unit: str = Field(description="Unit of the established phase-service value", examples=["s/cycle", "%"])
    approaches: list[Q3CPhaseServiceApproach] = Field(default_factory=list)

    @property
    def affected_approach_ids(self) -> list[str]:
        abnormal = (PhaseServiceStatus.ABNORMAL_LOW, PhaseServiceStatus.ABNORMAL_HIGH)
        return [a.approach_id for a in self.approaches if a.status in abnormal]

class Q3SignalOperation(BaseModel):
    status: AssessmentStatus
    cycle_length: Q3CycleLength | None = None
    cycle_stability: Q3CycleStability | None = None
    phase_service: Q3CPhaseService | None = None

    @model_validator(mode="after")
    def _check_two_of_three(self, info: ValidationInfo):
        if _is_trusted(info):
            return self
        statuses = [
            c.status if c else AssessmentStatus.INSUFFICIENT_DATA
            for c in (self.cycle_length, self.cycle_stability, self.phase_service)
        ]
        n_abnormal = statuses.count(AssessmentStatus.ABNORMAL)
        n_assessed = len(statuses) - statuses.count(AssessmentStatus.INSUFFICIENT_DATA)
        if n_abnormal >= 2:
            expected = AssessmentStatus.ABNORMAL
        elif n_assessed >= 2:
            expected = AssessmentStatus.NORMAL
        else:
            expected = AssessmentStatus.INSUFFICIENT_DATA
        if self.status != expected:
            raise ValueError(f"Q3 status {self.status.value} breaks the 2-of-3 rule (expected {expected.value})")
        return self

def classify_site(
    q2: Q2DetectorGate,
    q1: Q1TrafficAbnormality | None,
    q3: Q3SignalOperation | None,
) -> SiteCategory:
    """Section 10 decision matrix; observed Q2 failure takes precedence."""
    if q2.status == GateStatus.FAIL:
        return SiteCategory.DETECTOR_HEALTH_ISSUE
    if q2.status == GateStatus.INSUFFICIENT_DATA or q1 is None or q3 is None:
        return SiteCategory.GREY
    if AssessmentStatus.INSUFFICIENT_DATA in (q1.status, q3.status):
        return SiteCategory.GREY
    q1_abnormal = q1.status == AssessmentStatus.ABNORMAL
    q3_abnormal = q3.status == AssessmentStatus.ABNORMAL
    if q1_abnormal and q3_abnormal:
        return SiteCategory.RED
    if q1_abnormal:
        return SiteCategory.AMBER_TRAFFIC
    if q3_abnormal:
        return SiteCategory.AMBER_SIGNAL
    return SiteCategory.NORMAL

class SiteScreeningResult(SiteRef):
    """One site's saved screening record; this is also the Q4 evidence payload."""
    q2: Q2DetectorGate
    q1: Q1TrafficAbnormality | None = Field(default=None, description="None when Q2 did not pass")
    q3: Q3SignalOperation | None = Field(default=None, description="None when Q2 did not pass")
    category: SiteCategory
    total_volume_veh_h: float | None = Field(
        default=None,
        description="Site volume for the period as an hourly rate; drives 'Scale radius by value'",
    )
    notes: list[str] = Field(default_factory=list, description="Why a site is Grey, or other data caveats")

    @model_validator(mode="after")
    def _check_category(self, info: ValidationInfo):
        if _is_trusted(info):
            return self
        expected = classify_site(self.q2, self.q1, self.q3)
        if self.category != expected:
            raise ValueError(f"site {self.site_no}: category {self.category.value} != decision matrix {expected.value}")
        return self

class ScreeningResult(BaseModel):
    """Level 1 output; stored as the screening run record and cache entry."""
    run_id: str
    region: str
    period: AnalysisPeriod
    baseline_version: str
    config: ScreeningConfig
    completed_at: datetime
    sites: list[SiteScreeningResult]
    errors: Annotated[dict[str, str], Field(default_factory=dict, description="site_no -> error for sites that failed to process")]

# Service outputs (core logic -> backend) - Level 2 diagnosis

class EvidenceItem(BaseModel):
    """A statement tied to source values; values are copied from Q1/Q3/Q5, never generated."""
    statement: str = Field(examples=["Northbound volume is 30% above reference."])
    source: str = Field(description="Producing check", examples=["Q1", "Q3A", "Q3B", "Q3C", "Q5"])
    approach_id: str | None = None
    metric: str | None = Field(default=None, examples=["volume", "cycle_length_s", "phase_service", "delay_s"])
    values: dict[str, float | None] = Field(default_factory=dict, examples=[{"current": 412, "reference": 317, "pct_diff": 30.0}])

class Q4Output(BaseModel):
    template: TemplateRef
    diagnosis: str = Field(description="(a) SCATS Diagnosis")
    supporting_evidence: list[EvidenceItem] = Field(description="(b) Supporting Evidence")
    suggested_checks: list[str] = Field(description="(c) Suggested Engineering Checks; review/verify/investigate only")
    limitations: list[str] = Field(default_factory=list)

class TomTomApproachMetrics(ApproachRef):
    delay_s: float | None = None
    control_delay_s: float | None = None
    multi_stop_rate: float | None = None
    queue_length_m: float | None = None
    is_observed: bool = Field(description="False when TomTom had no adequate coverage; missing is never zero")

class TomTomMovementMetrics(BaseModel):
    approach_id: str
    movement: str = Field(examples=["through", "right", "left"])
    delay_s: float | None = None
    control_delay_s: float | None = None

class ScatsComparison(BaseModel):
    approach_id: str
    scats_findings: list[str] = Field(description="SCATS flags on this approach", examples=[["Q1 high", "Q3C abnormal_low"]])
    has_largest_delay: bool
    has_largest_queue: bool
    agreement: ScatsAgreement

class Q5Output(BaseModel):
    template: TemplateRef
    available: bool = Field(description="False -> show TOMTOM_UNAVAILABLE_MESSAGE; Q4 is still shown")
    period: AnalysisPeriod | None = Field(default=None, description="Period actually used; must equal the screening period")
    approaches: list[TomTomApproachMetrics] = Field(default_factory=list)
    movements: list[TomTomMovementMetrics] = Field(default_factory=list)
    largest_delay_approach_id: str | None = None
    largest_queue_approach_id: str | None = None
    scats_comparison: list[ScatsComparison] = Field(default_factory=list)
    missing_approach_ids: list[str] = Field(default_factory=list, description="Partial-coverage disclosure")
    narrative: str = Field(default="", description="Template answer explaining the calculated evidence")

class DiagnosisResult(BaseModel):
    """Level 2 output; stored as the selected Red-site record."""
    diagnosis_id: str
    screening_run_id: str
    site_no: str
    period: AnalysisPeriod
    q4: Q4Output
    q5: Q5Output | None = Field(default=None, description="None or unavailable -> show Q4 alone")
    completed_at: datetime

# Shared run store (Redis/Mongo): one record per cache key, shared across users

class ScreeningCacheKey(BaseModel):
    region: str
    period_end: datetime
    baseline_version: str

    def as_key(self) -> str:
        return f"intersections_diagnostics:screening:{self.region}:{self.period_end.isoformat()}:{self.baseline_version}"

class ScreeningRun(BaseModel):
    """Screening run record and cache entry.

    The background callback writes RUNNING before calling core logic so a second user
    hitting the same key waits on this run instead of starting another.
    """
    run_id: str
    key: ScreeningCacheKey
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    result: ScreeningResult | None = Field(default=None, description="Set when COMPLETED")
    error: str | None = Field(default=None, description="Set when FAILED")

    def to_store_record(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_store_record(cls, record: dict) -> "ScreeningRun":
        """Reload without re-running the 2-of-3 and decision-matrix checks on every site."""
        return cls.model_validate(record, context={"trusted": True})

    def site(self, site_no: str) -> SiteScreeningResult | None:
        if self.result is None:
            return None
        return next((s for s in self.result.sites if s.site_no == site_no), None)

# Panel store (service -> dcc.Store); colours, labels and legend percentages are UI constants

class IntersectionMarker(SiteRef):
    category: SiteCategory
    value_veh_h: float | None = Field(default=None, description="Used when 'Scale radius by value' is on")
    abnormal_approaches: list[str] = Field(default_factory=list, description="Tooltip: Q1/Q3C affected approach names")

class DetectorHealthIssue(SiteRef):
    failed_detectors: list[DetectorCount]

class ScreeningPanelData(BaseModel):
    """What the screening callback writes to the panel's dcc.Store."""
    region: str
    run_id: str | None = Field(default=None, description="None while no run exists yet")
    status: RunStatus = Field(description="RUNNING keeps the dcc.Interval polling the shared run")
    period: AnalysisPeriod | None = None
    baseline_version: str | None = None
    from_cache: bool = False
    next_period_end: datetime | None = Field(default=None, description="When the next refresh becomes available")
    category_counts: dict[SiteCategory, int] = Field(
        default_factory=dict,
        description="All screened sites per category, Normal included; legend percentages come from this",
    )
    markers: list[IntersectionMarker] = Field(default_factory=list, description="Normal sites omitted")
    detector_health_issues: list[DetectorHealthIssue] = Field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_run(cls, run: ScreeningRun, *, from_cache: bool, next_period_end: datetime | None = None) -> "ScreeningPanelData":
        panel = cls(region=run.key.region, run_id=run.run_id, status=run.status, baseline_version=run.key.baseline_version,
                    from_cache=from_cache, next_period_end=next_period_end, error=run.error)
        if run.result is None:
            return panel
        panel.period = run.result.period
        for site in run.result.sites:
            panel.category_counts[site.category] = panel.category_counts.get(site.category, 0) + 1
            ref = SiteRef(site_no=site.site_no, name=site.name, coordinates=site.coordinates).model_dump()
            if site.category == SiteCategory.DETECTOR_HEALTH_ISSUE:
                panel.detector_health_issues.append(DetectorHealthIssue(**ref, failed_detectors=site.q2.failed_detectors))
            elif site.category != SiteCategory.NORMAL:
                approaches = [*(site.q1.approaches if site.q1 else []),
                              *(site.q3.phase_service.approaches if site.q3 and site.q3.phase_service else [])]
                names = {a.approach_id: a.approach_name or a.approach_id for a in approaches}
                affected = DiagnosisInput.affected_ids(site)
                panel.markers.append(IntersectionMarker(
                    **ref, category=site.category, value_veh_h=site.total_volume_veh_h,
                    abnormal_approaches=[names.get(a, a) for a in affected],
                ))
        return panel

    def to_store_record(self) -> dict:
        return self.model_dump(mode="json")

DiagnosisInput.model_rebuild()
