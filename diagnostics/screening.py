"""Level 1 network screening: Q2 detector gate, Q1 traffic, Q3 signal operation, classification.

Deterministic code only; no LLM. Every site gets one category:

    detector_health   Q2 FAIL: an active detector recorded fewer than the minimum in a complete 60 minutes
    grey              insufficient data (Q2 not assessable, Q1 or Q3 INSUFFICIENT DATA, or an evaluated
                      approach without green in the period)
    normal            Q1 NORMAL and Q3 NORMAL
    amber_traffic     Q1 ABNORMAL, Q3 NORMAL
    amber_signal      Q1 NORMAL, Q3 ABNORMAL
    red               Q1 ABNORMAL and Q3 ABNORMAL ("Needs Attention")

Evaluated approaches (Q1 and Q3C) are the site's EGRESS links that had data in the reference weeks
(rules q1/q3c.approach_history_min_presence). If any evaluated approach has no value for the analysis
period, Q1 is INSUFFICIENT DATA and the site is Grey (q1.grey_if_any_approach_missing). If any evaluated
approach has no green in the period (HasGreen = 0 or no GreenShare in either quarter), the site is Grey
(q3c.grey_site_if_any_approach_without_green).
"""
from __future__ import annotations

from collections import defaultdict

from . import stats
from .measures import Measures
from .stats import ABNORMAL, INSUFFICIENT, NORMAL
from .timewin import Period

PASS, FAIL = "PASS", "FAIL"
CATEGORIES = {
    "red": "Red - Needs Attention",
    "amber_traffic": "Amber - Traffic Abnormality",
    "amber_signal": "Amber - Signal-Operation Abnormality",
    "normal": "Normal",
    "grey": "Grey - Insufficient Data",
    "detector_health": "Detector Health Issue",
}


def site_name(streets) -> str | None:
    if not streets:
        return None
    parts = streets if isinstance(streets, list) else str(streets).split("|")
    names = list(dict.fromkeys(p.strip() for p in parts if p and str(p).strip()))
    return " / ".join(sorted(names)) or None


# ---------------------------------------------------------------------- Q2
def q2_gate(detectors: list[dict], totals: dict[int, dict], rules: dict) -> dict:
    """Per active detector, its count over the 60 minutes (a negative 5-minute record is treated as missing):

        at least the minimum                      PASS, even if some 5-minute records are missing
                                                  (the missing ones could only add to it)
        below the minimum, all records present    FAIL
        below the minimum, records missing        INSUFFICIENT DATA (a missing record is not a zero)
    """
    rule = rules["q2"]
    if rule.get("active_detectors_only", True):
        detectors = [d for d in detectors if d["active"]]
    rows = []
    for d in sorted(detectors, key=lambda d: d["detector"]):
        t = totals.get(d["detector"]) or {"total": None, "records": 0, "expected": None, "negatives": 0}
        count = t["total"] if t["records"] else None
        complete = t["records"] and t["records"] == t["expected"]
        if count is not None and count >= rule["min_vehicles"]:
            status = PASS
        elif count is not None and complete:
            status = FAIL
        else:
            status = INSUFFICIENT
        rows.append({"detector": d["detector"], "count_60min": count, "status": status, "records": t["records"],
                     "expected_records": t["expected"], "negative_records": t["negatives"]})
    failed = [r for r in rows if r["status"] == FAIL]
    missing = [r for r in rows if r["status"] == INSUFFICIENT]
    if not rows:
        status, reason = INSUFFICIENT, "no active detector is associated with the intersection"
    elif failed:
        # An observed low count takes precedence over missing records at other detectors.
        status, reason = FAIL, f"{len(failed)} detector(s) below {rule['min_vehicles']} vehicles in 60 minutes"
    elif missing:
        status, reason = INSUFFICIENT, (f"{len(missing)} detector(s) below {rule['min_vehicles']} vehicles with "
                                        "5-minute records missing in the 60 minutes")
    else:
        status, reason = PASS, None
    return {"status": status, "reason": reason, "threshold": rule["min_vehicles"], "detectors": rows,
            "failed": [r["detector"] for r in failed], "missing": [r["detector"] for r in missing]}


