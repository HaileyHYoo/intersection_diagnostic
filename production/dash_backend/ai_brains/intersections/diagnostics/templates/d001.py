"""D001 (Q4): SCATS diagnostic interpretation of a Red site from its saved Q1/Q3 results.

No data is retrieved. The evidence is the screening run's own record, rounded for reading; the code
writes a complete answer from it, and the LLM (when available) may only re-word that evidence.
"""
from __future__ import annotations

import json
import re

from .. import llm as llm_mod
from ..stats import ABNORMAL, NORMAL
from . import definition
from ..layout import D001_LABELS, lines
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


def evidence(site: dict, period: dict) -> dict:
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
    return {
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
    }


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


def _pct(x):
    return f"{abs(x):.1f}% {'above' if x > 0 else 'below'}"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


ADAPTIVE = ("SCATS adapts cycle length and phase service to demand and coordination, so a value outside its "
            "historical range does not by itself show a signal problem.")
MORE_LESS = {"HIGH": ("higher", "longer", "more green"), "LOW": ("lower", "shorter", "less green")}


def findings(ev: dict) -> tuple[str, str]:
    """(what the data show, possible explanations) - the second is labelled as possible, never as a finding."""
    t, s = ev["traffic"], ev["signal"]
    cl, cs, ps = s["cycle_length_s"], s["cycle_stability"], s["phase_service"]
    traffic = {a["approach"]: a["direction"] for a in t["abnormal_approaches"]}
    service = {a["approach"]: a["direction"] for a in ps["abnormal_approaches"]}

    shown = []
    if traffic:
        shown.append("Traffic differs from history on " + _and([f"{k} ({MORE_LESS[d][0]} volume than usual)"
                                                               for k, d in traffic.items()]) + ".")
    signal = []
    if cl["status"] == ABNORMAL:
        signal.append(f"cycle length ({MORE_LESS[cl['direction']][1]} than usual)")
    if cs["status"] == ABNORMAL:
        signal.append("Cycle Stability (poorer than usual)")
    signal += [f"phase service to {k} ({MORE_LESS[d][2]} than usual)" for k, d in service.items()]
    if signal:
        shown.append("Signal operation differs from history in " + _and(signal) + ".")
    if ev["same_approach"]:
        shown.append(f"The traffic and phase-service findings are on the same approach ({_and(ev['same_approach'])}); "
                     "this is an association, not proof that one caused the other.")
    elif service and traffic:
        shown.append("The phase-service finding is on a different approach from the traffic finding.")

    maybe = []
    if cl["status"] == ABNORMAL:
        longer = cl["direction"] == "HIGH"
        matching = [k for k, d in traffic.items() if d == cl["direction"]]
        if matching:
            maybe.append(f"the {'longer' if longer else 'shorter'} cycle with {'higher' if longer else 'lower'} volume "
                         f"on {_and(matching)} may be SCATS {'lengthening' if longer else 'shortening'} the cycle "
                         f"as demand {'rose' if longer else 'fell'}")
        else:
            maybe.append(f"the {'longer' if longer else 'shorter'} cycle is not matched by "
                         f"{'higher' if longer else 'lower'} volume on the screened approaches, so a plan or "
                         "coordination change is a possible explanation")
    for k, d in service.items():
        own = traffic.get(k)
        if own == d:
            # Both readings: SCATS counts the vehicles served at the stop line, so the counted volume also
            # follows the green given (SCATS 774: 16.8% green against a usual 84.1%, volume 16.7% below usual).
            maybe.append(f"{MORE_LESS[d][2]} to {k} with {MORE_LESS[own][0]} volume may be SCATS following its demand, "
                         f"or the counted volume may be {MORE_LESS[own][0]} because of the green given (detectors count "
                         "the vehicles served)")
        elif own:
            maybe.append(f"{MORE_LESS[d][2]} to {k} while its volume is {MORE_LESS[own][0]} is the opposite of a "
                         "demand response, so it is the finding most worth verifying")
        else:
            maybe.append(f"{MORE_LESS[d][2]} to {k} without a volume change on it may follow demand on competing "
                         "phases or the coordination plan")
    if cs["status"] == ABNORMAL:
        maybe.append("poorer stability means the cycle length varied more than usual, which can happen while SCATS "
                     "adapts to changing demand")
    only = ev["traffic_only_approaches"]
    if only:
        maybe.append(f"the volume change on {_and(only)} has no phase-service finding on the same approach, so its "
                     "cause is not shown by the SCATS data")
    explained = (ADAPTIVE + " " + "; ".join(m[0].upper() + m[1:] for m in maybe[:1]) + "".join("; " + m for m in maybe[1:])
                 + ".") if maybe else ADAPTIVE
    return " ".join(shown), explained


