"""Ranking within a category (proposal, 16 Nov 2026; rules.json "rank").

Sites are ordered within Red and within each Amber category; a rank never moves a site between categories.

    score = severity x impact x type x confidence x persistence

- severity: for every abnormal finding a robust z-score, |current - usual| / spread, where spread is the 10th-90th
  percentile width divided by 2.563 (the standard deviation of a normal distribution with that range), never below a
  floor: sqrt(usual) vehicles for volume (the Poisson standard deviation of a count), 2 s for cycle length, 1 point for
  Cycle Stability, 1 percentage point for green share. Each z is capped at 5; the three largest are combined as
  sqrt(sum z^2), so one extreme value cannot dominate and several findings add up.
- impact: log10(1 + site volume veh/h) / log10(1 + 1000): 1.0 at 1,000 veh/h, 0.67 at 100 veh/h.
- type: x 1.25 when phase service moves opposite to the volume on the same approach (diagnosis type A1).
- confidence: x 0.8 when a finding rests on the 5-week minimum history; x 0.8 with a tolerated detector.
- persistence: x (1 + 0.25 k), k = the number of the previous 4 same-weekday, same-slot periods in which the site had
  the same category (Red), or Red or Amber (Amber). It counters regression to the mean: a site unusual once is often
  normal the next time; one unusual repeatedly is not (Hauer 1997; Highway Safety Manual network screening).
- approaches with identical green-share values are one phase and count as one finding.
- mapping-suspect sites (a usual green share of 100 % or a usual volume of 0 behind a finding) are listed apart,
  unranked: the finding may come from the phase-to-approach or link assignment.
"""
from __future__ import annotations

import math

from .names import approach_label
from .stats import ABNORMAL

RANKED = ("red", "amber_traffic", "amber_signal")
FLOOR_UNITS = {"volume": "veh", "cycle_length": "s", "cycle_stability": "points", "phase_service": "pp"}


def spread(row: dict, measure: str, rule: dict) -> float | None:
    lo, hi, usual = row.get("p_low"), row.get("p_high"), row.get("usual")
    if lo is None or hi is None or usual is None:
        return None
    floor = rule["spread_floor"][measure]
    floor = math.sqrt(max(usual, 1)) if floor == "sqrt_usual" else float(floor)
    return max((hi - lo) / rule["range_to_sd"], floor)


def z_score(row: dict, measure: str, rule: dict) -> float | None:
    s = spread(row, measure, rule)
    if s is None or row.get("current") is None:
        return None
    return min(abs(row["current"] - row["usual"]) / s, rule["z_cap"])


def findings(site: dict, rule: dict) -> list[dict]:
    """Every abnormal finding of the site with its z-score, largest first."""
    out = []
    q1, q3 = site.get("q1") or {}, site.get("q3") or {}
    for a in q1.get("approaches") or []:
        if a["status"] == ABNORMAL:
            out.append({"measure": "volume", "approach": approach_label(a), "row": a})
    comps = q3.get("components") or {}
    for key in ("cycle_length", "cycle_stability"):
        if (comps.get(key) or {}).get("status") == ABNORMAL:
            out.append({"measure": key, "approach": None, "row": comps[key]})
    phases: dict[tuple, dict] = {}
    for a in (comps.get("phase_service") or {}).get("approaches") or []:
        if a["status"] == ABNORMAL:
            # approaches with identical values are one phase: counted once (as in the D001 wording)
            key = (a["current"], a["usual"], a["p_low"], a["p_high"], a["direction"])
            if key in phases:
                phases[key]["approaches"].append(approach_label(a))
                phases[key]["approach"] = " and ".join(phases[key]["approaches"]) + " (one phase)"
            else:
                phases[key] = {"measure": "phase_service", "approach": approach_label(a), "row": a,
                               "approaches": [approach_label(a)]}
    out += phases.values()
    for f in out:
        f["z"] = z_score(f["row"], f["measure"], rule) or 0.0
    return sorted(out, key=lambda f: -f["z"])


def describe(f: dict) -> str:
    r = f["row"]
    c, u = r["current"], r["usual"]
    if f["measure"] == "volume":
        what = f"volume {f['approach']} {c:.0f} vs {u:.0f} veh/30 min"
    elif f["measure"] == "phase_service":
        what = f"green share {f['approach']} {c:.1f}% vs {u:.1f}%"
    elif f["measure"] == "cycle_length":
        what = f"cycle length {c:.0f} vs {u:.0f} s"
    else:
        what = f"Cycle Stability {c:.1f} vs {u:.1f}"
    return f"{what} (z {f['z']:.1f})"


