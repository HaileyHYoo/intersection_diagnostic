"""D001 (Q4): SCATS diagnostic interpretation of a Red site from its saved Q1/Q3 results.

No data is retrieved. The evidence is the screening run's own record, rounded for reading; the code
writes a complete answer from it, and the LLM (when available) may only re-word that evidence.
"""
from __future__ import annotations

import json

from .. import llm as llm_mod
from ..stats import ABNORMAL
from . import definition

TEMPLATE = "D001"


def r1(x):
    return None if x is None else round(float(x), 1)


def approach_label(row: dict) -> str:
    street, bound = row.get("street"), row.get("bound")
    if street and bound:
        return f"{street} [{bound}]"
    return street or (f"link {row['link']} [{bound}]" if bound else f"link {row['link']}")


def evidence(site: dict, period: dict) -> dict:
    q1, q3 = site["q1"], site["q3"]
    comps = q3["components"]
    traffic = [{"approach": approach_label(a), "link": a["link"], "current_volume": r1(a["current"]),
                "usual_volume": r1(a["usual"]), "normal_range": [r1(a["p_low"]), r1(a["p_high"])],
                "direction": a["direction"], "pct_difference": r1(a["pct_difference"])}
               for a in q1["approaches"] if a["status"] == ABNORMAL]
    service = [{"approach": approach_label(a), "link": a["link"], "current_green_share_pct": r1(a["current"]),
                "usual_green_share_pct": r1(a["usual"]), "normal_range": [r1(a["p_low"]), r1(a["p_high"])],
                "direction": a["direction"]}
               for a in comps["phase_service"]["approaches"] if a["status"] == ABNORMAL]

    def measure(c):
        return {"status": c["status"], "current": r1(c["current"]), "usual": r1(c["usual"]),
                "normal_range": [r1(c["p_low"]), r1(c["p_high"])], "pct_difference": r1(c["pct_difference"]),
                "direction": c["direction"], "reason": c.get("reason")}

    t_links, s_links = {a["link"] for a in traffic}, {a["link"] for a in service}
    labels = {a["link"]: a["approach"] for a in traffic + service}
    return {
        "site": site["site"], "intersection": site.get("name"), "period": period["local"],
        "classification": site["label"],
        "traffic": {"status": q1["status"], "approaches_assessed": len(q1["approaches"]), "abnormal_approaches": traffic},
        "signal": {"status": q3["status"], "abnormal_measures": q3["abnormal_count"],
                   "cycle_length_s": measure(comps["cycle_length"]),
                   "cycle_stability": {**measure(comps["cycle_stability"]),
                                       "meaning": "higher is more stable; only poorer stability is flagged"},
                   "phase_service": {"status": comps["phase_service"]["status"], "abnormal_approaches": service}},
        "same_approach": sorted(labels[k] for k in t_links & s_links),
        "traffic_only_approaches": sorted(labels[k] for k in t_links - s_links),
        "signal_only_approaches": sorted(labels[k] for k in s_links - t_links),
    }


def _pct(x):
    return f"{abs(x):.1f}% {'above' if x > 0 else 'below'}"


