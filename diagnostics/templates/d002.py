"""D002 (Q5): TomTom road-user performance for the same 30-minute period, compared with the SCATS findings.

Code computes every number, the rankings and the agreement:

    approach delay    mean ApproachDelaySec over the observed quarter-hours   (InfluxDB IntersectionTurnKpi)
    control delay     SampleCount-weighted ControlDelaySec over the approach's movements
    multi-stop rate   SampleCount-weighted MultiStopRate
    movements         per exit, named left / through / right / u_turn from the mapping's travel directions
    queue length      mean of the per-minute queue in the period, and its maximum
                      (Junction Analytics archive; only when rules tomtom.api_enabled)

An approach is adequately observed when it has records in both quarter-hours (tomtom.adequate_quarters); its
queue when at least tomtom.queue_min_minutes minutes have a value. Only adequately observed approaches are
ranked. TomTom approaches are matched to the screening approaches through the ApproachId -> EGRESS link
mapping. A SCATS-identified approach agrees when it has the greatest delay or the longest queue, disagrees
when it is observed without either, and has insufficient coverage when it is not observed.
"""
from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean

from .. import llm as llm_mod
from ..series import Aligner
from ..stats import ABNORMAL
from ..timewin import Period
from ..tomtom_map import movement
from . import definition
from .d001 import approach_label, r1

TEMPLATE = "D002"
UNAVAILABLE = "TomTom confirmation unavailable for this intersection or analysis period."
AGREE, DISAGREE, NO_COVERAGE = "agreement", "disagreement", "insufficient coverage"


def scats_approaches(site: dict) -> dict[str, dict]:
    """{link: {approach, findings}} for the approaches the screening flagged, Q1 first."""
    out = {}
    for a in site["q1"]["approaches"]:
        if a["status"] == ABNORMAL:
            out.setdefault(a["link"], {"approach": approach_label(a), "findings": []})["findings"].append(
                f"Q1 {a['direction'].lower()}")
    for a in site["q3"]["components"]["phase_service"]["approaches"]:
        if a["status"] == ABNORMAL:
            out.setdefault(a["link"], {"approach": approach_label(a), "findings": []})["findings"].append(
                f"Q3C abnormal_{a['direction'].lower()}")
    return out


def _weighted(pairs):
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else mean(v for v, _ in pairs)


def _queue(source, site: str, period: Period, rules: dict) -> tuple[dict, str]:
    """({tomtom approach: {mean, max, minutes}}, status text)."""
    try:
        rows = source.tomtom_queue(site, period.start, period.end)
    except Exception as exc:  # noqa: BLE001 - the queue is optional evidence; the reason is reported
        return {}, "unavailable - " + str(exc)
    per_minute = defaultdict(dict)
    for r in rows:
        minute = r["time"].replace(second=0, microsecond=0)
        per_minute[r["approach"]][minute] = max(per_minute[r["approach"]].get(minute, 0.0), r["queue_m"])
    out = {a: {"mean_m": mean(v.values()), "max_m": max(v.values()), "minutes": len(v)} for a, v in per_minute.items() if v}
    return out, "available" if out else "unavailable - the queue archive returned no rows for this period"


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
    acc = defaultdict(lambda: {"quarters": set(), "delay": defaultdict(list), "weighted": defaultdict(list), "movements": {}})
    for (approach, exit_id, field), s in aligned.items():
        a = acc[approach]
        a["quarters"].update(s)
        if field == "approach_delay":
            for t, v in s.items():
                a["delay"][t].append(v)
        elif field in ("control_delay", "multi_stop_rate"):
            weights = aligned.get((approach, exit_id, "sample_count"), {})
            a["weighted"][field] += [(v, weights.get(t, 0) or 0) for t, v in s.items()]
            mv = a["movements"].setdefault(exit_id, {})
            if field == "control_delay" and s:
                mv["control_delay_s"] = r1(_weighted([(v, weights.get(t, 0) or 0) for t, v in s.items()]))

    queue, queue_status = _queue(source, site["site"], period, rules)
    min_minutes = rules["tomtom"]["queue_min_minutes"]
    approaches, exits = mapping.get("approaches", {}), mapping.get("exits", {})
    out = []
    for approach_id in sorted(set(acc) | set(queue)):
        a, info = acc[approach_id], approaches.get(approach_id, {})
        link = info.get("link")
        base = names.get(link, {"link": link, "street": info.get("street"), "bound": info.get("direction")})
        delays = [mean(v) for v in a["delay"].values() if v]
        q = queue.get(approach_id)
        movements = []
        for exit_id, mv in sorted(a["movements"].items()):
            turn = movement(info.get("direction"), exits.get(exit_id, {}).get("direction"))
            movements.append({"exit": exit_id, "movement": turn or "unknown", **mv})
        mrate = _weighted(a["weighted"].get("multi_stop_rate", []))
        out.append({"tomtom_approach": approach_id, "link": link, "mapped": link is not None,
                    "approach": approach_label(base) if link else f"TomTom approach {approach_id} (not mapped)",
                    "approach_delay_s": r1(mean(delays)) if delays else None,
                    "control_delay_s": r1(_weighted(a["weighted"].get("control_delay", []))),
                    "multi_stop_rate": None if mrate is None else round(mrate, 3),
                    "quarters_observed": len(a["quarters"]),
                    "adequate": len(a["quarters"]) >= rules["tomtom"]["adequate_quarters"],
                    "queue_mean_m": r1(q["mean_m"]) if q else None, "queue_max_m": r1(q["max_m"]) if q else None,
                    "queue_minutes": q["minutes"] if q else 0,
                    "queue_adequate": bool(q) and q["minutes"] >= min_minutes,
                    "movements": movements})
    out.sort(key=lambda r: -(r["approach_delay_s"] if r["approach_delay_s"] is not None else -1))
    site_rows = source.tomtom_site_kpi(site["site"], period.start, period.end)
    site_delay = [float(r["value"]) for r in site_rows if r["field"] == "control_delay"]
    return {"approaches": out, "mapping_size": len(approaches), "queue_status": queue_status,
            "site_control_delay_s": r1(mean(site_delay)) if site_delay else None}


