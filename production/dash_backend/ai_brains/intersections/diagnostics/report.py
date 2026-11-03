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
               "columns": ["Approach", "Current", "Usual", "Normal range", "Status"],
               "rows": [[approach_label(a), *_values(a),
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


def assemble(site: dict, period: dict, d001: dict, d002: dict | None, link_speed: dict | None = None) -> dict:
    a1 = d001["answer"]
    sections = [
        {"title": "1. Diagnosis", "text": a1["diagnosis"], "producer": "D001"},
        {"title": "2. Supporting Evidence", "bullets": a1["supporting_evidence"], "tables": evidence_tables(site),
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
        lines += ["| " + " | ".join(r) + " |" for r in t["rows"]]
        lines.append("")
    return lines


def markdown(report: dict) -> str:
    lines = [f"# {report['intersection'] or 'SCATS ' + report['site']} (SCATS {report['site']})",
             f"**{report['classification']}** - {report['period']['local']}", ""]
    for s in report["sections"]:
        lines.append(f"## {s['title']}")
        if s.get("text"):
            lines += [s["text"], ""]
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