def written(ev: dict) -> dict:
    """The code-written answer: diagnosis (what the data show, then possible explanations), supporting evidence
    (the measurements behind the findings) and checks (in order of priority), from the evidence alone."""
    t, s = ev["traffic"], ev["signal"]
    cl, cs, ps = s["cycle_length_s"], s["cycle_stability"], s["phase_service"]
    shown, explained = findings(ev)
    diagnosis = f"{D001_LABELS[0]} {shown}\n{D001_LABELS[1]} {explained}"

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
    for a in ps["abnormal_approaches"]:
        lo, hi = a["normal_range"]
        side = "below" if a["direction"] == "LOW" else "above"
        support.append(f"Phase service {a['approach']}: green share {a['current_green_share_pct']:.1f}% against a usual "
                       f"{a['usual_green_share_pct']:.1f}% (normal range {lo:.1f}-{hi:.1f}%) - {side} its normal range.")

    traffic = {a["approach"]: a["direction"] for a in t["abnormal_approaches"]}
    service = {a["approach"]: a["direction"] for a in ps["abnormal_approaches"]}
    checks = []
    # 1. a phase-service change on an approach whose traffic moved the other way, then the same approach otherwise
    same = sorted(ev["same_approach"], key=lambda k: service.get(k) == traffic.get(k))
    for label in same:
        checks.append(f"Verify phase service on {label} against its demand: compare its green time and phase calls "
                      "cycle by cycle with the detector counts for the period.")
    # 2. cycle length: adaptive response or plan / coordination
    if cl["status"] == ABNORMAL:
        checks.append(f"Verify whether the {MORE_LESS[cl['direction']][1]} cycle was SCATS's adaptive response or a "
                      "plan or coordination change: check the plan, the subsystem cycle length and the coordination "
                      "(linking and offsets) in force for the period.")
    # 3. phase service on approaches without a traffic finding
    for label in ev["signal_only_approaches"]:
        checks.append(f"Check phase service to {label}: phase calls, skipped or extended phases, and demand on the "
                      "competing phases.")
    # 4. stability
    if cs["status"] == ABNORMAL:
        checks.append("Review cycle-by-cycle cycle lengths in Signal Performance for the period to confirm the poorer "
                      "stability and whether it follows changing demand.")
    # 5. traffic without a signal finding on the same approach
    for label in ev["traffic_only_approaches"]:
        checks.append(f"Check for incidents, events, roadworks or diversions that could explain the unusual volume on "
                      f"{label}, and monitor whether it persists.")
    return {"diagnosis": diagnosis, "supporting_evidence": support, "suggested_checks": checks}


SYSTEM = """You write the SCATS diagnostic interpretation for one intersection flagged Red by deterministic screening.
Use only the evidence JSON and the draft answer. Rules:
- diagnosis: two lines, starting exactly with "What the data show:" and "Possible explanations (not demonstrated by
  these data):" as in the draft. First what the data show (the main problem and the approaches concerned), then possible explanations,
  clearly worded as possible ("may", "possible explanation"), never as findings. SCATS adapts cycle length and phase
  service to demand and coordination, so an abnormal value does not by itself show a signal problem: say so, and keep the draft's
  reading of each combination (e.g. a longer cycle with higher volume may be an adaptive response). Keep it short;
  leave the figures to the supporting evidence.
- supporting_evidence: the measurements only (current, usual, normal range, difference), no interpretation.
- suggested_checks: actions in order of priority, keeping the draft's order; they verify signal behaviour, phase
  service and coordination. Conservative verbs only (review, investigate, verify, check, monitor).
- Report every abnormal approach and say which measure is unusual. Do not assume the traffic approach is the
  phase-service approach; connect findings only when the approach is the same.
- An abnormal signal measure is an association, not proof that SCATS caused the traffic change. Never use the words
  fault, faulty or malfunction (the answer is rejected).
- Do not reclassify the site, invent or recalculate figures, add causes that are not in the draft, mention databases
  or queries, or propose signal-timing changes.
- Every number you write must appear in the evidence or in the draft answer.
- Name every abnormal approach exactly as written in the evidence (e.g. "Swanston Street [N]").
- For cycle length and cycle stability, state the position given in the evidence ("position"); never call a value
  within its normal range unless the position says so. If "why_normal" is given, use it to explain a normal status.
- Write plain English: do not copy field names or codes such as HIGH, LOW, POORER, abnormal_high or Q3C; say
  "above its normal range", "below its normal range", "poorer than usual".
Return JSON with keys: diagnosis (string), supporting_evidence (list of strings), suggested_checks (list of strings)."""


def run(site: dict, period: dict, llm=None) -> dict:
    spec = definition(TEMPLATE)
    ev = evidence(site, period)
    draft = written(ev)
    user = json.dumps({"question": spec["question"], "evidence": ev, "draft_answer": draft}, ensure_ascii=False)
    named = [a["approach"] for a in ev["traffic"]["abnormal_approaches"] + ev["signal"]["phase_service"]["abnormal_approaches"]]
    worded = llm_mod.word(llm, SYSTEM, user, ["diagnosis", "supporting_evidence", "suggested_checks"], ev, draft,
                          required={"diagnosis": named + D001_LABELS, "supporting_evidence": named},
                          validate=lambda answer: contradictions(answer, ev))
    worded["answer"]["diagnosis"] = lines(worded["answer"]["diagnosis"], D001_LABELS)
    return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"],
            "evidence": ev, **worded}
