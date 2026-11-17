"""D001 (Q4): SCATS diagnostic interpretation of a Red site from its saved Q1/Q3 results.

No data is retrieved. The evidence is the screening run's own record, rounded for reading; the code
writes a complete answer from it, and the LLM (when available) may only re-word that evidence.
"""
from __future__ import annotations

import json
import re

from .. import llm as llm_mod
from ..stats import ABNORMAL, INSUFFICIENT, NORMAL
from . import definition
from . import readings as rd_mod
from ..layout import D001_LABELS, d001_labels, lines
from ..names import approach_label  # noqa: F401 - re-exported for report.py, d002, link_speed

TEMPLATE = "D001"


def r1(x):
    return None if x is None else round(float(x), 1)


def decimals(row: dict) -> int:
    """1 decimal, or more when the current value rounds onto a range bound it is not equal to (e.g. 67.56 against a
    10th percentile of 67.63 would both read 67.6 and look like a value on the range)."""
    current = row.get("current")
    for d in (1, 2, 3):
        if current is None or not any(b is not None and b != current and round(b, d) == round(current, d)
                                      for b in (row.get("p_low"), row.get("p_high"))):
            return d
    return 3


def evidence(site: dict, period: dict, detail: dict | None = None, schema: dict | None = None,
             control: dict | None = None) -> dict:
    """The diagnosis evidence: the saved 30-minute results and, when read on click (detail.py), the quarter-hour
    view, the phases serving each approach and the table of readings."""
    q1, q3 = site["q1"], site["q3"]
    comps = q3["components"]
    traffic = [{"approach": approach_label(a), "link": a["link"], "current_volume": r1(a["current"]),
                "usual_volume": r1(a["usual"]), "normal_range": [r1(a["p_low"]), r1(a["p_high"])],
                "direction": a["direction"], "pct_difference": r1(a["pct_difference"])}
               for a in q1["approaches"] if a["status"] == ABNORMAL]
    service = [{"approach": approach_label(a), "link": a["link"], "current_green_share_pct": r1(a["current"]),
                "usual_green_share_pct": r1(a["usual"]), "normal_range": [r1(a["p_low"]), r1(a["p_high"])],
                "difference_pp": r1(r1(a["current"]) - r1(a["usual"])), "direction": a["direction"]}
               for a in comps["phase_service"]["approaches"] if a["status"] == ABNORMAL]

    def measure(c, normal_outside: str):
        d = decimals(c)
        rd = lambda x: None if x is None else round(float(x), d)
        out = {"status": c["status"], "current": rd(c["current"]), "usual": rd(c["usual"]),
               "normal_range": [rd(c["p_low"]), rd(c["p_high"])], "pct_difference": r1(c["pct_difference"]), "decimals": d,
               "direction": c["direction"], "reason": c.get("reason"), "position": position(c)}
        if c["status"] == NORMAL and out["position"] not in (None, "within its normal range"):
            out["why_normal"] = normal_outside
        return out

    t_links, s_links = {a["link"] for a in traffic}, {a["link"] for a in service}
    labels = {a["link"]: a["approach"] for a in traffic + service}
    q2 = site.get("q2") or {}
    counts = {r["detector"]: r.get("count_60min") for r in q2.get("detectors") or []}
    view = rd_mod.quarter_view(site, detail, schema)
    weeks = [a.get("n_history") for a in q1["approaches"] + comps["phase_service"]["approaches"]
             if a["status"] == ABNORMAL and a.get("n_history")]
    weeks += [comps[k].get("n_history") for k in ("cycle_length", "cycle_stability")
              if comps[k]["status"] == ABNORMAL and comps[k].get("n_history")]
    ev = {
        "site": site["site"], "intersection": site.get("name"), "period": period["local"],
        "classification": site["label"],
        "traffic": {"status": q1["status"], "approaches_assessed": len(q1["approaches"]), "abnormal_approaches": traffic},
        "signal": {"status": q3["status"], "abnormal_measures": q3["abnormal_count"],
                   "cycle_length_s": measure(comps["cycle_length"], "outside its normal range but less than 10% from "
                                             "usual, so it is not flagged (methodology: both conditions are needed)"),
                   "cycle_stability": {**measure(comps["cycle_stability"], "more stable than usual; only poorer "
                                                 "stability is flagged"),
                                       "meaning": "higher is more stable; only poorer stability is flagged"},
                   "phase_service": {"status": comps["phase_service"]["status"], "abnormal_approaches": service}},
        "same_approach": sorted(labels[k] for k in t_links & s_links),
        "traffic_only_approaches": sorted(labels[k] for k in t_links - s_links),
        "signal_only_approaches": sorted(labels[k] for k in s_links - t_links),
        "phase_groups": phase_groups(service, view),
        "mapping_checks": mapping_checks(traffic, service, view),
        "tolerated_detectors": [{"detector": d, "count_60min": r1(counts.get(d)), "threshold": q2.get("threshold")}
                                for d in q2.get("tolerated") or []],
        "min_history": min(weeks) if weeks else None,
        "quarter_view": view,
        "control": control,
        "phase_service_all": [{"approach": approach_label(a), "current": r1(a["current"]), "usual": r1(a["usual"])}
                              for a in comps["phase_service"]["approaches"] if a["status"] != INSUFFICIENT],
    }
    ev["phase_shifts"] = rd_mod.phase_shifts(ev, view)
    ev["phase_shares"] = rd_mod.phase_shares(ev, view)
    ev["readings"] = rd_mod.readings(ev)
    return ev


