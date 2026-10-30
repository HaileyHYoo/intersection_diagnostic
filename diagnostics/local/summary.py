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
    examples = {"single detector": [], "every failed detector 0": []}
    for s in dh:
        failed = [d for d in s["q2"]["detectors"] if d["status"] == "FAIL"]
        failed_n[len(failed)] += 1
        failed_counts.update(_bucket(d["count_60min"], [0, 1, 5, 10]) for d in failed)
        zero = all(d["count_60min"] == 0 for d in failed)
        all_zero += zero
        one_detector += len(failed) == 1
        if len(failed) == 1:
            examples["single detector"].append(s["site"])
        if zero:
            examples["every failed detector 0"].append(s["site"])
    q2_rows = [d for s in sites for d in s["q2"]["detectors"]]
    out["q2_records"] = {"detectors": len(q2_rows),
                         "passed_with_records_missing": sum(1 for d in q2_rows if d["status"] == "PASS"
                                                            and d.get("records", 0) < (d.get("expected_records") or 0)),
                         "detectors_with_negative_records": sum(1 for d in q2_rows if d.get("negative_records")),
                         "of_which_grey_or_insufficient": sum(1 for d in q2_rows if d.get("negative_records")
                                                              and d["status"] == INSUFFICIENT)}
    out["detector_health"] = {"sites": len(dh), "failed_detectors_per_site": dict(sorted(failed_n.items())),
                              "failed_detector_counts_60min": dict(failed_counts),
                              "sites_where_every_failed_detector_counted_0": all_zero,
                              "sites_failing_on_a_single_detector": one_detector,
                              "examples": {k: v[:5] for k, v in examples.items()}}

    # Grey
    grey = [s for s in sites if s["category"] == "grey"]
    causes, q1_detail, q3_detail, cause_examples = Counter(), Counter(), Counter(), {}
    missing_share = Counter()

    def cause(name, site):
        causes[name] += 1
        cause_examples.setdefault(name, []).append(site)

    for s in grey:
        q2 = s["q2"]
        if q2["status"] == INSUFFICIENT:
            if not q2["detectors"]:
                cause("Q2: no active detector in Neo4j", s["site"])
            elif len(q2["missing"]) == len(q2["detectors"]):
                cause("Q2: no detector records at all", s["site"])
            else:
                cause("Q2: some detectors missing records", s["site"])
                missing_share[f"{len(q2['missing'])} of {len(q2['detectors'])}"] += 1
            continue
        ps = s["q3"]["components"]["phase_service"]
        if ps["grey_site"]:
            cause("Q3C: approach without green", s["site"])
        if s["q1"]["status"] == INSUFFICIENT:
            cause("Q1: insufficient", s["site"])
            for a in s["q1"]["approaches"]:
                if a["status"] == INSUFFICIENT:
                    q1_detail["no current volume" if a["current"] is None else "fewer than 5 historical values"] += 1
            if not s["q1"]["approaches"]:
                q1_detail["no approach with volume history"] += 1
        if s["q3"]["status"] == INSUFFICIENT:
            cause("Q3: fewer than two measures assessable", s["site"])
            for name, c in s["q3"]["components"].items():
                if c["status"] == INSUFFICIENT:
                    q3_detail[name] += 1
    out["grey"] = {"sites": len(grey), "causes (a site can have several)": dict(causes.most_common()),
                   "Q2 missing detectors (missing of active)": dict(missing_share.most_common(8)),
                   "Q1 approaches not assessable": dict(q1_detail), "Q3 measures not assessable": dict(q3_detail),
                   "examples": {k: v[:5] for k, v in cause_examples.items()}}

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
    # Why Q3C (phase service) could not be assessed, per site and per approach
    q3c_site, q3c_history, q3c_examples = Counter(), Counter(), {}
    for s in assessed:
        ps = s["q3"]["components"]["phase_service"]
        if ps["status"] != INSUFFICIENT:
            continue
        rows = ps["approaches"]
        if not rows:
            key = "no approach has phase-service history"
        elif ps["without_green"]:
            key = "an approach without green now"
        elif any(a["current"] is None for a in rows):
            key = "an approach without a current value"
        else:
            key = "an approach with fewer than 5 historical values"
            q3c_history.update(f"{a['n_history']} values" for a in rows if a["status"] == INSUFFICIENT)
        q3c_site[key] += 1
        q3c_examples.setdefault(key, []).append(s["site"])
    could_change = [s for s in assessed if s["q3"].get("missing_measure_could_change")]
    recorded = any("missing_measure_could_change" in s["q3"] for s in assessed)
    out["signal"] = {"sites_assessed": len(assessed), "component_status": {k: dict(v) for k, v in comp.items()},
                     "q3_normal_that_the_missing_measure_could_change": len(could_change) if recorded else
                     "not recorded in this run (screened before the check existed): run `python main.py screen` again",
                     "of_which_category": dict(Counter(s["category"] for s in could_change)),
                     "examples_q3_normal_could_change": [s["site"] for s in could_change][:5],
                     "phase_service_approaches_with_zero_width_range": zero_width,
                     "phase_service_not_assessable_why": dict(q3c_site.most_common()),
                     "phase_service_history_of_short_approaches": dict(sorted(q3c_history.items())),
                     "phase_service_examples": {k: v[:5] for k, v in q3c_examples.items()}}
    return out


def text(summary: dict) -> str:
    lines = [f"Run {summary['run']}  {summary['period']}  sites {summary['sites']}  errors {summary['errors']}",
             "  categories: " + ", ".join(f"{k} {v}" for k, v in summary["categories"].items())]
    for key in ("q2_records", "detector_health", "grey", "traffic_abnormal", "signal"):
        lines.append(f"  {key}:")
        for k, v in summary[key].items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def save(summary: dict, out_dir: str = "out") -> Path:
    path = Path(out_dir) / f"summary_{summary['run']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
