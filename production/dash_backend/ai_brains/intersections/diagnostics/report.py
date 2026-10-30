"""The final diagnostic report for a selected Red site: four fixed sections from D001 and D002.

    1. Diagnosis                    D001
    2. Supporting Evidence          D001 over the saved Q1/Q3 results (with the code-built tables)
    3. TomTom Road-User Impact      D002 over code-calculated TomTom evidence
    4. Suggested Engineering Checks D001
"""
from __future__ import annotations

from .templates.d001 import approach_label


def _fmt(x, unit=""):
    return "-" if x is None else f"{x:.1f}{unit}"


def evidence_tables(site: dict) -> list[dict]:
    q1, q3 = site["q1"], site["q3"]
    traffic = {"title": "Approach volume (30 min)",
               "columns": ["Approach", "Current", "Usual", "Normal range", "Difference", "Status"],
               "rows": [[approach_label(a), _fmt(a["current"]), _fmt(a["usual"]), f"{_fmt(a['p_low'])}-{_fmt(a['p_high'])}",
                         _fmt(a["pct_difference"], "%"), (a["direction"] or a["status"]).title()]
                        for a in q1["approaches"]]}
    comps = q3["components"]
    signal = {"title": "Signal operation", "columns": ["Measure", "Current", "Usual", "Normal range", "Status"],
              "rows": [[name, _fmt(c["current"]), _fmt(c["usual"]), f"{_fmt(c['p_low'])}-{_fmt(c['p_high'])}", c["status"].title()]
                       for name, c in (("Cycle length (s)", comps["cycle_length"]), ("Cycle Stability", comps["cycle_stability"]))]}
    service = {"title": "Phase service by approach (green share %)",
               "columns": ["Approach", "Current", "Usual", "Normal range", "Status"],
               "rows": [[approach_label(a), _fmt(a["current"]), _fmt(a["usual"]), f"{_fmt(a['p_low'])}-{_fmt(a['p_high'])}",
                         (a["direction"] or a["status"]).title()] for a in comps["phase_service"]["approaches"]]}
    return [traffic, signal, service]


def tomtom_tables(d002: dict) -> list[dict]:
    rows = d002["evidence"]["approaches"]
    if not rows:
        return []
    queue = d002["evidence"]["queue"] == "available"
    approach = {"title": "TomTom approach performance (same 30 min)",
                "columns": ["Approach", "Approach delay (s)", "Control delay (s)", "Multi-stop rate", "Quarter-hours"]
                + (["Mean queue (m)", "Max queue (m)", "Queue minutes"] if queue else []),
                "rows": [[a["approach"], _fmt(a["approach_delay_s"]), _fmt(a["control_delay_s"]),
                          "-" if a["multi_stop_rate"] is None else f"{a['multi_stop_rate']:.3f}", str(a["quarters_observed"])]
                         + ([_fmt(a["queue_mean_m"]), _fmt(a["queue_max_m"]), str(a["queue_minutes"])] if queue else [])
                         for a in rows]}
    moves = {"title": "TomTom movements (control delay, s)", "columns": ["Approach", "Movement", "Control delay (s)"],
             "rows": [[a["approach"], m["movement"], _fmt(m.get("control_delay_s"))] for a in rows for m in a["movements"]]}
    return [approach] + ([moves] if moves["rows"] else [])


def assemble(site: dict, period: dict, d001: dict, d002: dict | None) -> dict:
    a1 = d001["answer"]
    sections = [
        {"title": "1. Diagnosis", "text": a1["diagnosis"], "producer": "D001"},
        {"title": "2. Supporting Evidence", "bullets": a1["supporting_evidence"], "tables": evidence_tables(site),
         "producer": "D001"},
    ]
    if d002 is None:
        sections.append({"title": "3. TomTom Road-User Impact", "text": "TomTom confirmation was not run.", "producer": "D002"})
    else:
        a2 = d002["answer"]
        sections.append({"title": "3. TomTom Road-User Impact", "text": a2["road_user_impact"],
                         "bullets": [f"Agreement with SCATS findings: {a2['agreement']}", f"Coverage: {a2['coverage']}"],
                         "tables": tomtom_tables(d002), "producer": "D002"})
    sections.append({"title": "4. Suggested Engineering Checks", "bullets": a1["suggested_checks"], "producer": "D001"})
    report = {"site": site["site"], "intersection": site.get("name"), "classification": site["label"],
              "period": period, "sections": sections,
              "generated_by": {"D001": d001["generated_by"], "D002": d002["generated_by"] if d002 else None}}
    report["markdown"] = markdown(report)
    return report


def markdown(report: dict) -> str:
    lines = [f"# {report['intersection'] or 'SCATS ' + report['site']} (SCATS {report['site']})",
             f"**{report['classification']}** - {report['period']['local']}", ""]
    for s in report["sections"]:
        lines.append(f"## {s['title']}")
        if s.get("text"):
            lines += [s["text"], ""]
        for b in s.get("bullets", []):
            lines.append(f"- {b}")
        if s.get("bullets"):
            lines.append("")
        for t in s.get("tables", []):
            lines += [f"**{t['title']}**", "", "| " + " | ".join(t["columns"]) + " |",
                      "|" + "---|" * len(t["columns"])]
            lines += ["| " + " | ".join(r) + " |" for r in t["rows"]]
            lines.append("")
    lines.append("_Classification by deterministic screening; wording by "
                 + ", ".join(f"{k}: {v}" for k, v in report["generated_by"].items() if v) + "._")
    return "\n".join(lines)
