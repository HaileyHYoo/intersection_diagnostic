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
    return [_fmt(row.get("current"), digits=d), _fmt(row.get("usual"), digits=d), _range(row, d)]


def evidence_tables(site: dict) -> list[dict]:
    q1, q3 = site["q1"], site["q3"]
    traffic = {"title": "Approach volume (30 min)",
               "columns": ["Approach", "Current", "Usual", "Normal range", "Difference", "Status"],
               "rows": [[approach_label(a), *_values(a),
                         _fmt(a["pct_difference"], "%"), (a["direction"] or a["status"]).title()]
                        for a in q1["approaches"]]}
    comps = q3["components"]
    signal = {"title": "Signal operation", "columns": ["Measure", "Current", "Usual", "Normal range", "Status"],
              "rows": [[name, *_values(c), c["status"].title()]
                       for name, c in (("Cycle length (s)", comps["cycle_length"]), ("Cycle Stability", comps["cycle_stability"]))]}
    service = {"title": "Phase service by approach (green share %)",
               "columns": ["Approach", "Current", "Usual", "Normal range", "Difference (pp)", "Status"],
               "rows": [[approach_label(a), *_values(a),
                         "-" if a.get("current") is None or a.get("usual") is None else f"{round(a['current'], 1) - round(a['usual'], 1):+.1f}",
                         (a["direction"] or a["status"]).title()] for a in comps["phase_service"]["approaches"]]}
    return [traffic, signal, service]


def tomtom_tables(d002: dict) -> list[dict]:
    rows = d002["evidence"]["approaches"]
    if not rows:
        return []
    queue = d002["evidence"]["queue"] == "available"
    approach = {"title": "TomTom approach performance (same 30 min)",
                "columns": ["Approach", "Approach delay (s)", "Control delay (s)", "Multi-stop rate", "15-min periods observed (of 2)"]
                + (["Mean queue (m)", "Max queue (m)", "Queue minutes"] if queue else []),
                "rows": [[a["approach"], _fmt(a["approach_delay_s"]), _fmt(a["control_delay_s"]),
                          "-" if a["multi_stop_rate"] is None else f"{a['multi_stop_rate']:.3f}", str(a["quarters_observed"])]
                         + ([_fmt(a["queue_mean_m"]), _fmt(a["queue_max_m"]), str(a["queue_minutes"])] if queue else [])
                         for a in rows]}
    to = lambda m: " ".join(x for x in (m.get("to_street"), f"({m['to_direction'].lower()}bound)" if m.get("to_direction")
                                         else None) if x) or "-"
    moves = {"title": "TomTom movements (control delay, s)", "columns": ["Approach", "Movement", "To", "Control delay (s)"],
             "rows": [[a["approach"], m["movement"], to(m), _fmt(m.get("control_delay_s"))]
                      for a in rows for m in a["movements"]]}
    return [approach] + ([moves] if moves["rows"] else [])


def speed_part(link_speed: dict | None) -> tuple[list[str], list[dict]]:
    if link_speed is None:
        return [], []
    bullets = list(link_speed["notes"])
    bullets.append("Reference speed: " + link_speed["reference"])
    return bullets, [speed.table(link_speed)] if link_speed["approaches"] else []


ABNORMAL_CELLS = {"High", "Low", "Abnormal", "Poorer"}
LABELS = ["What the data show:", "Possible explanations (not demonstrated by these data):",
          "Largest values:", "By approach:", "Overall:", "Coverage:"]


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
    notes = []
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


def assemble(site: dict, period: dict, d001: dict, d002: dict | None, link_speed: dict | None = None) -> dict:
    a1 = d001["answer"]
    head, notes = evidence_summary(site)
    sections = [
        {"title": "1. Diagnosis", "text": a1["diagnosis"], "producer": "D001"},
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
