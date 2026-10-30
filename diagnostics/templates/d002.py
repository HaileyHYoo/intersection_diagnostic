"""D002 (Q5): TomTom road-user performance for the same 30-minute period, compared with the SCATS findings.

Reads the TomTom KPIs stored in InfluxDB (IntersectionTurnKpi, IntersectionKpi) for the selected site and
the exact screening period. Code computes every number, the ranking and the agreement:

    approach delay    mean ApproachDelaySec over the observed quarter-hours
    control delay     SampleCount-weighted ControlDelaySec over the approach's movements
    multi-stop rate   SampleCount-weighted MultiStopRate
    adequately observed   records in both quarter-hours (rules tomtom.adequate_quarters)

TomTom approaches are matched to the screening approaches through the TomTom ApproachId -> EGRESS link
mapping. The queue length (TomTom Junction Analytics API) is disabled in this version and reported as
unavailable rather than estimated.
"""
from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean

from .. import llm as llm_mod
from ..series import Aligner
from ..stats import ABNORMAL
from ..timewin import Period
from . import definition
from .d001 import approach_label, r1

TEMPLATE = "D002"
UNAVAILABLE = "TomTom confirmation unavailable for this intersection or analysis period."


def scats_approaches(site: dict) -> dict[str, dict]:
    """{link: {approach, reasons}} for the approaches the screening flagged."""
    out = {}
    for a in site["q1"]["approaches"]:
        if a["status"] == ABNORMAL:
            out.setdefault(a["link"], {"approach": approach_label(a), "reasons": []})["reasons"].append(
                f"volume {a['direction'].lower()}")
    for a in site["q3"]["components"]["phase_service"]["approaches"]:
        if a["status"] == ABNORMAL:
            out.setdefault(a["link"], {"approach": approach_label(a), "reasons": []})["reasons"].append(
                f"phase service {a['direction'].lower()}")
    return out


def measure(source, site: dict, period: Period, rules: dict) -> dict:
    mapping = source.tomtom_mapping(site["site"])
    rows = source.tomtom_turn_kpi(site["site"], period.start, period.end)
    aligner = Aligner(rules["alignment"])
    series = defaultdict(list)
    for r in rows:
        series[(r["approach"], r["exit"], r["field"])].append((r["time"], r["value"]))
    ends = period.interval_ends(15)
    aligned = {k: {t: v for t, v in aligner.align(points, 15).items() if t in ends} for k, points in series.items()}

    names = {a["link"]: a for a in site["q1"]["approaches"]}
    names.update({a["link"]: a for a in site["q3"]["components"]["phase_service"]["approaches"]})
    approaches = defaultdict(lambda: {"quarters": set(), "approach_delay": defaultdict(list), "weighted": defaultdict(list),
                                      "movements": {}})
    for (approach, exit_id, field), s in aligned.items():
        a = approaches[approach]
        a["quarters"].update(s)
        if field == "approach_delay":
            for t, v in s.items():
                a["approach_delay"][t].append(v)
    for (approach, exit_id, field), s in aligned.items():
        if field not in ("control_delay", "multi_stop_rate", "turn_ratio"):
            continue
        weights = aligned.get((approach, exit_id, "sample_count"), {})
        for t, v in s.items():
            approaches[approach]["weighted"][field].append((v, weights.get(t, 0) or 0))
        mv = approaches[approach]["movements"].setdefault(exit_id, {})
        mv[field] = r1(mean(s.values())) if s else None

    out = []
    for approach_id, a in approaches.items():
        info = mapping.get(approach_id, {})
        link = info.get("link")
        base = names.get(link, {"link": link, "street": info.get("street"), "bound": info.get("direction")})

        def weighted(field):
            pairs = a["weighted"].get(field, [])
            total = sum(w for _, w in pairs)
            if not pairs:
                return None
            return sum(v * w for v, w in pairs) / total if total else mean(v for v, _ in pairs)

        delays = [mean(v) for v in a["approach_delay"].values() if v]
        out.append({"tomtom_approach": approach_id, "link": link, "mapped": link is not None,
                    "approach": approach_label(base) if link else f"TomTom approach {approach_id} (not mapped)",
                    "approach_delay_s": r1(mean(delays)) if delays else None,
                    "control_delay_s": r1(weighted("control_delay")), "multi_stop_rate": None if weighted("multi_stop_rate") is None
                    else round(weighted("multi_stop_rate"), 3),
                    "quarters_observed": len(a["quarters"]),
                    "adequate": len(a["quarters"]) >= rules["tomtom"]["adequate_quarters"],
                    "movements": [{"exit": k, **v} for k, v in sorted(a["movements"].items())]})
    out.sort(key=lambda r: -(r["approach_delay_s"] or -1))
    site_rows = source.tomtom_site_kpi(site["site"], period.start, period.end)
    site_delay = [r["value"] for r in site_rows if r["field"] == "control_delay"]
    return {"approaches": out, "mapping_size": len(mapping),
            "site_control_delay_s": r1(mean(float(v) for v in site_delay)) if site_delay else None}