def compare(measured: dict, flagged: dict[str, dict]) -> dict:
    rows = measured["approaches"]
    delay_rank = [a for a in rows if a["adequate"] and a["approach_delay_s"] is not None and a["link"]]
    queue_rank = sorted((a for a in rows if a["queue_adequate"] and a["link"]), key=lambda a: -a["queue_mean_m"])
    top_delay = max(delay_rank, key=lambda a: a["approach_delay_s"], default=None)
    top_queue = queue_rank[0] if queue_rank else None
    queue_known = measured["queue_status"] == "available"
    by_link = {a["link"]: a for a in rows if a["link"]}
    per_approach = []
    for link, f in flagged.items():
        a = by_link.get(link)
        observed = bool(a and a["adequate"] and a["approach_delay_s"] is not None)
        largest_delay = bool(top_delay and top_delay["link"] == link) if observed else None
        largest_queue = (bool(top_queue and top_queue["link"] == link) if a and a["queue_adequate"] else None) if queue_known else None
        if largest_delay or largest_queue:
            verdict = AGREE
        elif observed:
            verdict = DISAGREE
        else:
            verdict = NO_COVERAGE
        per_approach.append({"link": link, "approach": f["approach"], "scats_findings": f["findings"], "observed": observed,
                             "has_largest_delay": largest_delay, "has_largest_queue": largest_queue, "agreement": verdict})
    verdicts = {p["agreement"] for p in per_approach}
    overall = AGREE if AGREE in verdicts else DISAGREE if DISAGREE in verdicts else NO_COVERAGE
    return {"agreement": overall, "per_approach": per_approach,
            "greatest_delay": {"approach": top_delay["approach"], "link": top_delay["link"],
                               "approach_delay_s": top_delay["approach_delay_s"]} if top_delay else None,
            "longest_queue": {"approach": top_queue["approach"], "link": top_queue["link"],
                              "queue_mean_m": top_queue["queue_mean_m"]} if top_queue else None,
            "uncovered_scats_approaches": [p["approach"] for p in per_approach if not p["observed"]]}


