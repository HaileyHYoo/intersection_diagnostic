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

from ..stats import ABNORMAL, INSUFFICIENT, NORMAL


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
    # Why Q3A / Q3B could not be assessed: no current value (data not in yet?) or too little history
    kpi_why = {name: Counter(s["q3"]["components"][name].get("reason") for s in assessed
                             if s["q3"]["components"][name]["status"] == INSUFFICIENT)
               for name in ("cycle_length", "cycle_stability")}
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
                     "cycle_not_assessable_why": {k: dict(v.most_common()) for k, v in kpi_why.items()},
                     "phase_service_approaches_with_zero_width_range": zero_width,
                     "phase_service_not_assessable_why": dict(q3c_site.most_common()),
                     "phase_service_history_of_short_approaches": dict(sorted(q3c_history.items())),
                     "phase_service_examples": {k: v[:5] for k, v in q3c_examples.items()}}
    out["review"] = review(sites)
    return out


# ---------------------------------------------------------------------- review (methodology owner, 3 Nov 2026)
LARGE_CHANGE_PP = 30          # Q3C: a current green share this many percentage points from the usual value
NEAR = 0.02                   # Q3A/Q3B: within 2% of the range bound it was compared with


def _q3_status(statuses: list[str]) -> str:
    abnormal, assessable = statuses.count(ABNORMAL), sum(x != INSUFFICIENT for x in statuses)
    return ABNORMAL if abnormal >= 2 else NORMAL if assessable >= 2 else INSUFFICIENT


def _q3c_status(rows: list[dict]) -> str:
    if not rows:
        return INSUFFICIENT
    if any(r["status"] == ABNORMAL for r in rows):
        return ABNORMAL
    return INSUFFICIENT if any(r["status"] == INSUFFICIENT for r in rows) else NORMAL


def _category(q1: str, q3: str) -> str:
    if INSUFFICIENT in (q1, q3):
        return "grey"
    return {(True, True): "red", (True, False): "amber_traffic", (False, True): "amber_signal",
            (False, False): "normal"}[(q1 == ABNORMAL, q3 == ABNORMAL)]


def _no_green_as_zero(row: dict) -> str:
    """A recorded HasGreen = 0 read as a measured 0% green share against the approach's range."""
    if row.get("p_low") is None:
        return INSUFFICIENT
    return ABNORMAL if 0 < row["p_low"] else NORMAL


def counterfactual(s: dict) -> dict | None:
    """For a Grey site with an approach without green (Q2 PASS): the category under the two alternatives to the
    current rule. Never used for the screening; for the discussion of q3c.grey_site_if_any_approach_without_green."""
    q3, q1 = s.get("q3"), s.get("q1")
    if not q3 or not q3["components"]["phase_service"]["grey_site"]:
        return None
    comps = q3["components"]
    ab = [comps["cycle_length"]["status"], comps["cycle_stability"]["status"]]
    rows = comps["phase_service"]["approaches"]
    # (a) the no-green approach is left out of Q3C (not assessable), the site is not made Grey for it
    a = _q3c_status([r for r in rows if not r.get("no_green")])
    if any(r.get("no_green") for r in rows) and a == NORMAL:
        a = INSUFFICIENT                                   # an evaluated approach still lacks a value
    # (b) a recorded HasGreen = 0 is a measured zero green; only a missing record stays not assessable
    b_rows = [{**r, "status": _no_green_as_zero(r)} if r.get("no_green") and r.get("recorded_green_share") is not None
              else r for r in rows]
    b = _q3c_status(b_rows)
    return {"q1": q1["status"], "cycle_length": ab[0], "cycle_stability": ab[1],
            "a_no_green_not_assessable": _category(q1["status"], _q3_status(ab + [a])),
            "b_recorded_no_green_as_zero": _category(q1["status"], _q3_status(ab + [b]))}


