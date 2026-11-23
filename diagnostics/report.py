"""The final diagnostic report for a selected Red site: four fixed sections from D001 and D002.

    1. Diagnosis                    D001
    2. Supporting Evidence          D001 over the saved Q1/Q3 results (with the code-built tables)
    3. TomTom Road-User Impact      D002 over code-calculated TomTom evidence, plus the supplementary TomTom
                                    incoming-link speed (link_speed.py; not part of D002 or its agreement)
    4. Suggested Engineering Checks D001
"""
from __future__ import annotations

from . import link_speed as speed
from .templates.d001 import approach_label, decimals
from .templates.d002 import DEFAULT_NOTE


def _range(row: dict, digits: int = 1) -> str:
    if row.get("p_low") is None and row.get("p_high") is None:
        return "-"
    return f"{_fmt(row.get('p_low'), digits=digits)}-{_fmt(row.get('p_high'), digits=digits)}"


def _fmt(x, unit="", digits: int = 1):
    return "-" if x is None else f"{x:.{digits}f}{unit}"


def _digits(row: dict) -> int:
    return decimals(row)                                # the same rule as the D001 evidence and wording


def _values(row: dict) -> list[str]:
    d = _digits(row)
    if row.get("usual") is None and row.get("report_usual") is not None:
        # not assessed (2-4 weeks): the usual value from those weeks, marked as shown for reference (20 Nov 2026)
        lo, hi = row.get("report_p_low"), row.get("report_p_high")
        return [_fmt(row.get("current"), digits=d), _fmt(row["report_usual"], digits=d) + " (ref.)",
                "-" if lo is None or hi is None else f"{lo:.{d}f}-{hi:.{d}f} (ref.)"]
    return [_fmt(row.get("current"), digits=d), _fmt(row.get("usual"), digits=d), _range(row, d)]


def evidence_tables(site: dict) -> list[dict]:
    q1, q3 = site["q1"], site["q3"]
    # every EGRESS approach is listed, so the table shows which ones were actually assessed (methodology
    # owner, Nov 2026): an approach without volume in the reference weeks is "Not assessed", with the reason
    weeks = lambda r: "-" if r.get("n_history") is None else str(r["n_history"])
    traffic = {"title": "Approach volume (veh/30 min)",
               "columns": ["Approach", "Current", "Usual", "Normal range", "Weeks", "Difference", "Status"],
               "rows": [[approach_label(a), *_values(a), weeks(a), _fmt(a["pct_difference"], "%"),
                         (a["direction"] or a["status"]).title() if a["status"] != "INSUFFICIENT DATA" else
                         ("Not assessed: no current volume" if a.get("current") is None
                          else "Not assessed for the category: fewer than 5 weeks")]
                        for a in q1["approaches"]]
                       + [[approach_label(a), "-", "-", "-", "0", "-", "Not assessed: no volume in any reference week"]
                          for a in q1.get("not_evaluated", [])]}
    comps = q3["components"]
    signal = {"title": "Signal operation", "columns": ["Measure", "Current", "Usual", "Normal range", "Weeks", "Status"],
              "rows": [[name, *_values(c), weeks(c), c["status"].title()]
                       for name, c in (("Cycle length (s)", comps["cycle_length"]),
                                       ("Cycle Stability (score 0-100, higher is more stable)", comps["cycle_stability"]))]}
    service = {"title": "Phase service by approach (green share %: share of the cycle taken by the phases serving "
                        "the approach, from phase durations; not measured signal-group green time)",
               "columns": ["Approach", "Current", "Usual", "Normal range", "Weeks", "Difference (pp)", "Status"],
               "rows": [[approach_label(a), *_values(a), weeks(a),
                         "-" if a.get("current") is None or a.get("usual") is None else f"{round(a['current'], 1) - round(a['usual'], 1):+.1f}",
                         (a["direction"] or a["status"]).title()] for a in comps["phase_service"]["approaches"]]}
    return [traffic, signal, service]


