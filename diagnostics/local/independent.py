"""Independent checks: every data condition and every question for every site, without the screening's gates.

    python main.py stats --end 2026-10-30T15:30

The screening is sequential (Q2 first; Q1 and Q3 only after a Q2 PASS; a missing input makes the site Grey). Here
each check is counted on its own over all sites, so "sites without a current KPI value" includes sites that failed
Q2. Nothing is stored and the categories are not changed. Outputs:

    out/stats_<period>.json   counts per check, the overlap of the data checks, the most common combinations
    out/stats_<period>.csv    one row per site, one column per check (for a spreadsheet)

It reads the same data as the screening (one network pass) and the cached baseline.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from .. import screening
from ..stats import ABNORMAL, INSUFFICIENT, NORMAL

# data checks (True = a problem), then results; the order is the column order of the CSV
DATA = {
    "no_active_detector": "No active detector (Neo4j BELONG_TO, active = true)",
    "detector_records_missing": "An active detector below 10 vehicles in 60 min with 5-min records missing (Q2 INSUFFICIENT)",
    "all_detector_records_missing": "Active detectors, but no valid 5-min record at any of them in the 60 min",
    "detector_below_threshold": "An active detector below 10 vehicles in 60 min with all 12 records (Q2 FAIL)",
    "no_egress_link": "No EGRESS road with a link_id in Neo4j",
    "link_without_volume_history": "An EGRESS link with no 30-min volume in any reference week (left out of Q1)",
    "link_without_current_volume": "An evaluated link without volume in both quarter-hours now",
    "link_short_volume_history": "An evaluated link with a volume now but fewer than 5 reference weeks with volume",
    "no_current_cycle_length": "No AvgCycle in both quarter-hours now (IntersectionPerfKpi)",
    "no_current_cycle_stability": "No CycleStability in both quarter-hours now (IntersectionPerfKpi)",
    "short_kpi_history": "Cycle length or stability present now but fewer than 5 reference weeks with a value",
    "no_perf_approach_now": "No IntersectionPerfApproach record for any link now",
    "no_phase_service_history": "No link with a valid green share (HasGreen = 1) in any reference week",
    "approach_hasgreen_0": "An evaluated approach recorded with HasGreen = 0 now (a recorded zero)",
    "approach_no_green_record": "An evaluated approach without a GreenShare/HasGreen record now (missing data)",
    "approach_short_green_history": "An evaluated approach with green now but fewer than 5 reference weeks with green",
    "no_tomtom_mapping": "No approach in the validated TomTom mapping file (Q5 unavailable)",
}
RESULTS = ["q2", "q1", "q3a_cycle_length", "q3b_cycle_stability", "q3c_phase_service", "q3",
           "category_without_q2_gate", "category"]


def _short(reason: str | None) -> bool:
    return bool(reason) and reason.startswith("only ")


def site_checks(s: dict, mapped: set[str]) -> dict:
    ind, q2 = s["independent"], s["q2"]
    q1, q3 = ind["q1"], ind["q3"]
    comps = q3["components"]
    dets = q2["detectors"]
    ps = comps["phase_service"]["approaches"]
    row = {
        "no_active_detector": not dets,
        "detector_records_missing": any(d["status"] == INSUFFICIENT for d in dets),
        "all_detector_records_missing": bool(dets) and all(d.get("records", 0) == 0 for d in dets),
        "detector_below_threshold": any(d["status"] == "FAIL" for d in dets),
        "no_egress_link": ind["links"] == 0,
        "link_without_volume_history": bool(q1["not_evaluated"]),
        "link_without_current_volume": any(a["status"] == INSUFFICIENT and a["current"] is None for a in q1["approaches"]),
        "link_short_volume_history": any(a["status"] == INSUFFICIENT and a["current"] is not None
                                         for a in q1["approaches"]),
        "no_current_cycle_length": comps["cycle_length"]["current"] is None,
        "no_current_cycle_stability": comps["cycle_stability"]["current"] is None,
        "short_kpi_history": any(_short(comps[k].get("reason")) for k in ("cycle_length", "cycle_stability")),
        "no_perf_approach_now": ind["perf_records_now"] == 0,
        "no_phase_service_history": not ps,
        "approach_hasgreen_0": any(a.get("no_green") and str(a.get("reason", "")).startswith("HasGreen") for a in ps),
        "approach_no_green_record": any(a.get("no_green") and not str(a.get("reason", "")).startswith("HasGreen")
                                        for a in ps),
        "approach_short_green_history": any(a["status"] == INSUFFICIENT and not a.get("no_green") for a in ps),
        "no_tomtom_mapping": s["site"] not in mapped,
    }
    as_if = screening.classify({**q2, "status": screening.PASS}, q1, q3)[0]
    row.update({"q2": q2["status"], "q1": q1["status"], "q3a_cycle_length": comps["cycle_length"]["status"],
                "q3b_cycle_stability": comps["cycle_stability"]["status"],
                "q3c_phase_service": comps["phase_service"]["status"], "q3": q3["status"],
                "category_without_q2_gate": as_if, "category": s["category"]})
    return row


def summarise(rows: list[dict], period: str) -> dict:
    n = len(rows)
    data = {k: sum(r[k] for r in rows) for k in DATA}
    results = {k: dict(Counter(r[k] for r in rows).most_common()) for k in RESULTS}
    overlap = {f"{a} & {b}": sum(r[a] and r[b] for r in rows) for a, b in combinations(DATA, 2)
               if sum(r[a] and r[b] for r in rows)}
    combo = Counter(" + ".join(k for k in DATA if r[k]) or "(no data problem)" for r in rows)
    clean = sum(not any(r[k] for k in DATA if k != "no_tomtom_mapping") for r in rows)
    return {"period": period, "sites": n, "definitions": "docs/STATS_DEFINITIONS.md",
            "data_checks": {k: {"sites": v, "share": round(v / n, 3) if n else None, "meaning": DATA[k]}
                            for k, v in data.items()},
            "sites_without_any_screening_data_problem": clean,
            "results_each_question_alone": results,
            "abnormal_each_question_alone": {k: sum(r[k] == ABNORMAL for r in rows)
                                             for k in ("q1", "q3a_cycle_length", "q3b_cycle_stability",
                                                       "q3c_phase_service", "q3")},
            "normal_each_question_alone": {k: sum(r[k] == NORMAL for r in rows)
                                           for k in ("q1", "q3a_cycle_length", "q3b_cycle_stability",
                                                     "q3c_phase_service", "q3")},
            "overlap_of_data_checks (sites with both)": dict(sorted(overlap.items(), key=lambda x: -x[1])),
            "most_common_combinations": dict(combo.most_common(15))}


def run(svc, period_end: str | None) -> tuple[dict, list[dict]]:
    from .. import tomtom_map
    from ..settings import package_file
    period = svc.period(period_end)
    baseline = svc.baselines.get(period)
    result = screening.screen(svc.source, svc.settings, baseline, period, independent=True)
    try:
        mapped = {k for k, m in tomtom_map.load(str(package_file(svc.settings.schema["tomtom_mapping"]["file"]))).items()
                  if m.get("approaches")}
    except Exception:  # noqa: BLE001 - only the TomTom column depends on it
        mapped = set()
    rows = [{"site": s["site"], "name": s.get("name") or "", **site_checks(s, mapped)} for s in result["sites"]]
    return summarise(rows, period.label()), rows


def text(summary: dict) -> str:
    n = summary["sites"]
    lines = [f"Independent checks, {summary['period']}: {n} sites (each check counted on its own, no gates;",
             "definitions: docs/STATS_DEFINITIONS.md)", "",
             "  Data checks (sites with the problem):"]
    for k, v in summary["data_checks"].items():
        lines.append(f"    {v['sites']:>5}  {v['share'] * 100:5.1f}%  {v['meaning']}")
    lines.append(f"    {summary['sites_without_any_screening_data_problem']:>5}         sites without any of these "
                 "problems (TomTom mapping aside)")
    lines += ["", "  Each question on its own (all sites):"]
    for k, v in summary["results_each_question_alone"].items():
        lines.append(f"    {k}: {v}")
    lines += ["", "  Largest overlaps of data checks:"]
    for k, v in list(summary["overlap_of_data_checks (sites with both)"].items())[:12]:
        lines.append(f"    {v:>5}  {k}")
    lines += ["", "  Most common combinations of data problems (each site once):"]
    for k, v in summary["most_common_combinations"].items():
        lines.append(f"    {v:>5}  {k}")
    return "\n".join(lines)


def save(summary: dict, rows: list[dict], out_dir: str, stamp: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    js, cs = out / f"stats_{stamp}.json", out / f"stats_{stamp}.csv"
    js.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with cs.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["site", "name", *DATA, *RESULTS])
        w.writeheader()
        for r in rows:
            w.writerow({k: (int(v) if isinstance(v, bool) else v) for k, v in r.items()})
    return js, cs