def phase_groups(service: list[dict], view: dict | None = None) -> list[list[str]]:
    """Abnormal phase-service approaches served by the same phases, reported once instead of once per approach: the
    same IntersectionPerfApproach "Phases" when read, otherwise identical current, usual and range (15 % of sites)."""
    phases = (view or {}).get("phases") or {}
    use_phases = bool(service) and all(a["approach"] in phases for a in service)
    groups: dict[tuple, list[str]] = {}
    for a in service:
        key = ((phases[a["approach"]], a["direction"]) if use_phases else
               (a["current_green_share_pct"], a["usual_green_share_pct"], tuple(a["normal_range"]), a["direction"]))
        groups.setdefault(key, []).append(a["approach"])
    return [g for g in groups.values()]


def mapping_checks(traffic: list[dict], service: list[dict], view: dict | None = None) -> list[dict]:
    """Usual values that point to the phase-to-approach or link assignment rather than to operation: a usual green
    share of 100 % (the approach is never stopped) or a usual volume of 0. An approach served in every phase of the
    site (its "Phases" lists them all, e.g. Bell Street [W] at SCATS 3055) is green all cycle by design: not a check."""
    out = [{"approach": a["approach"], "measure": "green share", "usual": a["usual_green_share_pct"]}
           for a in service if a["usual_green_share_pct"] is not None and a["usual_green_share_pct"] >= 100
           and not rd_mod.served_in_every_phase(view, a["approach"])]
    out += [{"approach": a["approach"], "measure": "volume", "usual": a["usual_volume"]}
            for a in traffic if a["usual_volume"] is not None and a["usual_volume"] == 0]
    return out


def position(c: dict) -> str | None:
    """Where the current value lies against the 10th-90th range, from the unrounded values."""
    if c.get("current") is None or c.get("p_low") is None or c.get("p_high") is None:
        return None
    if c["current"] < c["p_low"]:
        return "below its normal range"
    if c["current"] > c["p_high"]:
        return "above its normal range"
    return "within its normal range"