def tomtom_tables(d002: dict) -> list[dict]:
    """Per approach: the value now and its usual value (median of the reference weeks), with the probe vehicles behind
    it (20 Nov 2026: movements pooled by vehicles; stops per vehicle)."""
    rows = d002["evidence"]["approaches"]
    if not rows:
        return []
    queue = d002["evidence"]["queue"] == "available"
    nu = lambda a, m, d=1: (_fmt(a.get(m)) if d == 1 else ("-" if a.get(m) is None else f"{a[m]:.{d}f}")) + (
        "" if (a.get("usual") or {}).get(m) is None else
        f" ({(a['usual'][m]):.{d}f})")
    weeks = lambda a: str((a.get("usual_weeks") or {}).get("control_delay_s") or 0)
    approach = {"title": "TomTom approach performance (same 30 min; usual in brackets)",
                "columns": ["Approach", "Vehicles", "Control delay (s)", "Approach delay (s)", "Stops per vehicle",
                            "Delay minutes (of 30)", "Usual from (weeks)"]
                + (["Mean queue (m)", "Max queue (m)", "Queue minutes (of 30)"] if queue else []),
                "rows": [[a["approach"], str(a.get("vehicles", "-")), nu(a, "control_delay_s"), nu(a, "approach_delay_s"),
                          nu(a, "stops_per_vehicle", 2), str(15 * a["quarters_observed"]), weeks(a)]
                         + ([nu(a, "queue_mean_m"), _fmt(a["queue_max_m"]), str(a["queue_minutes"])] if queue else [])
                         for a in rows]}
    to = lambda m: " ".join(x for x in (m.get("to_street"), f"({m['to_direction'].lower()}bound)" if m.get("to_direction")
                                         else None) if x) or "-"
    moves = {"title": "TomTom movements (same 30 min)", "columns": ["Approach", "Movement", "To", "Vehicles",
                                                                     "Control delay (s)", "Stops per vehicle"],
             "rows": [[a["approach"], m["movement"], to(m), str(m.get("vehicles", "-")), _fmt(m.get("control_delay_s")),
                       "-" if m.get("stops_per_vehicle") is None else f"{m['stops_per_vehicle']:.2f}"]
                      for a in rows for m in a["movements"]]}
    site = d002["evidence"].get("site") or {}
    whole = [[name, "-" if (site.get(f) or {}).get("now") is None else f"{site[f]['now']:.{d}f}",
              "-" if (site.get(f) or {}).get("usual") is None else f"{site[f]['usual']:.{d}f}", str((site.get(f) or {}).get("weeks", 0))]
             for f, name, d in (("control_delay", "Control delay (s)", 1), ("stops", "Stops per vehicle", 2),
                                ("speed", "Speed (km/h)", 1))]
    junction = {"title": "TomTom whole junction (same 30 min)", "columns": ["Measure", "Now", "Usual", "Weeks"],
                "rows": [r for r in whole if r[1] != "-"]}
    return [approach] + ([moves] if moves["rows"] else []) + ([junction] if junction["rows"] else [])


def speed_part(link_speed: dict | None) -> tuple[list[str], list[dict]]:
    if link_speed is None:
        return [], []
    bullets = list(link_speed["notes"])
    bullets.append("Reference speed: " + link_speed["reference"])
    return bullets, [speed.table(link_speed)] if link_speed["approaches"] else []


ABNORMAL_CELLS = {"High", "Low", "Abnormal", "Poorer"}
LABELS = ["What the data show:", *[f"Most likely reading (evidence: {x}):" for x in ("Strong", "Moderate", "Weak")],
          "Other readings:", "Largest values:", "By approach:", "Overall:", "Coverage:"]


def evidence_summary(site: dict) -> tuple[str, list[str]]:
    """Section 2 on screen: one line saying what is outside its range (marked in the tables, which hold every
    measurement), plus the notes the tables cannot show. The full sentences stay in the D001 answer and in the
    contract's supporting_evidence."""
    q1, comps = site["q1"], site["q3"]["components"]
    parts = []
    vol = [a for a in q1["approaches"] if a["status"] == "ABNORMAL"]
    if vol:
        parts.append(f"the volume on {len(vol)} approach{'es' if len(vol) > 1 else ''}")
    for key, name in (("cycle_length", "cycle length"), ("cycle_stability", "Cycle Stability")):
        if comps[key]["status"] == "ABNORMAL":
            parts.append(name)
    ps = [a for a in comps["phase_service"]["approaches"] if a["status"] == "ABNORMAL"]
    if ps:
        parts.append(f"phase service on {len(ps)} approach{'es' if len(ps) > 1 else ''}")
    head = ("Outside the normal range (marked in bold in the tables): " + ", ".join(parts) + "."
            if parts else "No measure is outside its normal range.")
    from .screening import detector_notes
    notes = detector_notes(site["q2"], site["category"])
    for key, name in (("cycle_length", "Cycle length"), ("cycle_stability", "Cycle Stability")):
        c = comps[key]
        if c["status"] == "INSUFFICIENT DATA":
            notes.append(f"{name}: not assessed ({c.get('reason') or 'insufficient data'}).")
        elif c["status"] == "NORMAL" and c.get("current") is not None and c.get("p_low") is not None \
                and not c["p_low"] <= c["current"] <= c["p_high"]:
            why = ("less than 10% from usual, so not flagged" if key == "cycle_length"
                   else "more stable than usual; only poorer stability is flagged")
            notes.append(f"{name} is outside its range but normal: {why}.")
    return head, notes