def review(sites: list[dict]) -> dict:
    """The checks asked for in the methodology owner's review of run eebc0b2964f4 (Fri 30 Oct 2026 15:00)."""
    out = {}

    # 2. Grey: one primary cause per site, the no-green approaches, and what the alternatives would give
    grey = [s for s in sites if s["category"] == "grey"]
    primary, combos, no_green, shares, cf_a, cf_b, cf_examples = (Counter() for _ in range(7))
    only_no_green, examples = [], {}
    for s in grey:
        q2 = s["q2"]
        if q2["status"] == INSUFFICIENT:
            key = ("Q2: no active detector" if not q2["detectors"] else
                   "Q2: no detector records at all" if len(q2["missing"]) == len(q2["detectors"]) else
                   "Q2: some detectors missing records")
            primary[key] += 1
            examples.setdefault(key, []).append(s["site"])
            continue
        ps = s["q3"]["components"]["phase_service"]
        parts = [p for p, on in (("no green", ps["grey_site"]), ("Q1", s["q1"]["status"] == INSUFFICIENT),
                                 ("Q3 <2 measures", s["q3"]["status"] == INSUFFICIENT)) if on]
        key = " + ".join(parts) or "other"
        combos[key] += 1
        examples.setdefault(key, []).append(s["site"])
        for r in ps["approaches"]:
            if not r.get("no_green"):
                continue
            recorded = r.get("recorded_green_share")
            if "recorded_green_share" not in r:
                no_green["not recorded in this run (screen again)"] += 1
            elif r["reason"].startswith("HasGreen"):
                no_green["HasGreen = 0 recorded in both quarter-hours"] += 1
                shares[_bucket(recorded, [0, 0.001, 5, 20, 50, 100.001], "%")] += 1
            else:
                no_green["no GreenShare/HasGreen record (missing data)"] += 1
        if parts == ["no green"]:
            only_no_green.append(s["site"])
        cf = counterfactual(s)
        if cf:
            cf_a[cf["a_no_green_not_assessable"]] += 1
            cf_b[cf["b_recorded_no_green_as_zero"]] += 1
            cf_examples.setdefault(cf["a_no_green_not_assessable"], []).append(s["site"])
    q3ab_ok = [s for s in grey if s["site"] in set(only_no_green)
               and all(s["q3"]["components"][k]["status"] != INSUFFICIENT for k in ("cycle_length", "cycle_stability"))]
    out["grey"] = {
        "sites": len(grey),
        "primary_cause_q2": dict(primary.most_common()),
        "after_q2_pass_cause_combination": dict(combos.most_common()),
        "no_green_approaches": dict(no_green),
        "no_green_recorded_green_share": dict(shares),
        "grey_only_because_of_no_green": len(only_no_green),
        "of_which_q3a_and_q3b_both_assessable": len(q3ab_ok),
        "category_if_no_green_approach_were_not_assessable_instead_of_greying": dict(cf_a.most_common()),
        "category_if_recorded_HasGreen_0_were_a_measured_0pct": dict(cf_b.most_common()),
        "examples": {k: v[:5] for k, v in {**examples, **{f"(a) -> {k}": v for k, v in cf_examples.items()}}.items()}}

    # 3. Detector Health: is the gate excluding sites over one low-volume detector?
    dh = [s for s in sites if s["category"] == "detector_health"]
    kind, shadow, shadow_single, ex = Counter(), Counter(), Counter(), {}
    for s in dh:
        failed = [d for d in s["q2"]["detectors"] if d["status"] == "FAIL"]
        others = [d for d in s["q2"]["detectors"] if d["status"] != "FAIL"]
        if len(failed) == 1:
            c = failed[0]["count_60min"]
            key = ("single detector at 0" if c == 0 else "single detector 1-4 vehicles" if c < 5
                   else "single detector 5-9 vehicles")
            if c > 0 and others and all(d["status"] == "PASS" for d in others):
                shadow_single[s.get("if_detectors_passed", "not recorded (screen again)")] += 1
        elif all(d["count_60min"] == 0 for d in failed):
            key = "several detectors, all at 0"
        else:
            key = "several detectors, some above 0"
        kind[key] += 1
        ex.setdefault(key, []).append(s["site"])
        shadow[s.get("if_detectors_passed", "not recorded (screen again)")] += 1
    out["detector_health"] = {
        "sites": len(dh), "failure_pattern": dict(kind.most_common()),
        "category_if_the_detector_gate_had_passed": dict(shadow.most_common()),
        "same, single detector 1-9 vehicles and every other detector passing": dict(shadow_single.most_common()),
        "examples": {k: v[:5] for k, v in ex.items()}}

    # 4. Q3C green share: 100% values, large changes, zero-width ranges
    assessed = [s for s in sites if s.get("q3")]
    rows = [(s, r) for s in assessed for r in s["q3"]["components"]["phase_service"]["approaches"]
            if r.get("current") is not None]
    full = [(s, r) for s, r in rows if r["current"] >= 99.999]
    large = [(s, r) for s, r in rows if r.get("usual") is not None and abs(r["current"] - r["usual"]) >= LARGE_CHANGE_PP]
    zero_w = [(s, r) for s, r in rows if r.get("p_low") is not None and r["p_low"] == r["p_high"]]
    ex = lambda pairs: [f"{s['site']} {r.get('street') or ''} [{r.get('bound') or '?'}] {r['current']:.1f}% "
                        f"(usual {r['usual']:.1f}%, {r['status']})" for s, r in pairs[:6] if r.get("usual") is not None]
    out["phase_service"] = {
        "approaches_with_a_current_value": len(rows),
        "current_100pct": len(full), "current_100pct_with_usual_100pct": sum(1 for _, r in full if (r.get("usual") or 0) >= 99.999),
        "current_100pct_status": dict(Counter(r["status"] for _, r in full)),
        f"change_from_usual_at_least_{LARGE_CHANGE_PP}pp": len(large),
        "large_change_status": dict(Counter(r["status"] for _, r in large)),
        "zero_width_range": len(zero_w), "zero_width_range_status": dict(Counter(r["status"] for _, r in zero_w)),
        "examples_100pct": ex(full), "examples_large_change": ex(sorted(large, key=lambda x: -abs(x[1]["current"] - x[1]["usual"]))),
        "examples_zero_width": ex(zero_w),
        "check": "python main.py kpi-check --site <n> --end <period end> prints every stored field of "
                 "IntersectionPerfApproach and IntersectionPerfKpi for the period"}

    # 5. Cycle stability and cycle length: zeros and values near the bound they were compared with
    def near(c: dict, bound: str) -> bool:
        b = c.get(bound)
        return c.get("current") is not None and b not in (None, 0) and abs(c["current"] - b) <= NEAR * abs(b)

    stab = [(s, s["q3"]["components"]["cycle_stability"]) for s in assessed]
    cyc = [(s, s["q3"]["components"]["cycle_length"]) for s in assessed]
    zero = [s["site"] for s, c in stab if c.get("current") == 0]
    out["cycle"] = {
        "stability_current_0": len(zero), "stability_current_0_sites": zero[:10],
        "stability_usual_0": sum(1 for _, c in stab if c.get("usual") == 0),
        "stability_within_2pct_of_p10": dict(Counter(c["status"] for _, c in stab if near(c, "p_low"))),
        "stability_within_2pct_of_p10_sites": [s["site"] for s, c in stab if near(c, "p_low")][:10],
        "cycle_length_within_2pct_of_a_bound": dict(Counter(c["status"] for _, c in cyc
                                                            if near(c, "p_low") or near(c, "p_high"))),
        "cycle_length_abnormal_with_10_to_12pct_difference": sum(
            1 for _, c in cyc if c["status"] == ABNORMAL and c.get("pct_difference") is not None
            and abs(c["pct_difference"]) < 12),
        "check": "python main.py kpi-check --site 707 --end <period end> shows CycleCvPct and CycleStability"}
    return out


def text(summary: dict) -> str:
    lines = [f"Run {summary['run']}  {summary['period']}  sites {summary['sites']}  errors {summary['errors']}",
             "  categories: " + ", ".join(f"{k} {v}" for k, v in summary["categories"].items())]
    for key in ("q2_records", "detector_health", "grey", "traffic_abnormal", "signal"):
        lines.append(f"  {key}:")
        for k, v in summary[key].items():
            lines.append(f"    {k}: {v}")
    lines.append("  REVIEW (methodology owner's checks):")
    for part, items in summary.get("review", {}).items():
        lines.append(f"    {part}:")
        for k, v in items.items():
            lines.append(f"      {k}: {v}")
    return "\n".join(lines)


def save(summary: dict, out_dir: str = "out") -> Path:
    path = Path(out_dir) / f"summary_{summary['run']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