def mapping_suspect(fs: list[dict]) -> list[str]:
    out = []
    for f in fs:
        u = f["row"].get("usual")
        if f["measure"] == "phase_service" and u is not None and u >= 100:
            out.append(f"usual green share 100% on {f['approach']}")
        if f["measure"] == "volume" and u == 0:
            out.append(f"usual volume 0 on {f['approach']}")
    return out


def opposite(fs: list[dict]) -> list[str]:
    volume = {f["approach"]: f["row"]["direction"] for f in fs if f["measure"] == "volume"}
    return [a for f in fs if f["measure"] == "phase_service" for a in f["approaches"]
            if volume.get(a) not in (None, f["row"]["direction"])]


def site_volume(site: dict) -> float | None:
    if site.get("total_volume_veh_h") is not None:
        return site["total_volume_veh_h"]
    vals = [a["current"] for a in (site.get("q1") or {}).get("approaches") or [] if a.get("current") is not None]
    return sum(vals) * 2 if vals else None


def score(site: dict, rules: dict, persistence: int | None = None) -> dict:
    """The score of one Red or Amber site and the reasons behind it."""
    rule = rules["rank"]
    fs = findings(site, rule)
    top = fs[:rule["top_findings"]]
    severity = math.sqrt(sum(f["z"] ** 2 for f in top))
    volume = site_volume(site)
    impact = math.log10(1 + (volume or 0)) / math.log10(1 + rule["impact_reference_veh_h"])
    opp = opposite(fs)
    type_factor = rule["opposite_direction_factor"] if opp else 1.0
    weeks = [f["row"].get("n_history") for f in fs if f["row"].get("n_history")]
    thin = bool(weeks) and min(weeks) <= rule["minimum_history_weeks"]
    tolerated = (site.get("q2") or {}).get("tolerated") or []
    confidence = (rule["minimum_history_factor"] if thin else 1.0) * (rule["tolerated_detector_factor"] if tolerated else 1.0)
    persist = 1.0 + rule["persistence_step"] * (persistence or 0)
    total = severity * impact * type_factor * confidence * persist
    reasons = [describe(f) for f in top]
    if opp:
        reasons.append("phase service opposite to volume on " + ", ".join(opp))
    if persistence:
        reasons.append(f"also {'Red' if site['category'] == 'red' else 'Red or Amber'} in {persistence} of the previous "
                       f"{rule['persistence_weeks']} weeks")
    if thin:
        reasons.append(f"history at the {rule['minimum_history_weeks']}-week minimum")
    if tolerated:
        reasons.append("one detector tolerated")
    suspect = mapping_suspect(fs)
    from .subsystems import membership
    m = membership(site["site"])
    return {"subsystem": f"{m['region']}-{m['subsystem']}" if m else None,
            "subsystem_sites": len(m["members"]) if m else None, "site": site["site"], "name": site.get("name"), "category": site["category"], "score": round(total, 2),
            "severity": round(severity, 2), "impact": round(impact, 2), "volume_veh_h": volume,
            "type_factor": type_factor, "confidence": round(confidence, 2), "persistence": persistence,
            "persistence_factor": persist, "findings": len(fs), "opposite_direction": opp, "min_history": min(weeks) if weeks else None,
            "tolerated_detector": bool(tolerated), "mapping_suspect": suspect, "reasons": reasons}


def persistence_counts(site_id: str, category: str, previous: list[dict | None]) -> int | None:
    """Previous runs (same weekday and slot) as {site: category}; None when none is available."""
    runs = [p for p in previous if p is not None]
    if not runs:
        return None
    hit = {"red"} if category == "red" else set(RANKED)
    return sum(1 for p in runs if p.get(site_id) in hit)


def rank(sites: list[dict], rules: dict, previous: list[dict | None] | None = None) -> dict[str, list[dict]]:
    """{category: ranked rows} for Red and Amber, plus "mapping_suspect" (unranked)."""
    out = {c: [] for c in RANKED}
    out["mapping_suspect"] = []
    for s in sites:
        if s["category"] not in RANKED:
            continue
        row = score(s, rules, persistence_counts(s["site"], s["category"], previous or []))
        (out["mapping_suspect"] if row["mapping_suspect"] else out[s["category"]]).append(row)
    for c in RANKED:
        out[c].sort(key=lambda r: (-r["score"], r["site"]))
        for k, r in enumerate(out[c], 1):
            r["rank"] = k
    return out