def compare(measured: dict, flagged: dict[str, dict]) -> dict:
    adequate = [a for a in measured["approaches"] if a["adequate"] and a["approach_delay_s"] is not None]
    observed_links = {a["link"] for a in adequate if a["link"]}
    uncovered = [v["approach"] for link, v in flagged.items() if link not in observed_links]
    if not adequate:
        return {"agreement": "insufficient coverage", "greatest_delay": None, "uncovered_scats_approaches": uncovered}
    top = adequate[0]
    if top["link"] in flagged:
        verdict = "agreement"
    elif observed_links & set(flagged):
        verdict = "disagreement"          # a flagged approach is observed, but the greatest delay is elsewhere
    else:
        verdict = "insufficient coverage"  # no flagged approach is adequately observed
    return {"agreement": verdict, "greatest_delay": {"approach": top["approach"], "approach_delay_s": top["approach_delay_s"]},
            "uncovered_scats_approaches": uncovered}


def written(ev: dict) -> dict:
    if not ev["available"]:
        return {"road_user_impact": UNAVAILABLE, "agreement": "insufficient coverage", "coverage": ev["coverage_note"]}
    comp = ev["comparison"]
    lines = []
    top = comp["greatest_delay"]
    if top:
        lines.append(f"The greatest TomTom approach delay among the adequately observed approaches is on {top['approach']} "
                     f"({top['approach_delay_s']:.1f} s).")
    flagged = ", ".join(v["approach"] for v in ev["scats_approaches"].values()) or "none"
    if comp["agreement"] == "agreement":
        lines.append(f"This is an approach identified by the SCATS screening ({flagged}), which supports a road-user "
                     "impact on that approach without establishing its cause.")
    elif comp["agreement"] == "disagreement":
        lines.append(f"The SCATS screening identified {flagged}; the greatest delay is on a different approach, so the "
                     "TomTom data do not confirm a road-user impact on the SCATS-identified approach.")
    else:
        lines.append(f"The SCATS-identified approach(es) ({flagged}) are not adequately covered by TomTom for this period, "
                     "so the comparison is incomplete.")
    lines.append("Highest among the observed approaches does not mean historically abnormal delay.")
    lines.append("Queue length: " + ev["queue"] + ".")
    return {"road_user_impact": " ".join(lines), "agreement": comp["agreement"], "coverage": ev["coverage_note"]}


SYSTEM = """You explain the TomTom road-user evidence for one intersection flagged Red by SCATS screening.
Use only the evidence JSON. State whether the greatest delay is on a SCATS-identified approach and report any mismatch.
Highest among observed approaches is not historically abnormal delay. Missing approaches are partial coverage, never zero.
Do not say that signal settings caused congestion, queues or delay. Every number must appear in the evidence or the draft.
Return JSON with keys: road_user_impact (string), agreement (copy the evidence value), coverage (string)."""


def run(source, site: dict, period: Period, rules: dict, llm=None) -> dict:
    spec = definition(TEMPLATE)
    flagged = scats_approaches(site)
    try:
        measured = measure(source, site, period, rules)
        error = None
    except Exception as exc:  # noqa: BLE001 - Q4 still runs; the report states the missing confirmation
        measured, error = {"approaches": [], "mapping_size": 0, "site_control_delay_s": None}, f"{type(exc).__name__}: {exc}"
    rows = measured["approaches"]
    available = any(a["approach_delay_s"] is not None for a in rows)
    partial = [a["approach"] for a in rows if not a["adequate"]]
    unmapped = [a["tomtom_approach"] for a in rows if not a["mapped"]]
    notes = []
    if not measured["mapping_size"]:
        notes.append("the site has no TomTom approach mapping")
    if partial:
        notes.append("observed in only part of the period: " + ", ".join(partial))
    if unmapped:
        notes.append("TomTom approaches without a link mapping: " + ", ".join(unmapped))
    if error:
        notes.append("TomTom data could not be read (" + error[:120] + ")")
    comparison = compare(measured, flagged) if available else None
    if comparison and comparison["uncovered_scats_approaches"]:
        notes.append("SCATS-identified approaches without adequate TomTom data: " + ", ".join(comparison["uncovered_scats_approaches"]))
    queue = ("unavailable - the TomTom Junction Analytics API (queue source) is disabled in this version" if not rules["tomtom"]["api_enabled"]
             else "not implemented")
    ev = {"site": site["site"], "period": period.label(), "available": available, "approaches": rows,
          "site_control_delay_s": measured["site_control_delay_s"], "scats_approaches": flagged, "comparison": comparison,
          "queue": queue, "coverage_note": "; ".join(notes) or "all mapped approaches observed in both quarter-hours"}
    draft = written(ev)
    if not available:
        return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"], "evidence": ev,
                "answer": draft, "generated_by": "code", "rejected": None}
    user = json.dumps({"question": spec["question"], "evidence": ev, "draft_answer": draft}, ensure_ascii=False)
    worded = llm_mod.word(llm, SYSTEM, user, ["road_user_impact", "agreement", "coverage"], ev, draft)
    worded["answer"]["agreement"] = draft["agreement"]          # the verdict is code's, never re-worded
    return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"], "evidence": ev,
            **worded}
