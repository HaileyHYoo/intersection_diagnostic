"""Conversion between our screening/diagnosis records and the production contract models.

Our records keep every value the methodology needs; the contract is a projection of them:

    statuses        ABNORMAL / NORMAL / INSUFFICIENT DATA        -> abnormal / normal / insufficient_data
    percentiles     0.10 / 0.90 (rules)                           -> 10 / 90 (ScreeningConfig)
    approach_id     Neo4j EGRESS link_id;  detector_id = n of d[n]
    coordinates     (lon, lat)
    count_60min     the 60-minute total rounded to an integer (the gate itself uses the unrounded total)

Two agreed behaviours need fields the contract does not have yet. They are used as soon as the contract has
them, detected from the models themselves:

    Q3CPhaseService.site_grey_no_green   our Grey rule for an approach without green. Until the field exists,
                                         such a site cannot pass the contract's decision-matrix validator; it is
                                         reported in ScreeningResult.errors instead of being dropped silently.
    ScatsComparison.has_largest_queue    None when the queue is unknown. Until it accepts None, False is written.

Audit fields (methodology 18) the contract does not carry yet are kept in a separate audit record (core.py) and
written into the contract as soon as these optional fields exist (names proposed to the production team):

    Q4Output / Q5Output    generated_by ("code" or "llm:<model>"), llm_rejected (why an LLM answer was not used)
    ScreeningResult        config_version, audit_ref
    DiagnosisResult        config_version, audit_ref
"""
from __future__ import annotations

import typing
from datetime import datetime, timedelta

from . import intersections_diagnostics_schemas as _bundled
from ..stats import ABNORMAL, INSUFFICIENT, NORMAL
from ..timewin import Period, period_ending
from ..templates.d001 import approach_label



def use_contract(module) -> None:
    """Bind the adapter to a contract module: the bundled copy by default, or the host's own module, e.g.
    adapter.use_contract(dash_backend.....intersections_diagnostics_schemas) so both sides share one set of classes."""
    global S, STATUS, STATUS_BACK, GATE, CATEGORY, CATEGORY_BACK, AGREEMENT
    S = module
    STATUS = {NORMAL: S.AssessmentStatus.NORMAL, ABNORMAL: S.AssessmentStatus.ABNORMAL,
              INSUFFICIENT: S.AssessmentStatus.INSUFFICIENT_DATA}
    STATUS_BACK = {v: k for k, v in STATUS.items()}
    GATE = {"PASS": S.GateStatus.PASS, "FAIL": S.GateStatus.FAIL, INSUFFICIENT: S.GateStatus.INSUFFICIENT_DATA}
    CATEGORY = {"red": S.SiteCategory.RED, "amber_traffic": S.SiteCategory.AMBER_TRAFFIC,
                "amber_signal": S.SiteCategory.AMBER_SIGNAL, "normal": S.SiteCategory.NORMAL,
                "grey": S.SiteCategory.GREY, "detector_health": S.SiteCategory.DETECTOR_HEALTH_ISSUE}
    CATEGORY_BACK = {v: k for k, v in CATEGORY.items()}
    AGREEMENT = {"agreement": S.ScatsAgreement.AGREE, "disagreement": S.ScatsAgreement.DISAGREE,
                 "insufficient coverage": S.ScatsAgreement.INSUFFICIENT_COVERAGE}


use_contract(_bundled)
GREY_FLAG = "site_grey_no_green"


class ContractGap(ValueError):
    """A result the current contract cannot represent; the message says which field is missing."""


def accepts_none(model, field: str) -> bool:
    info = model.model_fields.get(field)
    if info is None:
        return False
    annotation = info.annotation
    return annotation is type(None) or type(None) in typing.get_args(annotation)


def has_field(model, field: str) -> bool:
    return field in model.model_fields


def optional(model, **values) -> dict:
    """Only the values whose field the contract model has (so new contract fields are filled automatically)."""
    return {k: v for k, v in values.items() if has_field(model, k)}