def contradictions(answer: dict, ev: dict) -> list[str]:
    """A statement that calls a measure 'within' its range when it is outside it (seen live from the LLM).
    Each "within" is read against the measure named last before it, so "stability is below its range and cycle
    length is within it" is not taken as a claim about stability."""
    names = {"cycle_length_s": "cycle length", "cycle_stability": "stability"}
    texts = [answer.get("diagnosis") or ""] + list(answer.get("supporting_evidence") or [])
    sentences = [s.lower() for t in texts for s in re.split(r"(?<=[.;])\s+", str(t))]
    problems = []
    for key, name in names.items():
        m = ev["signal"][key]
        if m.get("position") in (None, "within its normal range"):
            continue
        for s in sentences:
            claimed = False
            for hit in re.finditer(r"\bwithin\b", s):
                if s[max(0, hit.start() - 4):hit.start()].strip() == "not":
                    continue
                before = s[:hit.start()]
                last = max(names.values(), key=lambda n: before.rfind(n))
                if before.rfind(last) >= 0 and last == name:
                    claimed = True
            if claimed:
                problems.append(f"says {name} is within its normal range; it is {m['position']}")
                break
    return problems


def kept_points(answer: dict, ev: dict) -> list[str]:
    """Points of the draft the LLM must keep (seen live: 9 of 81 LLM answers softened the opposite-direction finding)."""
    text = (answer.get("diagnosis") or "").lower()
    problems = []
    if opposite_approaches(ev) and OPPOSITE not in text:
        problems.append(f'drops "{OPPOSITE}"')
    if ev.get("mapping_checks") and "mapping" not in text:
        problems.append("drops the mapping caveat")
    if ev.get("tolerated_detectors") and "under-count" not in text:
        problems.append("drops the detector caveat")
    table = ev.get("readings") or []
    if table:
        label = d001_labels(table[0]["strength"])[1].lower()
        if label not in text:
            problems.append(f'drops the label "{d001_labels(table[0]["strength"])[1]}"')
        main = text.split(label, 1)[-1].split("other readings:", 1)[0]
        if table[0]["name"].lower() not in main:
            problems.append(f'the most likely reading is not "{table[0]["name"]}"')
    return problems


def _window(ev: dict) -> str:
    """The quarter-hour where the signal change starts, or the whole period."""
    view = ev.get("quarter_view")
    on = rd_mod.onset(view, ev)
    if view and on["signal"] is not None:
        return view["quarters"][on["signal"]]
    return "the period"


def _pct(x):
    return f"{abs(x):.1f}% {'above' if x > 0 else 'below'}"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


ADAPTIVE = ("SCATS adapts cycle length and phase service to demand and coordination, so a value outside its "
            "historical range does not by itself show a signal problem.")
# Said once per report (Q4Output.limitations and the local report), no longer in every diagnosis (17 Nov 2026).
METHOD_NOTE = (ADAPTIVE + " The readings are ranked by the evidence in these data (strength of evidence: Strong, "
               "Moderate or Weak); they are not proven causes.")
MORE_LESS = {"HIGH": ("higher", "longer", "more green"), "LOW": ("lower", "shorter", "less green")}


OPPOSITE = "the opposite of a demand response"


def service_groups(ev: dict) -> list[tuple[list[str], str]]:
    """(approach labels, direction) per phase: approaches with identical phase-service values are one phase."""
    direction = {a["approach"]: a["direction"] for a in ev["signal"]["phase_service"]["abnormal_approaches"]}
    return [(g, direction[g[0]]) for g in ev.get("phase_groups") or [[k] for k in direction]]


def group_name(labels: list[str]) -> str:
    return _and(labels) + (" (one phase)" if len(labels) > 1 else "")


def opposite_approaches(ev: dict) -> list[str]:
    """Approaches whose phase service moved the other way from their volume (diagnosis type A1)."""
    traffic = {a["approach"]: a["direction"] for a in ev["traffic"]["abnormal_approaches"]}
    return [a["approach"] for a in ev["signal"]["phase_service"]["abnormal_approaches"]
            if traffic.get(a["approach"]) not in (None, a["direction"])]


