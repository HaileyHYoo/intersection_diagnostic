"""Why sites got their category: counts over a stored screening run.

    python main.py summary                 the latest complete run
    python main.py summary --run <run_id>

Groups the reasons behind Detector Health Issue and Grey, and describes the flagged approaches behind Amber
and Red, so the thresholds can be discussed with numbers. Reads the store only.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..stats import ABNORMAL, INSUFFICIENT


def _bucket(x, edges, unit=""):
    if x is None:
        return "unknown"
    for lo, hi in zip(edges, edges[1:]):
        if lo <= x < hi:
            return f"{lo}-{hi}{unit}"
    return f">={edges[-1]}{unit}"


def summarise(payload: dict) -> dict:
    sites = payload["sites"]
    by_cat = Counter(s["category"] for s in sites)
    out = {"run": payload.get("run_id"), "period": payload["period"]["local"], "sites": len(sites),
           "categories": dict(by_cat), "errors": len(payload.get("errors", {}))}

    # Detector Health Issue
    dh = [s for s in sites if s["category"] == "detector_health"]
    failed_n, failed_counts, all_zero, one_detector = Counter(), Counter(), 0, 0
    for s in dh:
        failed = [d for d in s["q2"]["detectors"] if d["status"] == "FAIL"]
        failed_n[len(failed)] += 1
        failed_counts.update(_bucket(d["count_60min"], [0, 1, 5, 10]) for d in failed)
        all_zero += all(d["count_60min"] == 0 for d in failed)
        one_detector += len(failed) == 1
    out["detector_health"] = {"sites": len(dh), "failed_detectors_per_site": dict(sorted(failed_n.items())),
                              "failed_detector_counts_60min": dict(failed_counts),
                              "sites_where_every_failed_detector_counted_0": all_zero,
                              "sites_failing_on_a_single_detector": one_detector}

    # Grey
    grey = [s for s in sites if s["category"] == "grey"]
    causes, q1_detail, q3_detail = Counter(), Counter(), Counter()
    for s in grey:
        q2 = s["q2"]
        if q2["status"] == INSUFFICIENT:
            if not q2["detectors"]:
                causes["Q2: no active detector in Neo4j"] += 1
            elif len(q2["missing"]) == len(q2["detectors"]):
                causes["Q2: no detector records at all"] += 1
            else:
                causes["Q2: some detectors missing records"] += 1
            continue
        ps = s["q3"]["components"]["phase_service"]
        if ps["grey_site"]:
            causes["Q3C: approach without green"] += 1
        if s["q1"]["status"] == INSUFFICIENT:
            causes["Q1: insufficient"] += 1
            for a in s["q1"]["approaches"]:
                if a["status"] == INSUFFICIENT:
                    q1_detail["no current volume" if a["current"] is None else "fewer than 5 historical values"] += 1
            if not s["q1"]["approaches"]:
                q1_detail["no approach with volume history"] += 1
        if s["q3"]["status"] == INSUFFICIENT:
            causes["Q3: fewer than two measures assessable"] += 1
            for name, c in s["q3"]["components"].items():
                if c["status"] == INSUFFICIENT:
                    q3_detail[name] += 1
    out["grey"] = {"sites": len(grey), "causes (a site can have several)": dict(causes.most_common()),
                   "Q1 approaches not assessable": dict(q1_detail), "Q3 measures not assessable": dict(q3_detail)}

    # Amber traffic and Red: the flagged approaches
    flagged_sites = [s for s in sites if s["category"] in ("amber_traffic", "red")]
    per_site, pct, usual, direction = Counter(), Counter(), Counter(), Counter()
    for s in flagged_sites:
        rows = [a for a in s["q1"]["approaches"] if a["status"] == ABNORMAL]
        per_site[len(rows)] += 1
        for a in rows:
            pct[_bucket(abs(a["pct_difference"]) if a["pct_difference"] is not None else None, [10, 20, 30, 50, 100], "%")] += 1
            usual[_bucket(a["usual"], [0, 20, 50, 100, 200], " veh")] += 1
            direction[a["direction"]] += 1
    out["traffic_abnormal"] = {"sites": len(flagged_sites), "flagged_approaches_per_site": dict(sorted(per_site.items())),
                               "abs_pct_difference": dict(pct), "usual_30min_volume": dict(usual), "direction": dict(direction)}

    # Q3 components where Q2 passed
    assessed = [s for s in sites if s.get("q3")]
    comp = {name: Counter(s["q3"]["components"][name]["status"] for s in assessed)
            for name in ("cycle_length", "cycle_stability", "phase_service")}
    zero_width = sum(1 for s in assessed for a in s["q3"]["components"]["phase_service"]["approaches"]
                     if a.get("p_low") is not None and a["p_low"] == a["p_high"])
    out["signal"] = {"sites_assessed": len(assessed), "component_status": {k: dict(v) for k, v in comp.items()},
                     "phase_service_approaches_with_zero_width_range": zero_width}
    return out


def text(summary: dict) -> str:
    lines = [f"Run {summary['run']}  {summary['period']}  sites {summary['sites']}  errors {summary['errors']}",
             "  categories: " + ", ".join(f"{k} {v}" for k, v in summary["categories"].items())]
    for key in ("detector_health", "grey", "traffic_abnormal", "signal"):
        lines.append(f"  {key}:")
        for k, v in summary[key].items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def save(summary: dict, out_dir: str = "out") -> Path:
    path = Path(out_dir) / f"summary_{summary['run']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