def written(ev: dict) -> dict:
    """The code-written answer: diagnosis, supporting evidence and checks from the evidence alone."""
    t, s = ev["traffic"], ev["signal"]
    cl, cs, ps = s["cycle_length_s"], s["cycle_stability"], s["phase_service"]
    parts = []
    for a in t["abnormal_approaches"]:
        parts.append(f"{a['approach']} volume is {_pct(a['pct_difference'])} its usual level and outside its normal range")
    signal = []
    if cl["status"] == ABNORMAL:
        signal.append(f"cycle length is {_pct(cl['pct_difference'])} usual")
    if cs["status"] == ABNORMAL:
        signal.append("Cycle Stability is on the poorer side of its historical range")
    for a in ps["abnormal_approaches"]:
        side = "below its historical 10th percentile" if a["direction"] == "LOW" else "above its historical 90th percentile"
        signal.append(f"phase service to {a['approach']} is {side}")
    diagnosis = ("Traffic: " + ("; ".join(parts) or "no approach is outside its normal range") + ". Signal operation: "
                 + ("; ".join(signal) or "no measure is outside its normal range") + ".")
    if ev["same_approach"]:
        diagnosis += (" The traffic and phase-service findings concern the same approach ("
                      + ", ".join(ev["same_approach"]) + "); this is an association, not proof that the signal caused the traffic change.")
    elif ps["abnormal_approaches"]:
        diagnosis += " The phase-service finding is on a different approach from the traffic finding; they are reported separately."

    support = []
    for a in t["abnormal_approaches"]:
        lo, hi = a["normal_range"]
        support.append(f"{a['approach']}: {a['current_volume']:.0f} veh in 30 min against a usual {a['usual_volume']:.1f} "
                       f"(normal range {lo:.1f}-{hi:.1f}), {_pct(a['pct_difference'])}.")
    for name, m, unit in (("Cycle length", cl, " s"), ("Cycle Stability", cs, "")):
        if m["status"] == ABNORMAL or m["current"] is not None:
            lo, hi = m["normal_range"]
            rng = f" (normal range {lo:.1f}-{hi:.1f}{unit})" if lo is not None else ""
            cur = f"{m['current']:.1f}{unit}" if m["current"] is not None else "not available"
            usual = f"{m['usual']:.1f}{unit}" if m["usual"] is not None else "not available"
            support.append(f"{name}: {cur} against a usual {usual}{rng} - {m['status'].lower()}.")
        else:
            support.append(f"{name}: not assessed ({m.get('reason') or 'insufficient data'}).")
    for a in ps["abnormal_approaches"]:
        lo, hi = a["normal_range"]
        support.append(f"Phase service {a['approach']}: green share {a['current_green_share_pct']:.1f}% against a usual "
                       f"{a['usual_green_share_pct']:.1f}% (normal range {lo:.1f}-{hi:.1f}%) - {a['direction'].lower()}.")

    checks = []
    for label in ev["same_approach"]:
        checks.append(f"Review phase service and the current signal response on {label}; verify observed signal "
                      "behaviour before considering any operational adjustment.")
    for label in ev["traffic_only_approaches"]:
        checks.append(f"Verify the unusual volume on {label} (incidents, events, roadworks or diversions nearby) "
                      "and monitor whether it persists.")
    for label in ev["signal_only_approaches"]:
        checks.append(f"Check why phase service to {label} differs from its usual level (plan selection, "
                      "demand on competing phases).")
    if cl["status"] == ABNORMAL:
        checks.append("Check the signal plan and coordination in force for the period to explain the cycle length.")
    if cs["status"] == ABNORMAL:
        checks.append("Review cycle-by-cycle behaviour in Signal Performance for the period to confirm the poorer stability.")
    return {"diagnosis": diagnosis, "supporting_evidence": support, "suggested_checks": checks}


SYSTEM = """You write the SCATS diagnostic interpretation for one intersection flagged Red by deterministic screening.
Use only the evidence JSON. Rules:
- Report every abnormal approach and say which measure is unusual.
- Do not assume the traffic approach is the phase-service approach; connect findings only when the approach is the same.
- An abnormal signal measure is an association, not proof that SCATS caused the traffic change.
- Do not reclassify the site, invent or recalculate figures, mention databases or queries, or propose signal-timing changes.
- Suggested checks must be conservative (review, investigate, verify, check, monitor) and tied to the evidence.
- Every number you write must appear in the evidence or in the draft answer.
Return JSON with keys: diagnosis (string), supporting_evidence (list of strings), suggested_checks (list of strings)."""


def run(site: dict, period: dict, llm=None) -> dict:
    spec = definition(TEMPLATE)
    ev = evidence(site, period)
    draft = written(ev)
    user = json.dumps({"question": spec["question"], "evidence": ev, "draft_answer": draft}, ensure_ascii=False)
    worded = llm_mod.word(llm, SYSTEM, user, ["diagnosis", "supporting_evidence", "suggested_checks"], ev, draft)
    return {"template_id": TEMPLATE, "template_version": spec["version"], "question": spec["question"],
            "evidence": ev, **worded}