def findings(ev: dict) -> tuple[str, str, str, str]:
    """(what the data show, strength of the main reading, the main reading, the other readings). The readings come
    from the table in readings.py: ranked by the evidence, never stated as a proven cause."""
    t, s = ev["traffic"], ev["signal"]
    cl, cs = s["cycle_length_s"], s["cycle_stability"]
    traffic = {a["approach"]: a["direction"] for a in t["abnormal_approaches"]}
    groups = service_groups(ev)

    shown = []
    if traffic:
        shown.append("Traffic differs from history on " + _and([f"{k} ({MORE_LESS[d][0]} volume than usual)"
                                                               for k, d in traffic.items()]) + ".")
    signal = []
    if cl["status"] == ABNORMAL:
        signal.append(f"cycle length ({MORE_LESS[cl['direction']][1]} than usual)")
    if cs["status"] == ABNORMAL:
        signal.append("Cycle Stability (poorer than usual)")
    signal += [f"phase service to {group_name(g)} ({MORE_LESS[d][2]} than usual)" for g, d in groups]
    if signal:
        shown.append("Signal operation differs from history in " + _and(signal) + ".")
    if ev["same_approach"]:
        shown.append(f"The traffic and phase-service findings are on the same approach ({_and(ev['same_approach'])}); "
                     "this is an association, not proof that one caused the other.")
    elif groups and traffic:
        shown.append("The phase-service finding is on a different approach from the traffic finding.")

    a1 = opposite_approaches(ev)
    if a1:
        shown.append(f"Less green to {_and(a1)} while {'its' if len(a1) == 1 else 'their'} volume is higher is "
                     f"{OPPOSITE} for {'that approach' if len(a1) == 1 else 'those approaches'}.")
    shown += rd_mod.timing_sentences(ev.get("quarter_view"), ev)
    quarters = (ev.get("quarter_view") or {}).get("quarters")
    if ev.get("phase_shares"):                          # with mixed splits: the current shares only
        shown += rd_mod.phase_share_sentences(ev["phase_shares"], quarters)
    else:
        shown += rd_mod.shift_sentences(ev.get("phase_shifts") or [], ev.get("quarter_view"))
    if rd_mod.control_sentence(ev.get("control")):
        shown.append(rd_mod.control_sentence(ev.get("control")))
    if rd_mod.status_sentence(ev.get("control"), quarters):
        shown.append(rd_mod.status_sentence(ev.get("control"), quarters))
    if "readings" not in ev:                            # evidence built without evidence() (tests, old records)
        ev["phase_shifts"] = rd_mod.phase_shifts(ev, ev.get("quarter_view"))
        ev["phase_shares"] = rd_mod.phase_shares(ev, ev.get("quarter_view"))
        ev["readings"] = rd_mod.readings(ev)
    strength, main, others = rd_mod.reading_lines(ev["readings"])
    main = main[0].upper() + main[1:]
    others = others[0].upper() + others[1:]
    return " ".join(shown), strength, main, others