# ---------------------------------------------------------------------- shared
def period_model(period: Period) -> S.AnalysisPeriod:
    start, end = period.local_start, period.local_end
    return S.AnalysisPeriod(start=start, end=end, detector_window_start=end - timedelta(minutes=60),
                            weekday=period.weekday, slot_index=start.hour * 2 + start.minute // 30)


def period_from_model(model: S.AnalysisPeriod, rules: dict) -> Period:
    return period_ending(model.end, rules)


def run_id(region: str, period: Period, baseline_version: str) -> str:
    return f"scr_{region}_{period.local_end:%Y%m%dT%H%M}_b{baseline_version}"


def config_model(rules: dict) -> S.ScreeningConfig:
    return S.ScreeningConfig(detector_min_count_60min=rules["q2"]["min_vehicles"], baseline_weeks=rules["history"]["weeks"],
                             min_history_obs=rules["history"]["min_observations"],
                             percentile_low=round(rules["percentiles"]["low"] * 100, 6),
                             percentile_high=round(rules["percentiles"]["high"] * 100, 6),
                             min_relative_diff_pct=rules["q1"]["min_pct_difference"],
                             q3_min_abnormal=rules["q3"]["abnormal_required"], q3_min_assessed=rules["q3"]["assessable_required"])


def rules_overrides(config: S.ScreeningConfig) -> dict:
    """The contract's thresholds as overrides of rules.json (everything else stays as configured)."""
    return {"q2": {"min_vehicles": config.detector_min_count_60min},
            "history": {"weeks": config.baseline_weeks, "min_observations": config.min_history_obs},
            "percentiles": {"low": config.percentile_low / 100, "high": config.percentile_high / 100},
            "q1": {"min_pct_difference": config.min_relative_diff_pct},
            "q3a": {"min_pct_difference": config.min_relative_diff_pct},
            "q3": {"abnormal_required": config.q3_min_abnormal, "assessable_required": config.q3_min_assessed}}


def comparison(row: dict) -> S.HistoricalComparison:
    return S.HistoricalComparison(current=row.get("current"), reference=row.get("usual"), p10=row.get("p_low"),
                                  p90=row.get("p_high"), n_history_obs=row.get("n_history") or 0,
                                  pct_diff=row.get("pct_difference"))


def _coords(site: dict):
    return (site["lon"], site["lat"]) if site.get("lat") is not None and site.get("lon") is not None else None


# ---------------------------------------------------------------------- Level 1
def phase_status(row: dict) -> S.PhaseServiceStatus:
    if row.get("no_green") and hasattr(S.PhaseServiceStatus, "NO_GREEN"):
        return S.PhaseServiceStatus.NO_GREEN
    if row["status"] == ABNORMAL:
        return S.PhaseServiceStatus.ABNORMAL_LOW if row["direction"] == "LOW" else S.PhaseServiceStatus.ABNORMAL_HIGH
    return S.PhaseServiceStatus.NORMAL if row["status"] == NORMAL else S.PhaseServiceStatus.INSUFFICIENT_DATA


def site_model(site: dict, rules: dict) -> S.SiteScreeningResult:
    q2 = site["q2"]
    gate = S.Q2DetectorGate(status=GATE[q2["status"]], detectors=[
        S.DetectorCount(detector_id=str(d["detector"]),
                        count_60min=None if d["count_60min"] is None else int(round(d["count_60min"])),
                        passed=None if d["status"] == INSUFFICIENT else d["status"] == "PASS")
        for d in q2["detectors"]])
    q1 = q3 = None
    notes = list(site.get("reasons", []))
    if site["q1"]:
        q1 = S.Q1TrafficAbnormality(status=STATUS[site["q1"]["status"]], approaches=[
            S.Q1Approach(approach_id=a["link"], approach_name=approach_label(a), volume=comparison(a),
                         is_abnormal=a["status"] == ABNORMAL, status=STATUS[a["status"]],
                         direction=S.DeviationDirection(a["direction"].lower()) if a["status"] == ABNORMAL else None)
            for a in site["q1"]["approaches"]])
        notes += [f"Approach {a['street'] or a['link']} ({a['link']}) not evaluated: {a['reason']}"
                  for a in site["q1"]["not_evaluated"]]
    if site["q3"]:
        c = site["q3"]["components"]
        ps = c["phase_service"]
        service = dict(status=STATUS[ps["status"]], unit="%", approaches=[
            S.Q3CPhaseServiceApproach(approach_id=a["link"], approach_name=approach_label(a), service=comparison(a),
                                      status=phase_status(a)) for a in ps["approaches"]])
        if ps["grey_site"]:
            if not has_field(S.Q3CPhaseService, GREY_FLAG):
                raise ContractGap(f"Grey because {len(ps['without_green'])} evaluated approach(es) have no green; the "
                                  f"contract has no Q3CPhaseService.{GREY_FLAG} yet, so this site cannot be represented")
            service[GREY_FLAG] = True
        q3 = S.Q3SignalOperation(
            status=STATUS[site["q3"]["status"]],
            cycle_length=S.Q3CycleLength(status=STATUS[c["cycle_length"]["status"]], cycle_length_s=comparison(c["cycle_length"])),
            cycle_stability=S.Q3CycleStability(
                status=STATUS[c["cycle_stability"]["status"]], stability=comparison(c["cycle_stability"]),
                polarity=S.StabilityPolarity.LOWER_IS_POORER if rules["q3b"]["higher_is_more_stable"]
                else S.StabilityPolarity.HIGHER_IS_POORER),
            phase_service=S.Q3CPhaseService(**service))
    return S.SiteScreeningResult(site_no=site["site"], name=site.get("name") or "", coordinates=_coords(site), q2=gate,
                                 q1=q1, q3=q3, category=CATEGORY[site["category"]],
                                 total_volume_veh_h=site.get("total_volume_veh_h"), notes=notes)


def screening_result(payload: dict, settings, run: str | None = None, completed_at: datetime | None = None,
                     baseline_version: str | None = None, audit_ref: str | None = None) -> S.ScreeningResult:
    """A stored run (service payload) as the contract's ScreeningResult; unrepresentable sites go to errors."""
    period = period_ending(payload["period"]["end"], settings.rules)
    sites, errors = [], dict(payload.get("errors", {}))
    for site in payload["sites"]:
        try:
            sites.append(site_model(site, settings.rules))
        except (ContractGap, ValueError) as exc:
            errors[site["site"]] = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    version = baseline_version or payload["baseline"]["version"]
    return S.ScreeningResult(run_id=run or run_id(payload["region"], period, version),
                             region=payload["region"], period=period_model(period), baseline_version=version, config=config_model(settings.rules),
                             completed_at=completed_at or datetime.now().astimezone(), sites=sites, errors=errors,
                             **optional(S.ScreeningResult, config_version=settings.rules_version, audit_ref=audit_ref))


def network(inp: S.ScreeningInput) -> list[dict] | None:
    """The host's site list in our form, or None to read it from the source."""
    if not inp.sites:
        return None
    out = []
    for s in inp.sites:
        lon, lat = s.coordinates if s.coordinates else (None, None)
        out.append({"site": s.site_no, "name": s.name, "lat": lat, "lon": lon,
                    "detectors": [d for d in s.detector_ids if str(d).isdigit()],
                    "links": [{"link": a.approach_id, "street": a.approach_name or None} for a in s.approaches]})
    return out


# ---------------------------------------------------------------------- Level 2
def site_from_model(m: S.SiteScreeningResult) -> dict:
    """The contract's saved evidence back in our record form, for D001/D002 (values unchanged)."""
    def row(approach_id, name, hc, status, direction):
        return {"link": approach_id, "street": name or None, "bound": None, "current": hc.current, "usual": hc.reference,
                "p_low": hc.p10, "p_high": hc.p90, "n_history": hc.n_history_obs, "pct_difference": hc.pct_diff,
                "status": status, "direction": direction}

    q1 = {"status": STATUS_BACK[m.q1.status], "not_evaluated": [], "approaches": [
        row(a.approach_id, a.approach_name, a.volume, STATUS_BACK[a.status], a.direction.value.upper() if a.direction else None)
        for a in m.q1.approaches]}
    ps = m.q3.phase_service
    phase_rows = []
    for a in ps.approaches if ps else []:
        abnormal = a.status in (S.PhaseServiceStatus.ABNORMAL_LOW, S.PhaseServiceStatus.ABNORMAL_HIGH)
        status = ABNORMAL if abnormal else NORMAL if a.status == S.PhaseServiceStatus.NORMAL else INSUFFICIENT
        direction = ("LOW" if a.status == S.PhaseServiceStatus.ABNORMAL_LOW else "HIGH") if abnormal else None
        phase_rows.append(row(a.approach_id, a.approach_name, a.service, status, direction))

    def component(c, hc_name):
        if c is None:
            return {"status": INSUFFICIENT, "current": None, "usual": None, "p_low": None, "p_high": None,
                    "n_history": 0, "pct_difference": None, "direction": None, "reason": "not provided"}
        hc = getattr(c, hc_name)
        status = STATUS_BACK[c.status]
        direction = "POORER" if hc_name == "stability" and status == ABNORMAL else \
            (("HIGH" if (hc.current or 0) > (hc.reference or 0) else "LOW") if status == ABNORMAL else None)
        return {**row(None, None, hc, status, direction), "reason": None}

    components = {"cycle_length": component(m.q3.cycle_length, "cycle_length_s"),
                  "cycle_stability": component(m.q3.cycle_stability, "stability"),
                  "phase_service": {"status": STATUS_BACK[ps.status] if ps else INSUFFICIENT, "approaches": phase_rows,
                                    "flagged": [r["link"] for r in phase_rows if r["status"] == ABNORMAL],
                                    "without_green": [], "grey_site": False}}
    statuses = [c["status"] for c in components.values()]
    lon, lat = m.coordinates if m.coordinates else (None, None)
    return {"site": m.site_no, "name": m.name or None, "lat": lat, "lon": lon, "category": CATEGORY_BACK[m.category],
            "label": "Red - Needs Attention" if m.category == S.SiteCategory.RED else m.category.value,
            "reasons": m.notes, "q1": q1,
            "q3": {"status": STATUS_BACK[m.q3.status], "abnormal_count": statuses.count(ABNORMAL),
                   "assessable_count": sum(s != INSUFFICIENT for s in statuses), "components": components}}


def template_ref(rules: dict, template: str) -> S.TemplateRef:
    ref = rules["contract"]["template_ids"][template]
    return S.TemplateRef(template_id=ref["template_id"], version=ref["version"])


def _f(x):
    return None if x is None else round(float(x), 3)


def evidence_items(site: dict) -> list[S.EvidenceItem]:
    """Supporting evidence as statements tied to the source values (written by code, values copied)."""
    items = []
    for a in site["q1"]["approaches"]:
        if a["status"] == ABNORMAL:
            items.append(S.EvidenceItem(
                statement=f"{approach_label(a)} volume is {abs(a['pct_difference']):.1f}% "
                          f"{'above' if a['pct_difference'] > 0 else 'below'} its reference and outside its normal range.",
                source="Q1", approach_id=a["link"], metric="volume",
                values={"current": _f(a["current"]), "reference": _f(a["usual"]), "p10": _f(a["p_low"]),
                        "p90": _f(a["p_high"]), "pct_diff": _f(a["pct_difference"])}))
    comps = site["q3"]["components"]
    for source, key, metric, name in (("Q3A", "cycle_length", "cycle_length_s", "Cycle length"),
                                      ("Q3B", "cycle_stability", "cycle_stability", "Cycle Stability")):
        c = comps[key]
        if c["status"] == INSUFFICIENT:
            text = f"{name} could not be assessed ({c.get('reason') or 'insufficient data'})."
        else:
            text = f"{name} is {c['status'].lower()} against its history" + (
                " (poorer stability)." if key == "cycle_stability" and c["status"] == ABNORMAL else ".")
        items.append(S.EvidenceItem(statement=text, source=source, metric=metric,
                                    values={"current": _f(c["current"]), "reference": _f(c["usual"]), "p10": _f(c["p_low"]),
                                            "p90": _f(c["p_high"]), "pct_diff": _f(c["pct_difference"])}))
    for a in comps["phase_service"]["approaches"]:
        if a["status"] == ABNORMAL:
            side = "below its 10th" if a["direction"] == "LOW" else "above its 90th"
            items.append(S.EvidenceItem(statement=f"Phase service to {approach_label(a)} is {side} percentile.",
                                        source="Q3C", approach_id=a["link"], metric="phase_service",
                                        values={"current": _f(a["current"]), "reference": _f(a["usual"]),
                                                "p10": _f(a["p_low"]), "p90": _f(a["p_high"])}))
    return items


def q4_output(site: dict, d001: dict, rules: dict, template: S.TemplateRef | None = None) -> S.Q4Output:
    comps = site["q3"]["components"]
    limitations = [f"{name} not assessed: {c.get('reason') or 'insufficient data'}"
                   for name, c in (("Cycle length", comps["cycle_length"]), ("Cycle Stability", comps["cycle_stability"]))
                   if c["status"] == INSUFFICIENT]
    return S.Q4Output(template=template or template_ref(rules, "D001"), diagnosis=d001["answer"]["diagnosis"],
                      supporting_evidence=evidence_items(site), suggested_checks=d001["answer"]["suggested_checks"],
                      limitations=limitations,
                      **optional(S.Q4Output, generated_by=d001["generated_by"], llm_rejected=d001["rejected"]))


def q5_output(d002: dict, period: Period, rules: dict, template: S.TemplateRef | None = None) -> S.Q5Output:
    ev = d002["evidence"]
    template = template or template_ref(rules, "D002")
    if not ev["available"]:
        return S.Q5Output(template=template, available=False, period=period_model(period),
                          missing_approach_ids=ev["missing_approach_links"], narrative=d002["answer"]["road_user_impact"],
                          **optional(S.Q5Output, generated_by=d002["generated_by"], llm_rejected=d002["rejected"]))
    ident = lambda a: a["link"] or f"tomtom:{a['tomtom_approach']}"
    approaches = [S.TomTomApproachMetrics(approach_id=ident(a), approach_name=a["approach"], delay_s=a["approach_delay_s"],
                                          control_delay_s=a["control_delay_s"], multi_stop_rate=a["multi_stop_rate"],
                                          queue_length_m=a["queue_mean_m"] if a["queue_adequate"] else None,
                                          is_observed=a["adequate"]) for a in ev["approaches"]]
    movements = [S.TomTomMovementMetrics(approach_id=ident(a), movement=m["movement"], control_delay_s=m.get("control_delay_s"))
                 for a in ev["approaches"] for m in a["movements"]]
    comp = ev["comparison"]
    none_ok = accepts_none(S.ScatsComparison, "has_largest_queue")
    scats = [S.ScatsComparison(approach_id=p["link"], scats_findings=p["scats_findings"],
                               has_largest_delay=bool(p["has_largest_delay"]),
                               has_largest_queue=p["has_largest_queue"] if none_ok else bool(p["has_largest_queue"]),
                               agreement=AGREEMENT[p["agreement"]]) for p in comp["per_approach"]]
    return S.Q5Output(template=template, available=True, period=period_model(period),
                      approaches=approaches, movements=movements,
                      largest_delay_approach_id=comp["greatest_delay"]["link"] if comp["greatest_delay"] else None,
                      largest_queue_approach_id=comp["longest_queue"]["link"] if comp["longest_queue"] else None,
                      scats_comparison=scats, missing_approach_ids=ev["missing_approach_links"],
                      narrative=d002["answer"]["road_user_impact"],
                      **optional(S.Q5Output, generated_by=d002["generated_by"], llm_rejected=d002["rejected"]))