# ---------------------------------------------------------------------- Q1
def q1_traffic(links: list[dict], current: dict[str, float], base: dict[str, dict], bounds: dict, rules: dict) -> dict:
    rule = rules["q1"]
    evaluated, skipped = [], []
    for a in links:
        env = base.get(a["link"])
        (evaluated if env and env["n"] >= rule["approach_history_min_presence"] else skipped).append(a)
    rows = []
    for a in evaluated:
        result = stats.two_sided(current.get(a["link"]), base[a["link"]], rule["min_pct_difference"])
        rows.append({"link": a["link"], "street": a.get("street"), "bound": bounds.get(a["link"]), **result})
    missing = [r for r in rows if r["status"] == INSUFFICIENT]
    flagged = [r for r in rows if r["status"] == ABNORMAL]
    if not rows:
        status, reason = INSUFFICIENT, "no approach has volume data in the reference weeks"
    elif missing and rule.get("grey_if_any_approach_missing", True):
        status, reason = INSUFFICIENT, f"{len(missing)} evaluated approach(es) without a complete 30-minute volume or enough history"
    elif flagged:
        status, reason = ABNORMAL, None
    elif len(missing) == len(rows):
        status, reason = INSUFFICIENT, "no evaluated approach could be assessed"
    else:
        status, reason = NORMAL, None
    return {"status": status, "reason": reason, "approaches": rows, "flagged": [r["link"] for r in flagged],
            "missing": [r["link"] for r in missing],
            "not_evaluated": [{"link": a["link"], "street": a.get("street"), "reason": "no volume data in the reference weeks"}
                              for a in skipped]}


# ---------------------------------------------------------------------- Q3
def q3c_phase_service(site_links: list[dict], current: dict[str, dict], base: dict[str, dict], bounds: dict,
                      rules: dict) -> dict:
    rule = rules["q3c"]
    streets = {a["link"]: a.get("street") for a in site_links}
    evaluated = [link for link, env in base.items() if env["n"] >= rule["approach_history_min_presence"]]
    rows, without_green = [], []
    for link in sorted(evaluated):
        now = current.get(link)
        if not now or not now["green"]:
            without_green.append(link)
            reason = "HasGreen = 0 in the period" if now and now["complete"] else "no GreenShare/HasGreen record for both quarters"
            rows.append({"link": link, "street": streets.get(link), "bound": bounds.get(link), "status": INSUFFICIENT,
                         "current": None, "reason": reason, **{k: base[link].get(k) for k in ("usual", "p_low", "p_high")},
                         "n_history": base[link]["n"], "direction": None, "pct_difference": None, "no_green": True})
            continue
        result = stats.range_only(now["green_share"], base[link])
        rows.append({"link": link, "street": streets.get(link), "bound": bounds.get(link), **result, "no_green": False})
    grey_site = bool(without_green) and rule.get("grey_site_if_any_approach_without_green", True)
    flagged = [r for r in rows if r["status"] == ABNORMAL]
    insufficient = [r for r in rows if r["status"] == INSUFFICIENT]
    if not rows:
        status, reason = INSUFFICIENT, "no approach has phase-service history"
    elif insufficient:
        status, reason = INSUFFICIENT, f"{len(insufficient)} approach(es) without a current value or enough history"
    elif flagged:
        status, reason = ABNORMAL, None
    else:
        status, reason = NORMAL, None
    return {"status": status, "reason": reason, "approaches": rows, "flagged": [r["link"] for r in flagged],
            "without_green": without_green, "grey_site": grey_site}


def q3_signal(kpi_now: dict, kpi_base: dict, origin: dict, q3c: dict, rules: dict) -> dict:
    cycle = stats.two_sided(kpi_now.get("cycle_length"), kpi_base.get("cycle_length", {"n": 0}),
                            rules["q3a"]["min_pct_difference"])
    cycle["origin"] = origin.get("cycle_length")
    stability = stats.poorer_only(kpi_now.get("cycle_stability"), kpi_base.get("cycle_stability", {"n": 0}),
                                  rules["q3b"]["higher_is_more_stable"])
    components = {"cycle_length": cycle, "cycle_stability": stability, "phase_service": q3c}
    statuses = [c["status"] for c in components.values()]
    abnormal = statuses.count(ABNORMAL)
    assessable = sum(s != INSUFFICIENT for s in statuses)
    rule = rules["q3"]
    # Methodology 9: NORMAL whenever two measures are assessable and fewer than two are abnormal. With one
    # abnormal and one not assessable, the missing measure could have made it ABNORMAL; that case is flagged,
    # and withheld as INSUFFICIENT DATA only if q3.undetermined_if_missing_could_change is switched on.
    could_change = abnormal < rule["abnormal_required"] <= abnormal + (len(statuses) - assessable)
    if abnormal >= rule["abnormal_required"]:
        status = ABNORMAL
    elif assessable >= rule["assessable_required"] and not (could_change and rule.get("undetermined_if_missing_could_change")):
        status = NORMAL
    else:
        status = INSUFFICIENT
    return {"status": status, "abnormal_count": abnormal, "assessable_count": assessable,
            "missing_measure_could_change": could_change and status == NORMAL, "components": components}