def written(ev: dict) -> dict:
    """The code-written answer: diagnosis (what the data show, then possible explanations), supporting evidence
    (the measurements behind the findings) and checks (in order of priority), from the evidence alone."""
    t, s = ev["traffic"], ev["signal"]
    cl, cs, ps = s["cycle_length_s"], s["cycle_stability"], s["phase_service"]
    shown, strength, main, others = findings(ev)
    labels = d001_labels(strength)
    diagnosis = f"{labels[0]} {shown}\n{labels[1]} {main}\n{labels[2]} {others}"

    support = []
    for a in t["abnormal_approaches"]:
        lo, hi = a["normal_range"]
        support.append(f"{a['approach']}: {a['current_volume']:.0f} veh in 30 min against a usual {a['usual_volume']:.1f} "
                       f"(normal range {lo:.1f}-{hi:.1f}), {_pct(a['pct_difference'])}.")
    for name, m, unit in (("Cycle length", cl, " s"), ("Cycle Stability", cs, "")):
        if m["current"] is None:
            support.append(f"{name}: not assessed ({m.get('reason') or 'insufficient data'}).")
            continue
        if m["status"] != ABNORMAL and not m.get("why_normal"):
            continue                                       # a plain normal value is in the table only
        lo, hi = m["normal_range"]
        d = m.get("decimals", 1)
        rng = f" (normal range {lo:.{d}f}-{hi:.{d}f}{unit})" if lo is not None else ""
        usual = f"{m['usual']:.{d}f}{unit}" if m["usual"] is not None else "not available"
        why = f" ({m['position']}; {m['why_normal']})" if m.get("why_normal") else ""
        support.append(f"{name}: {m['current']:.{d}f}{unit} against a usual {usual}{rng} - {m['status'].lower()}{why}.")
    rows = {a["approach"]: a for a in ps["abnormal_approaches"]}
    for g, _ in service_groups(ev):
        a = rows[g[0]]
        lo, hi = a["normal_range"]
        side = "below" if a["direction"] == "LOW" else "above"
        support.append(f"Phase service {group_name(g)}: green share {a['current_green_share_pct']:.1f}% against a usual "
                       f"{a['usual_green_share_pct']:.1f}% (normal range {lo:.1f}-{hi:.1f}%) - {side} its normal range.")

    # quarter-hour view and phases (read on click), in the same evidence list
    view = ev.get("quarter_view")
    if view and len(view["quarters"]) == 2:
        q = view["quarters"]
        cl_q, cv_q, st_q = view["cycle_length_s"], view["cycle_cv_pct"], view["cycle_stability"]
        if None not in cl_q:
            text = f"By quarter-hour ({q[0]}, {q[1]}): cycle length {cl_q[0]:.1f} s, {cl_q[1]:.1f} s"
            if None not in cv_q:
                text += f"; cycle variation {cv_q[0]:.1f}%, {cv_q[1]:.1f}%"
            if None not in st_q:
                text += f"; Cycle Stability {st_q[0]:.1f}, {st_q[1]:.1f}"
            support.append(text + ".")
        flagged = [a["approach"] for a in t["abnormal_approaches"]]
        vols = [f"{k} {v[0]:.0f}, {v[1]:.0f}" for k, v in view["volume"].items() if k in flagged and None not in v]
        if vols:
            support.append(f"Volume by quarter-hour ({q[0]}, {q[1]}; vehicles per 15 minutes): " + "; ".join(vols) + ".")
    support += (rd_mod.phase_share_sentences(ev["phase_shares"], (view or {}).get("quarters")) if ev.get("phase_shares")
                else rd_mod.shift_sentences(ev.get("phase_shifts") or [], view))

    traffic = {a["approach"]: a["direction"] for a in t["abnormal_approaches"]}
    service = {a["approach"]: a["direction"] for a in ps["abnormal_approaches"]}
    found = []                                          # (kind, check), in the order written below
    # 0. a usual value that points to the mapping: settle it before reading the finding as operation
    for m in ev.get("mapping_checks") or []:
        found.append(("data", f"Verify the {'phase-to-approach' if m['measure'] == 'green share' else 'detector and link'} "
                              f"assignment of {m['approach']}: its usual {m['measure']} is "
                              f"{'100%' if m['measure'] == 'green share' else '0'}."))
    # 1. a phase-service change on an approach whose traffic moved the other way, then the same approach otherwise
    same = sorted(ev["same_approach"], key=lambda k: service.get(k) == traffic.get(k))
    for label in same:
        found.append(("other_phases" if service.get(label) != traffic.get(label) else "demand",
                      f"Verify phase service on {label} against its demand: compare its green time and phase calls "
                      "cycle by cycle with the detector counts for the period."))
    # 2. cycle length: adaptive response or plan / coordination
    if cl["status"] == ABNORMAL:
        found.append(("plan", f"Verify whether the {MORE_LESS[cl['direction']][1]} cycle was SCATS's adaptive response "
                              "or a plan or coordination change: check the plan, the subsystem cycle length and the "
                              "coordination (linking and offsets) in force for the period."))
    # 3. phase service on approaches without a traffic finding, once per phase
    signal_only = set(ev["signal_only_approaches"])
    for g, _ in service_groups(ev):
        only = [k for k in g if k in signal_only]
        if only:
            found.append(("other_phases", f"Check phase service to {group_name(only)}: phase calls, skipped or "
                                          "extended phases, and demand on the competing phases."))
    # 4. stability
    if cs["status"] == ABNORMAL:
        found.append(("plan", "Review cycle-by-cycle cycle lengths in Signal Performance for the period to confirm "
                              "the poorer stability and whether it follows changing demand."))
    # 5. traffic without a signal finding on the same approach: one check for all of them
    if ev["traffic_only_approaches"]:
        found.append(("event", "Check for incidents, events, roadworks or diversions that could explain the unusual "
                               f"volume on {_and(ev['traffic_only_approaches'])}, and monitor whether it persists."))
    # 6. a detector tolerated by the detector check
    for d in ev.get("tolerated_detectors") or []:
        count = f" ({d['count_60min']:.0f} vehicles in 60 minutes)" if d["count_60min"] is not None else ""
        found.append(("data", f"Check detector {d['detector']}{count}: a fault would under-count the volume of the "
                              "approach it serves."))
    # Order: mapping first; then, reading by reading (most supported first), its targeted check in place of the
    # generic checks of the same kind; then whatever is left.
    window = _window(ev)
    checks = [c for k, c in found if k == "data" and "assignment" in c]
    covered = set()
    for r in ev.get("readings") or []:
        targeted = rd_mod.check_for(r, ev, window) if view else None
        if targeted:
            checks.append(targeted)
            covered.add(r["key"])
        else:
            checks += [c for k, c in found if k == r["key"] and c not in checks]
    checks += [c for k, c in found if c not in checks and k not in covered]
    return {"diagnosis": diagnosis, "supporting_evidence": support, "suggested_checks": checks}