def written(ev: dict) -> dict:
    if not ev["available"]:
        return {"road_user_impact": UNAVAILABLE, "agreement": NO_COVERAGE, "coverage": ev["coverage_note"]}
    comp = ev["comparison"]
    lines = []
    top = comp["greatest_delay"]
    if top:
        lines.append(f"The greatest TomTom approach delay among the adequately observed approaches is on {top['approach']} "
                     f"({top['approach_delay_s']:.1f} s).")
    longest = comp["longest_queue"]
    if longest:
        lines.append(f"The longest mean queue is on {longest['approach']} ({longest['queue_mean_m']:.1f} m).")
    flagged = ", ".join(v["approach"] for v in ev["scats_approaches"].values()) or "none"
    if comp["agreement"] == AGREE:
        lines.append(f"This corresponds with an approach identified by the SCATS screening ({flagged}), which supports a "
                     "road-user impact on that approach without establishing its cause.")
    elif comp["agreement"] == DISAGREE:
        lines.append(f"The SCATS screening identified {flagged}; the greatest delay"
                     + (" and the longest queue are" if longest else " is") + " on a different approach, so the TomTom data "
                     "do not confirm a road-user impact on the SCATS-identified approach.")
    else:
        lines.append(f"The SCATS-identified approach(es) ({flagged}) are not adequately covered by TomTom for this period, "
                     "so the comparison is incomplete.")
    lines.append("Highest among the observed approaches does not mean historically abnormal delay.")
    if ev["queue"] != "available":
        lines.append("Queue length: " + ev["queue"] + ".")
    return {"road_user_impact": " ".join(lines), "agreement": comp["agreement"], "coverage": ev["coverage_note"]}


SYSTEM = """You explain the TomTom road-user evidence for one intersection flagged Red by SCATS screening.
Use only the evidence JSON. State whether the greatest delay and the longest queue are on a SCATS-identified approach
and report any mismatch. Highest among observed approaches is not historically abnormal delay. Missing approaches
are partial coverage, never zero. Do not say that signal settings caused congestion, queues or delay. Every number
must appear in the evidence or the draft.
Return JSON with keys: road_user_impact (string), agreement (copy the evidence value), coverage (string)."""


def run(source, site: dict, period: Period, rules: dict, llm=None) -> dict:
    spec = definition(TEMPLATE)
    flagged = scats_approaches(site)
    try:
        measured = measure(source, site, period, rules)
        error = None
    except Exception as exc:  # noqa: BLE001 - Q4 still runs; the report states the missing confirmation
        measured = {"approaches": [], "mapping_size": 0, "site_control_delay_s": None, "queue_status": "unavailable"}
        error = f"{type(exc).__name__}: {exc}"
    rows = measured["approaches"]
    available = any(a["approach_delay_s"] is not None for a in rows)
    notes = []
    if not measured["mapping_size"]:
        notes.append("the site has no TomTom approach mapping")
    partial = [a["approach"] for a in rows if a["approach_delay_s"] is not None and not a["adequate"]]
    if partial:
        notes.append("delay observed in only part of the period: " + ", ".join(partial))
    partial_queue = [a["approach"] for a in rows if a["queue_minutes"] and not a["queue_adequate"]]
    if partial_queue:
        notes.append("queue observed in too few minutes: " + ", ".join(partial_queue))
    unmapped = [a["tomtom_approach"] for a in rows if not a["mapped"]]
    if unmapped:
        notes.append("TomTom approaches without a link mapping: " + ", ".join(unmapped))
    if error:
        notes.append("TomTom data could not be read (" + error[:120] + ")")
    comparison = compare(measured, flagged) if available else None
    observed_links = {a["link"] for a in rows if a["adequate"] and a["link"]}
    missing = [a["link"] for a in site["q1"]["approaches"] if a["link"] not in observed_links]
    if comparison and comparison["uncovered_scats_approaches"]:
        notes.append("SCATS-identified approaches without adequate TomTom data: " + ", ".join(comparison["uncovered_scats_approaches"]))
    ev = {"site": site["site"], "period": period.label(), "available": available, "approaches": rows,
          "site_control_delay_s": measured["site_control_delay_s"], "scats_approaches": flagged, "comparison": comparison,
          "queue": measured["queue_status"], "missing_approach_links": missing,
          "coverage_note": "; ".join(notes) or "all mapped approaches observed in both quarter-hours"}
    draft = written(ev)
    if not available:
        return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"], "evidence": ev,
                "answer": draft, "generated_by": "code", "rejected": None}
    user = json.dumps({"question": spec["question"], "evidence": ev, "draft_answer": draft}, ensure_ascii=False)
    worded = llm_mod.word(llm, SYSTEM, user, ["road_user_impact", "agreement", "coverage"], ev, draft)
    worded["answer"]["agreement"] = draft["agreement"]          # the verdict is code's, never re-worded
    return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"], "evidence": ev,
            **worded}
