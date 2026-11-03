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
when it is observed without either, and has insufficient coverage when it is not observed. The site verdict
(methodology owner's review, 3 Nov 2026): agreement when every SCATS-identified approach agrees, partial
agreement when some do and others disagree or are not covered, disagreement when none agrees and at least one
is observed, insufficient coverage when none is observed. TomTom shows road-user impact, never its cause.
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
DEFAULT_NOTE = "all mapped approaches observed in both quarter-hours"
PARTIAL = "partial agreement"           # site level only: some SCATS-identified approaches agree, others do not


DELAY_FIELDS = {"approach_delay", "control_delay"}

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


def _street(name) -> str:
    return " ".join(str(name or "").lower().split())


def resolve_stubs(approaches: dict, names: dict) -> dict[str, str]:
    """{TomTom approach: site EGRESS link} for approaches the mapping file ties to a link upstream of the site's
    approach link (stub_hops > 0; the approach link itself is a short stub). Such an approach is the site's
    approach on the same street when exactly one approach of the site on that street has no other TomTom
    approach; otherwise it stays unmatched (never guessed)."""
    taken = {info.get("link") for info in approaches.values() if info.get("link") in names}
    out = {}
    for approach_id, info in approaches.items():
        if info.get("link") in names or not info.get("stub_hops") or not info.get("street"):
            continue
        candidates = [l for l, row in names.items() if l not in taken and _street(row.get("street")) == _street(info["street"])]
        if len(candidates) == 1:
            out[approach_id] = candidates[0]
            taken.add(candidates[0])
    return out


def measure(source, site: dict, period: Period, rules: dict) -> dict:
    mapping = source.tomtom_mapping(site["site"])
    rows = source.tomtom_turn_kpi(site["site"], period.start, period.end)
    aligner = Aligner(rules["alignment"])
    series = defaultdict(list)
    for r in rows:
        series[(r["approach"], r["exit"], r["field"])].append((r["time"], r["value"]))
    ends = period.interval_ends(15)
    feed = source.schema["influx"]["sources"]["tomtom_turn_kpi"] if hasattr(source, "schema") else {}
    label = feed.get("timestamp_label", "end")
    aligned = {k: {t: v for t, v in aligner.align(points, 15, label).items() if t in ends} for k, points in series.items()}

    names = {a["link"]: a for a in site["q1"]["approaches"] + site["q1"].get("not_evaluated", [])}
    names.update({a["link"]: a for a in site["q3"]["components"]["phase_service"]["approaches"]})
    tt = rules["tomtom"]
    metric = tt.get("delay_metric", "control_delay")
    if tt.get("negative_delay", "zero") == "zero":                     # the chatbot's delay_policy: faster than
        aligned = {k: ({t: max(v, 0.0) for t, v in s.items()} if k[2] in DELAY_FIELDS else s)   # free flow = no delay
                   for k, s in aligned.items()}
    acc = defaultdict(lambda: {"quarters": defaultdict(set), "delay": defaultdict(list), "control": [],
                               "weighted": defaultdict(list), "movements": {}})
    for (approach, exit_id, field), s in aligned.items():
        a = acc[approach]
        a["quarters"][field].update(s)
        if field == "approach_delay":
            for t, v in s.items():
                a["delay"][t].append(v)
        elif field == "control_delay":
            # The chatbot's approach and movement control delay (tomtom/los.py): the plain mean of the stored
            # 15-minute turn records; "sample_weighted" weights them by SampleCount instead.
            weights = aligned.get((approach, exit_id, "sample_count"), {})
            pairs = [(v, (weights.get(t, 0) or 0) if tt.get("delay_mean") == "sample_weighted" else 1) for t, v in s.items()]
            a["control"] += pairs
            if s:
                a["movements"].setdefault(exit_id, {})["control_delay_s"] = r1(_weighted(pairs))
        elif field == "multi_stop_rate":
            weights = aligned.get((approach, exit_id, "sample_count"), {})
            a["weighted"][field] += [(v, weights.get(t, 0) or 0) for t, v in s.items()]

    queue, queue_status = _queue(source, site["site"], period, rules)
    min_minutes = rules["tomtom"]["queue_min_minutes"]
    approaches, exits = mapping.get("approaches", {}), mapping.get("exits", {})
    via_stub = resolve_stubs(approaches, names)
    out = []
    for approach_id in sorted(set(acc) | set(queue)):
        a, info = acc[approach_id], approaches.get(approach_id, {})
        mapped_link = info.get("link")
        link = via_stub.get(approach_id, mapped_link)
        on_site = link in names                         # one of the site's screened (EGRESS) approaches
        base = names.get(link, {"link": link, "street": info.get("street"), "bound": info.get("direction")})
        label = approach_label(base) if on_site else \
            f"{info.get('street') or 'TomTom approach'} ({(info.get('direction') or '?').lower()}bound, link {link})"
        delays = [mean(v) for v in a["delay"].values() if v]
        q = queue.get(approach_id)
        movements = []
        for exit_id, mv in sorted(a["movements"].items()):
            out_arm = exits.get(exit_id, {})
            turn = movement(info.get("direction"), out_arm.get("direction"))
            movements.append({"exit": exit_id, "movement": turn or "unknown", "to_street": out_arm.get("street"),
                              "to_direction": out_arm.get("direction"), **mv})
        mrate = _weighted(a["weighted"].get("multi_stop_rate", []))
        approach_delay = r1(mean(delays)) if delays else None
        control_delay = r1(_weighted(a["control"]))
        quarters = len(a["quarters"][metric])
        out.append({"tomtom_approach": approach_id, "link": link, "mapped": link is not None, "on_site": on_site,
                    "mapped_link": mapped_link, "via_stub": approach_id in via_stub,
                    "stub_hops": info.get("stub_hops", 0),
                    "approach": label if link else f"TomTom approach {approach_id} (not mapped)",
                    "delay_s": control_delay if metric == "control_delay" else approach_delay,
                    "approach_delay_s": approach_delay, "control_delay_s": control_delay,
                    "multi_stop_rate": None if mrate is None else round(mrate, 3),
                    "quarters_observed": quarters,
                    "adequate": quarters >= tt["adequate_quarters"],
                    "quarters_by": {m: len(a["quarters"][m]) for m in DELAY_FIELDS},
                    "queue_mean_m": r1(q["mean_m"]) if q else None, "queue_max_m": r1(q["max_m"]) if q else None,
                    "queue_minutes": q["minutes"] if q else 0,
                    "queue_adequate": bool(q) and q["minutes"] >= min_minutes,
                    "movements": movements})
    out.sort(key=lambda r: -(r["delay_s"] if r["delay_s"] is not None else -1))
    site_rows = source.tomtom_site_kpi(site["site"], period.start, period.end)
    site_delay = [max(float(r["value"]), 0.0) for r in site_rows if r["field"] == "control_delay"]
    return {"approaches": out, "mapping_size": len(approaches), "queue_status": queue_status, "delay_metric": metric,
            "ranked_delays": tt.get("ranked_delays", [metric]), "adequate_quarters": tt["adequate_quarters"],
            "site_control_delay_s": r1(mean(site_delay)) if site_delay else None}


DELAY_NAMES = {"control_delay": "control delay", "approach_delay": "approach delay"}
CAVEAT = "Highest among the observed approaches does not mean historically abnormal delay."
FINDINGS = {"Q1 high": "volume above its normal range", "Q1 low": "volume below its normal range",
            "Q3C abnormal_high": "phase service above its normal range",
            "Q3C abnormal_low": "phase service below its normal range"}


def _delay(a: dict, metric: str):
    return a["control_delay_s"] if metric == "control_delay" else a["approach_delay_s"]


def compare(measured: dict, flagged: dict[str, dict]) -> dict:
    """Rank the adequately observed approaches by each delay in ranked_delays (decision: control and approach
    delay) and by queue; a SCATS-identified approach agrees when it has the greatest of any of them."""
    rows = measured["approaches"]
    primary = measured.get("delay_metric", "control_delay")
    metrics = measured.get("ranked_delays") or [primary]
    need = measured.get("adequate_quarters", 2)
    seen = lambda a, m: bool(a and a["link"] and _delay(a, m) is not None
                             and a.get("quarters_by", {}).get(m, a["quarters_observed"]) >= need)
    tops = {m: max((a for a in rows if seen(a, m)), key=lambda a, m=m: _delay(a, m), default=None) for m in metrics}
    queue_rank = sorted((a for a in rows if a["queue_adequate"] and a["link"]), key=lambda a: -a["queue_mean_m"])
    top_queue = queue_rank[0] if queue_rank else None
    queue_known = measured["queue_status"] == "available"
    by_link = {a["link"]: a for a in rows if a["link"]}
    per_approach = []
    for link, f in flagged.items():
        a = by_link.get(link)
        largest_by = {m: (bool(tops[m] and tops[m]["link"] == link) if seen(a, m) else None) for m in metrics}
        observed = any(v is not None for v in largest_by.values())
        largest_delay = any(largest_by.values()) if observed else None
        largest_queue = (bool(top_queue and top_queue["link"] == link) if a and a["queue_adequate"] else None) if queue_known else None
        if largest_delay or largest_queue:
            verdict = AGREE
        elif observed:
            verdict = DISAGREE
        else:
            verdict = NO_COVERAGE
        per_approach.append({"link": link, "approach": f["approach"], "scats_findings": f["findings"], "observed": observed,
                             "has_largest_delay": largest_delay, "largest_by_delay": largest_by,
                             "has_largest_queue": largest_queue, "agreement": verdict})
    overall = site_verdict([p["agreement"] for p in per_approach])
    top = lambda m: {"approach": tops[m]["approach"], "link": tops[m]["link"], "metric": m,
                     "delay_s": _delay(tops[m], m)} if tops.get(m) else None
    return {"agreement": overall, "per_approach": per_approach,
            "greatest_delay": top(primary) if primary in tops else None,
            "greatest_delays": {m: top(m) for m in metrics},
            "longest_queue": {"approach": top_queue["approach"], "link": top_queue["link"],
                              "queue_mean_m": top_queue["queue_mean_m"]} if top_queue else None,
            "uncovered_scats_approaches": [p["approach"] for p in per_approach if not p["observed"]]}


def site_verdict(verdicts: list[str]) -> str:
    if verdicts and all(v == AGREE for v in verdicts):
        return AGREE
    if AGREE in verdicts:
        return PARTIAL
    return DISAGREE if DISAGREE in verdicts else NO_COVERAGE


def coverage(rows: list[dict], flagged: dict[str, dict], queue_status: str, period_minutes: int = 30,
             quarters: int = 2) -> dict:
    """How much of the 30 minutes TomTom delay and queue cover on each SCATS-identified approach."""
    by_link = {a["link"]: a for a in rows if a["link"]}
    parts, full = [], True
    queue = queue_status == "available"
    for link, f in flagged.items():
        a = by_link.get(link)
        delay_q = a["quarters_observed"] if a else 0
        queue_m = a["queue_minutes"] if a else 0
        part = f"{f['approach']}: delay in {delay_q} of {quarters} 15-minute periods"
        if queue:
            part += f", queue in {queue_m} of {period_minutes} minutes"
            full = full and queue_m >= period_minutes
        full = full and delay_q >= quarters
        parts.append(part)
    if not flagged:
        statement = "No SCATS-identified approach to compare."
    elif full and queue:
        statement = "Delay and queue are available for the full 30 minutes on every SCATS-identified approach."
    else:
        statement = "Coverage of the SCATS-identified approaches: " + "; ".join(parts) + "."
        if not queue:
            statement += " Junction Analytics queue: " + queue_status + "."
    return {"per_approach": parts, "full_period": bool(flagged) and full and queue, "statement": statement}


def _per_approach_sentence(p: dict) -> str:
    """One SCATS-identified approach against the TomTom rankings (methodology 13: report any mismatch)."""
    if p["agreement"] == NO_COVERAGE:
        return f"{p['approach']}, identified by the SCATS screening, has no adequate TomTom coverage in this period."
    who = f"{p['approach']}, identified by the SCATS screening ({'; '.join(FINDINGS.get(f, f) for f in p['scats_findings'])}),"
    by = p.get("largest_by_delay") or {"delay": p["has_largest_delay"]}
    names = {m: "the greatest " + DELAY_NAMES.get(m, "delay") for m in by}
    has = [names[m] for m, v in by.items() if v]
    lacks = [names[m] for m, v in by.items() if v is False]
    if p["has_largest_queue"]:
        has.append("the longest queue")
    elif p["has_largest_queue"] is False:
        lacks.append("the longest queue")
    unknown = [] if p["has_largest_queue"] is not None else ["queue not known"]
    unknown += [DELAY_NAMES.get(m, "delay") + " not adequately observed" for m, v in by.items() if v is None]
    tail = f" ({'; '.join(unknown)})" if unknown else ""
    if has:
        return f"{who} has {_and(has)}" + (f" but not {_or(lacks)}" if lacks else "") + tail + "."
    return f"{who} has neither {_or(lacks, 'nor')}{tail}." if len(lacks) > 1 else f"{who} does not have {_or(lacks)}{tail}."


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _or(items: list[str], word: str = "or") -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {word} " + items[-1]


def written(ev: dict) -> dict:
    if not ev["available"]:
        return {"road_user_impact": UNAVAILABLE, "agreement": NO_COVERAGE, "coverage": ev["coverage_note"]}
    comp = ev["comparison"]
    lines = []
    tops = {m: t for m, t in (comp.get("greatest_delays") or {"x": comp["greatest_delay"]}).items() if t}
    longest = comp["longest_queue"]
    found = [(f"the greatest TomTom {DELAY_NAMES.get(t['metric'], 'delay')} ({t['delay_s']:.1f} s)", t)
             for t in tops.values()]
    if longest:
        found.append((f"the longest mean queue ({longest['queue_mean_m']:.1f} m)", longest))
    by_approach = {}
    for text, t in found:
        by_approach.setdefault(t["approach"], []).append(text)
    for approach, texts in by_approach.items():
        verb = "are all on" if len(texts) > 2 else "are both on" if len(texts) == 2 else "is on"
        sentence = f"{_and(texts)} among the adequately observed approaches {verb} {approach}."
        lines.append(sentence[0].upper() + sentence[1:])
    lines += [_per_approach_sentence(p) for p in comp["per_approach"]]
    group = lambda v: [p["approach"] for p in comp["per_approach"] if p["agreement"] == v]
    agreeing, differing, uncovered = group(AGREE), group(DISAGREE), group(NO_COVERAGE)
    verdict = comp["agreement"]
    if verdict == AGREE:
        lines.append(f"Overall: agreement - TomTom matches the SCATS findings on {_and(agreeing)}. This supports a "
                     "road-user impact there without establishing its cause.")
    elif verdict == PARTIAL:
        rest = ([f"differs on {_and(differing)}"] if differing else []) + \
               ([f"does not cover {_and(uncovered)}"] if uncovered else [])
        lines.append(f"Overall: partial agreement - TomTom matches the SCATS findings on {_and(agreeing)} but "
                     f"{' and '.join(rest)}. This supports a road-user impact on {_and(agreeing)} only, without "
                     "establishing its cause.")
    elif verdict == DISAGREE:
        lines.append(f"Overall: disagreement - the TomTom data do not confirm a road-user impact on {_and(differing)}"
                     + (f" ({_and(uncovered)} not covered)" if uncovered else "") + ".")
    else:
        lines.append("Overall: insufficient coverage - the SCATS-identified approaches are not adequately covered by "
                     "TomTom for this period, so no comparison is possible.")
    lines.append(CAVEAT)
    statement = (ev.get("coverage") or {}).get("statement", "")
    if statement:
        lines.append(statement)
    return {"road_user_impact": " ".join(lines), "agreement": verdict,
            "coverage": "; ".join(x for x in (statement, ev["coverage_note"]) if x)}


SYSTEM = """You explain the TomTom road-user evidence for one intersection flagged Red by SCATS screening.
Use only the evidence JSON. State whether the greatest delay and the longest queue are on a SCATS-identified approach
and report any mismatch. Highest among observed approaches is not historically abnormal delay. Missing approaches
are partial coverage, never zero. Do not say that signal settings caused congestion, queues or delay. Every number
must appear in the evidence or the draft. Keep one statement for every SCATS-identified approach (agreement, mismatch
or no coverage), naming it exactly as in the evidence, and keep the draft's overall verdict (agreement, partial
agreement, disagreement or insufficient coverage) with the approaches that match and those that differ. Keep the
draft's coverage statement (how much of the 30 minutes delay and queue cover). TomTom shows road-user impact, never
proof of cause. State the findings only: no interpretation such as "despite", "as expected" or reasons. Write plain
English, not codes such as abnormal_high or Q3C.
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
    available = any(a["delay_s"] is not None for a in rows)
    notes = []
    if not measured["mapping_size"]:
        notes.append("the site has no TomTom approach mapping")
    partial = [a["approach"] for a in rows if a["delay_s"] is not None and not a["adequate"]]
    if partial:
        notes.append("delay observed in only part of the period: " + ", ".join(partial))
    partial_queue = [a["approach"] for a in rows if a["queue_minutes"] and not a["queue_adequate"]]
    if partial_queue:
        notes.append("queue observed in too few minutes: " + ", ".join(partial_queue))
    unmapped = [a["tomtom_approach"] for a in rows if not a["mapped"]]
    if unmapped:
        notes.append("TomTom approaches without a link mapping: " + ", ".join(unmapped))
    stubbed = [f"{a['approach']} (mapping link {a['mapped_link']}, {a['stub_hops']} link(s) upstream)"
               for a in rows if a.get("via_stub")]
    if stubbed:
        notes.append("TomTom approaches matched through the mapping's upstream link (same street): " + ", ".join(stubbed))
    off_site = [a["approach"] for a in rows if a["mapped"] and not a.get("on_site", True)]
    if off_site:
        notes.append("TomTom approaches mapped to a link that is not one of the site's screened approaches: "
                     + ", ".join(off_site))
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
          "coverage": coverage(rows, flagged, measured["queue_status"]),
          "coverage_note": "; ".join(notes) or DEFAULT_NOTE}
    draft = written(ev)
    if not available:
        return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"], "evidence": ev,
                "answer": draft, "generated_by": "code", "rejected": None}
    user = json.dumps({"question": spec["question"], "evidence": ev, "draft_answer": draft}, ensure_ascii=False)
    named = [p["approach"] for p in comparison["per_approach"]]
    worded = llm_mod.word(llm, SYSTEM, user, ["road_user_impact", "agreement", "coverage"], ev, draft,
                          required={"road_user_impact": named})
    worded["answer"]["agreement"] = draft["agreement"]          # the verdict is code's, never re-worded
    text = worded["answer"]["road_user_impact"]
    if "historically abnormal" not in text:                      # methodology 13: always distinguish the two
        text = text.rstrip() + " " + CAVEAT
    statement = ev["coverage"]["statement"]
    if statement and statement not in text:                     # the 30-minute coverage is always stated
        text = text.rstrip() + " " + statement
    worded["answer"]["road_user_impact"] = text
    return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"], "evidence": ev,
            **worded}