SYSTEM = """You write the SCATS diagnostic interpretation for one intersection flagged Red by deterministic screening.
Use only the evidence JSON and the draft answer. The evidence has a table of readings ("readings"), ranked by the
code with a strength of evidence; the first one is the most likely reading. Rules:
- diagnosis: three lines, starting exactly with the draft's labels: "What the data show:", "Most likely reading
  (evidence: <strength>):" with the strength written in the draft, and "Other readings:".
  * What the data show: the findings, then when they happen (quarter-hours) and which phases gained or lost green,
    when the draft gives them. Lead with the most important finding.
  * Most likely reading: name the first reading exactly as written in the table (e.g. "green given to other
    phases") and explain it from its points "for", connecting them in time order where the evidence allows (e.g. the
    volume rose in the first quarter-hour, then the cycle varied and the green moved in the second). Mention its
    points "against" if any. Be direct: "is most consistent with", "points to". Never state a cause as proven and
    never use "caused", "because of", "due to" or "proves".
  * Other readings: each other reading, in one short clause, with why it is weaker (its main point against, or
    that it rests on few points); do not repeat every point.
- Do not add a reading that is not in the table, change the order or the strength, or add causes that are not in the
  evidence or the draft.
- supporting_evidence: the measurements only (current, usual, normal range, difference, quarter-hour values, phase
  shares), no interpretation.
- suggested_checks: keep the draft's checks and their order. You may make a check more specific with the evidence
  (the quarter-hour, the phases, the approaches), keeping its form "verify ...; if confirmed, review ...". Verbs:
  review, verify, check, confirm, compare, investigate, monitor. Do not prescribe timing values.
- Report every abnormal approach and say which measure is unusual. Connect a traffic finding and a phase-service
  finding only when the approach is the same.
- Never use the words fault, faulty or malfunction (the answer is rejected).
- Every number you write must appear in the evidence or in the draft answer. Do not recalculate figures.
- Name every abnormal approach exactly as written in the evidence (e.g. "Swanston Street [N]").
- For cycle length and cycle stability, state the position given in the evidence ("position"); never call a value
  within its normal range unless the position says so.
- Keep the exact words "the opposite of a demand response" where the draft uses them; keep a mapping caveat and a
  detector under-count caveat where the draft has them.
- Write every volume with its unit (veh/30 min or vehicles per 15 minutes), times in s and shares in %; write phase
  groups as "phases A and C", not "phases A,C".
- Write plain English: no field names or codes such as HIGH, LOW, POORER, abnormal_high, Q3C or other_phases, and do
  not mention "the table", "the evidence JSON" or "the draft".
Return JSON with keys: diagnosis (string), supporting_evidence (list of strings), suggested_checks (list of strings)."""