def assemble(site: dict, period: dict, d001: dict, d002: dict | None, link_speed: dict | None = None,
             reference: str | None = None) -> dict:
    a1 = d001["answer"]
    head, notes = evidence_summary(site)
    if reference:                                   # the reference dates and rule, under the tables' "Weeks" column
        notes = [reference] + notes
    sections = [
        {"title": "1. Diagnosis", "text": a1["diagnosis"], "producer": "D001",
         **({"bullets": ["Note: " + d001["method_note"]]} if d001.get("method_note") else {})},
        {"title": "2. Supporting Evidence", "text": head, "bullets": notes, "tables": evidence_tables(site),
         "producer": "D001"},
    ]
    speed_bullets, speed_tables = speed_part(link_speed)
    # Junction Analytics (delay, queue) and the supplementary link speed are separate TomTom sources: the second
    # never stands in for the first, and an unavailable confirmation keeps the methodology's fixed message.
    supplement = {"title": "Supplementary: TomTom incoming-link speed (a separate TomTom source; not Junction "
                           "Analytics, not used for the classification or the agreement)",
                  "bullets": speed_bullets, "tables": speed_tables} if link_speed is not None else None
    if d002 is None:
        section = {"title": "3. TomTom Road-User Impact", "text": "TomTom confirmation was not run.",
                   "bullets": ["Junction Analytics delay and queue: not run."], "tables": []}
    elif not d002["evidence"]["available"]:
        section = {"title": "3. TomTom Road-User Impact", "text": d002["answer"]["road_user_impact"],
                   "bullets": ["Junction Analytics delay and queue: unavailable"
                               + (f" ({d002['answer']['coverage']})" if d002["answer"].get("coverage") else "") + "."],
                   "tables": []}
    else:
        a2 = d002["answer"]
        section = {"title": "3. TomTom Road-User Impact", "text": a2["road_user_impact"],
                   # the verdict and the coverage statement are in the text; only extra coverage notes are listed
                   "bullets": [] if d002["evidence"]["coverage_note"] == DEFAULT_NOTE else
                              ["Coverage notes: " + d002["evidence"]["coverage_note"]],
                   "tables": tomtom_tables(d002)}
    sections.append({**section, "producer": "D002", **({"supplement": supplement} if supplement else {})})
    sections.append({"title": "4. Suggested Engineering Checks", "bullets": a1["suggested_checks"], "ordered": True,
                     "producer": "D001"})                 # in order of priority
    report = {"site": site["site"], "intersection": site.get("name"), "classification": site["label"],
              "period": period, "sections": sections,
              "generated_by": {"D001": d001["generated_by"], "D002": d002["generated_by"] if d002 else None}}
    report["markdown"] = markdown(report)
    return report


def _tables(tables: list[dict]) -> list[str]:
    lines = []
    for t in tables:
        lines += [f"**{t['title']}**", "", "| " + " | ".join(t["columns"]) + " |", "|" + "---|" * len(t["columns"])]
        for r in t["rows"]:
            mark = any(c in ABNORMAL_CELLS for c in r)          # rows outside their range in bold
            lines.append("| " + " | ".join(f"**{c}**" if mark and c not in ("-", "") else c for c in r) + " |")
        lines.append("")
    return lines


def _text(text: str) -> list[str]:
    """Each labelled line as its own paragraph, with the label in bold."""
    out = []
    for line in str(text).split("\n"):
        for label in LABELS:
            if line.startswith(label):
                line = f"**{label}**{line[len(label):]}"
                break
        out += [line, ""]
    return out


def markdown(report: dict) -> str:
    lines = [f"# {report['intersection'] or 'SCATS ' + report['site']} (SCATS {report['site']})",
             f"**{report['classification']}** - {report['period']['local']}", ""]
    for s in report["sections"]:
        lines.append(f"## {s['title']}")
        if s.get("text"):
            lines += _text(s["text"])
        for k, b in enumerate(s.get("bullets", []), 1):
            lines.append(f"{k}. {b}" if s.get("ordered") else f"- {b}")
        if s.get("bullets"):
            lines.append("")
        lines += _tables(s.get("tables", []))
        if s.get("supplement"):
            sup = s["supplement"]
            lines += [f"### {sup['title']}", ""] + [f"- {b}" for b in sup["bullets"]] + [""] + _tables(sup["tables"])
    lines.append("_Classification by deterministic screening; wording by "
                 + ", ".join(f"{k}: {v}" for k, v in report["generated_by"].items() if v) + "._")
    return "\n".join(lines)