# ---------------------------------------------------------------------- classification
def classify(q2: dict, q1: dict | None, q3: dict | None) -> tuple[str, list[str]]:
    if q2["status"] == FAIL:
        return "detector_health", [q2["reason"]]
    if q2["status"] == INSUFFICIENT:
        return "grey", ["Q2 cannot be assessed: " + q2["reason"]]
    reasons = []
    if q3["components"]["phase_service"]["grey_site"]:
        n = len(q3["components"]["phase_service"]["without_green"])
        reasons.append(f"{n} evaluated approach(es) without green in the period")
    if q1["status"] == INSUFFICIENT:
        reasons.append("Q1: " + q1["reason"])
    if q3["status"] == INSUFFICIENT:
        reasons.append("Q3: fewer than two of the three measures can be assessed")
    if reasons:
        return "grey", reasons
    q1_abn, q3_abn = q1["status"] == ABNORMAL, q3["status"] == ABNORMAL
    if q1_abn and q3_abn:
        return "red", ["traffic and signal operation both differ from the site's history"]
    if q1_abn:
        return "amber_traffic", ["traffic differs from the site's history"]
    if q3_abn:
        return "amber_signal", ["signal operation differs from the site's history"]
    return "normal", []


# ---------------------------------------------------------------------- network
def screen(source, settings, baseline: dict, period: Period, network: list[dict] | None = None) -> dict:
    """Screen every site. `network` (optional) is the host's own site list:
    [{site, name, lat, lon, detectors: [numbers], links: [{link, street}]}]; without it the source is read.
    A site that fails to process is reported in `errors` and does not stop the run."""
    rules, schema = settings.rules, settings.schema
    detectors, links = defaultdict(list), defaultdict(list)
    if network is None:
        sites = source.sites()
        site_ids = [s["site"] for s in sites]
        for d in source.detectors(site_ids):
            detectors[d["site"]].append(d)
        for a in source.approaches(site_ids):
            links[a["site"]].append(a)
    else:
        sites = network
        for s in network:
            detectors[s["site"]] = [{"site": s["site"], "detector": int(n), "active": True} for n in s.get("detectors", [])]
            links[s["site"]] = [{"site": s["site"], **a} for a in s.get("links", [])]

    m = Measures(source, rules, schema)
    totals = m.detector_totals(period, rules["q2"]["window_minutes"])
    volume = m.link_volumes([period])[period.key]
    kpi, origin = m.site_kpi([period])
    kpi, origin = kpi[period.key], origin[period.key]
    green = m.approach_green([period])[period.key]

    results, errors = [], {}
    for s in sites:
        site = s["site"]
        try:
            bounds = {link: v.get("bound") for link, v in green.get(site, {}).items()}
            q2 = q2_gate(detectors.get(site, []), totals.get(site, {}), rules)
            q1 = q3 = None
            if q2["status"] == PASS:
                q1 = q1_traffic(links.get(site, []), volume, baseline["volume"], bounds, rules)
                q3c = q3c_phase_service(links.get(site, []), green.get(site, {}), baseline["green"].get(site, {}), bounds, rules)
                q3 = q3_signal(kpi.get(site, {}), baseline["kpi"].get(site, {}), origin.get(site, {}), q3c, rules)
            category, reasons = classify(q2, q1, q3)
        except Exception as exc:  # noqa: BLE001 - one bad site must not stop the network screening
            errors[site] = f"{type(exc).__name__}: {exc}"
            continue
        results.append({"site": site, "name": site_name(s.get("streets")) or s.get("name"), "lat": s.get("lat"),
                        "lon": s.get("lon"), "category": category, "label": CATEGORIES[category], "reasons": reasons,
                        "selectable": rules["click"].get(category, []), "q2": q2, "q1": q1, "q3": q3,
                        "total_volume_veh_h": total_volume(q1)})
    counts = defaultdict(int)
    for r in results:
        counts[r["category"]] += 1
    return {"sites": results, "counts": dict(counts), "errors": errors, "alignment": m.aligner.stats}


def total_volume(q1: dict | None) -> float | None:
    """Site volume for the period as an hourly rate (veh/h): the evaluated approaches' 30-minute sum x 2.
    None unless every evaluated approach has a value."""
    if not q1 or not q1["approaches"] or any(a["current"] is None for a in q1["approaches"]):
        return None
    return round(sum(a["current"] for a in q1["approaches"]) * 60 / 30, 1)