def run(site: dict, period: dict, llm=None, detail: dict | None = None, schema: dict | None = None,
        control: dict | None = None) -> dict:
    """detail: the quarter-hour records read on click (detail.safe_detail); control: the subsystem context
    (subsystems.context). Without them the report is written from the 30-minute values."""
    spec = definition(TEMPLATE)
    ev = evidence(site, period, detail, schema, control)
    draft = written(ev)
    labels = d001_labels((ev["readings"][0]["strength"]) if ev["readings"] else "Weak")
    user = json.dumps({"question": spec["question"], "evidence": ev, "draft_answer": draft}, ensure_ascii=False)
    named = [a["approach"] for a in ev["traffic"]["abnormal_approaches"] + ev["signal"]["phase_service"]["abnormal_approaches"]]
    worded = llm_mod.word(llm, SYSTEM, user, ["diagnosis", "supporting_evidence", "suggested_checks"], ev, draft,
                          required={"diagnosis": named + labels, "supporting_evidence": named},
                          validate=lambda answer: contradictions(answer, ev) + kept_points(answer, ev) + causal(answer),
                          prepare=lambda answer: normalise_labels(answer, labels))
    worded["answer"]["diagnosis"] = lines(worded["answer"]["diagnosis"], labels)
    return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"],
            "evidence": ev, "method_note": METHOD_NOTE, **worded}


MAIN_LABEL = re.compile(r"most\s+likely\s+reading\s*(?:\(\s*(?:strength\s+of\s+)?(?:evidence\s*[:=-]?\s*)?"
                        r"(strong|moderate|weak)(?:\s+evidence)?\s*\))?\s*[:\-–]", re.I)
OTHER_LABEL = re.compile(r"other\s+readings\s*[:\-–]", re.I)
DATA_LABEL = re.compile(r"what\s+the\s+data\s+show\s*[:\-–]", re.I)


def normalise_labels(answer: dict, labels: list[str]) -> dict:
    """The three labels as written by the code when the LLM spelled them differently (seen live at SCATS 4864:
    the answer was rejected for its labels only). A different strength of evidence is left as written, so it is
    still rejected."""
    text = answer.get("diagnosis")
    if isinstance(text, list):
        text = "\n".join(str(x) for x in text)
    if not isinstance(text, str):
        return answer
    strength = labels[1].split(": ", 1)[1].rstrip("):").lower()

    def main(m):
        return labels[1] if m.group(1) is None or m.group(1).lower() == strength else m.group(0)
    text = DATA_LABEL.sub(labels[0], text, count=1)
    text = MAIN_LABEL.sub(main, text, count=1)
    text = OTHER_LABEL.sub(labels[2], text, count=1)
    return {**answer, "diagnosis": text}


CAUSAL = re.compile(r"\b(caused|causes|because of|due to|proves?|proven)\b", re.I)


def causal(answer: dict) -> list[str]:
    """The readings are ranked, not proven: causal wording is rejected (the draft never uses it)."""
    text = re.sub(r"not proof that one caused the other", "", answer.get("diagnosis") or "", flags=re.I)
    hit = CAUSAL.search(text)
    return [f'states a cause ("{hit.group(0)}")'] if hit else []
