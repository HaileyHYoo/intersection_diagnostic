"""Audit of Q1-Q3 inputs for the methodology owner's integration checks (read only).

    python main.py audit --end 2026-10-30T15:30 [--run ID]

For one analysis period it re-reads the inputs (Neo4j, the volume, detector, IntersectionPerfKpi and
IntersectionPerfApproach feeds, the TomTom mapping file) for the analysis period and its reference weeks, and
classifies what it finds into types, each with representative intersections:

    implementation   something this code does wrongly            (to fix here)
    mapping          SCATS / OSM / Platform mapping limitation    (to address progressively with the data owner)
    data             a gap or an implausible record in a feed      (to raise with the data owner)
    operation        genuine signal operation or traffic           (no action)

Nothing is written to the databases and no category is changed. Outputs: out/audit_<period>.md and .json.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

from .. import ids, screening, tomtom_map
from ..measures import Measures
from ..settings import package_file
from ..stats import INSUFFICIENT
from ..timewin import reference_periods, to_utc

EXAMPLES = 6


def _ex(items, n=EXAMPLES):
    return list(items)[:n]


def _periods(svc, end):
    period = svc.period(end)
    used, skipped = reference_periods(period, svc.settings.rules)
    return period, used, skipped


def _in(t, p, late: bool = False) -> bool:
    t = to_utc(t if isinstance(t, datetime) else datetime.fromisoformat(str(t)))
    if late:                                       # written after its quarter-hour: the one that ended before
        t = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)
    return to_utc(p.start) < t <= to_utc(p.end)


def _raw_by_period(source, key: str, periods: list, late: bool = False) -> dict:
    """{period key: [raw rows]} for one feed, every site, every field (one query per period)."""
    from datetime import timedelta
    read = getattr(source, "raw_all", source.raw)
    out = {}
    for p in periods:
        rows = read(key, p.start, p.end + timedelta(minutes=15 if late else 0), None)
        out[p.key] = [r for r in rows if _in(r["time"], p, late)]
    return out


def _records(rows: list[dict], site_tag: str, link_tag: str | None = None) -> dict:
    """{(site[, link]): {stamp: {field: value}}} from raw rows."""
    out = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        key = (ids.site(r.get(site_tag)),) + ((ids.link(r.get(link_tag)),) if link_tag else ())
        out[key][str(r["time"])][r["field"]] = r["value"]
    return out


# ---------------------------------------------------------------------- 1. Q1 volume and approach mapping
def audit_q1(svc, baseline, period, sites, links, perf_now, tomtom) -> dict:
    vol_hist = {link for link, env in baseline["volume"].items() if env["n"] > 0}
    m = Measures(svc.source, svc.settings.rules, svc.settings.schema)
    current = m.link_volumes([period])[period.key]
    perf_links = defaultdict(set)
    for site, link in perf_now:
        perf_links[site].add(link)
    counts, examples = Counter(), defaultdict(list)
    for site in sites:
        egress = {a["link"] for a in links.get(site, [])}
        checks = {
            "egress_link_without_volume_history": egress - vol_hist,
            "egress_link_without_current_volume": {x for x in egress & vol_hist if current.get(x) is None},
            "perf_approach_link_not_egress": perf_links.get(site, set()) - egress,
            "egress_link_without_perf_approach": egress - perf_links.get(site, set()) if perf_links.get(site) else set(),
            "tomtom_link_not_egress": tomtom.get(site, set()) - egress,
        }
        for name, found in checks.items():
            if found:
                counts[name] += 1
                examples[name].append(f"{site}: {', '.join(sorted(found)[:3])}")
    return {
        "source": "scats-aggregation/volume, DetectorGroupId = Neo4j EGRESS Road.link_id; current value = sum of the "
                  "two 15-minute volumes; history = the same 30 minutes in each reference week (Melbourne local time)",
        "sites_with": dict(counts), "examples": {k: _ex(v) for k, v in examples.items()},
        "types": {
            "egress_link_without_volume_history": "mapping – an EGRESS link with no detector group (exit-only link, "
                                                  "slip lane or a link not matched to a SCATS detector group); left out of Q1",
            "egress_link_without_current_volume": "data – the volume feed has no value now",
            "perf_approach_link_not_egress": "mapping – the Platform's approach list has a link that is not an EGRESS road",
            "egress_link_without_perf_approach": "mapping – an EGRESS road that the Platform's approach list does not have",
            "tomtom_link_not_egress": "mapping – the TomTom mapping ties an approach to a link that is not an EGRESS road",
        }}


# ---------------------------------------------------------------------- 2. Q2 detectors
def audit_q2(svc, period, refs, sites, detectors) -> dict:
    rules = svc.settings.rules
    m = Measures(svc.source, rules, svc.settings.schema)
    window = rules["q2"]["window_minutes"]
    now = m.detector_totals(period, window)
    fields_extra, active_missing = [], []
    low = {}                                                     # (site, detector) -> count now
    for site in sites:
        active = {d["detector"] for d in detectors.get(site, []) if d["active"]}
        present = now.get(site, {})
        missing = sorted(active - set(present))
        extra = sorted(d for d, t in present.items() if d not in active and t["records"] and t["total"] > 0)
        if missing:
            active_missing.append(f"{site}: d{missing[:4]}")
        if extra:
            fields_extra.append(f"{site}: d{extra[:4]}")
        gate = screening.q2_gate(detectors.get(site, []), present, rules)
        for r in gate["detectors"]:
            if r["status"] == screening.FAIL:
                low[(site, r["detector"])] = r["count_60min"]
    # each low detector against its own history (same 60 minutes in the reference weeks)
    hist = defaultdict(list)
    for ref in refs:
        totals = m.detector_totals(ref, window)
        for (site, det) in low:
            t = totals.get(site, {}).get(det)
            if t and t["records"] == t["expected"]:
                hist[(site, det)].append(t["total"])
    minimum = rules["q2"]["min_vehicles"]
    kinds, ex = Counter(), defaultdict(list)
    for key, count in low.items():
        values = hist.get(key, [])
        usual = median(values) if len(values) >= 3 else None
        if usual is None:
            kind = "no history (fewer than 3 complete reference weeks)"
        elif usual < minimum:
            kind = "low-volume movement: usually below the threshold too"
        elif count == 0:
            kind = "zero now, usually above the threshold: possible detector fault"
        else:
            kind = "below the threshold now, usually above it: unusual low count"
        kinds[kind] += 1
        ex[kind].append(f"{key[0]} d{key[1]}: {count:.0f} now, usual {usual if usual is None else round(usual)} "
                        f"({len(values)} weeks)")
    return {
        "source": "scats/volume fields d[n], n = Neo4j Detector.detector_number (active, BELONG_TO); 60-minute count "
                  "of the valid 5-minute records; missing records are INSUFFICIENT DATA, never zero",
        "active_detector_without_any_record_now": len(active_missing),
        "examples_active_detector_without_record": _ex(active_missing),
        "counting_field_without_neo4j_detector": len(fields_extra),
        "examples_counting_field_without_detector": _ex(fields_extra),
        "low_count_detectors": len(low), "low_count_detector_types": dict(kinds.most_common()),
        "examples": {k: _ex(v) for k, v in ex.items()},
        "types": {"low-volume movement": "operation – the detector is usually below 10 vehicles in this hour",
                  "possible detector fault / unusual low count": "data – to check with the detector owner",
                  "active detector without record": "mapping/data – Neo4j detector with no d[n] in the feed",
                  "field without Neo4j detector": "mapping – the feed counts on a detector number Neo4j does not list"}}


# ---------------------------------------------------------------------- 3. Q3A/Q3B cycle KPIs
def audit_kpi(kpi_rows: dict, period, site_tag: str, network: set) -> dict:
    formula_bad, empty, zero_cycle = Counter(), Counter(), Counter()
    seen_empty = defaultdict(set)
    ex = defaultdict(list)
    for pkey, rows in kpi_rows.items():
        role = "current" if pkey == period.key else "history"
        for (site,), stamps in _records(rows, site_tag).items():
            if site not in network:
                continue                                  # KPI records of sites outside the screened network
            for stamp, f in stamps.items():
                cv, st = f.get("CycleCvPct"), f.get("CycleStability")
                if isinstance(cv, (int, float)) and isinstance(st, (int, float)):
                    if abs(st - max(0.0, 100 - 5 * cv)) > 0.05:
                        formula_bad[role] += 1
                        ex["formula"].append(f"{site} {stamp[:16]}: stability {st:.2f}, CV {cv:.2f}")
                if f.get("TotalVolume") == 0 and f.get("AvgCycle") not in (None, 0):
                    empty[role] += 1
                    seen_empty[role].add(site)
                    ex["empty"].append(f"{site} {stamp[:16]}: AvgCycle {f.get('AvgCycle')}, CycleStability "
                                       f"{f.get('CycleStability')}, TotalVolume 0")
                if f.get("AvgCycle") == 0:
                    zero_cycle[role] += 1
                    ex["zero"].append(f"{site} {stamp[:16]}")
    for role, s in seen_empty.items():
        empty[f"{role}_sites"] = len(s)
    return {"source": "IntersectionPerfKpi AvgCycle and CycleStability (MinutesPast 15), mean of the two 15-minute "
                      "records; a missing record gives no value (never zero); history formed the same way",
            "records_not_matching_the_stability_formula": dict(formula_bad),
            "records_with_a_cycle_but_total_volume_0": dict(empty),
            "records_with_avg_cycle_0": dict(zero_cycle),
            "examples": {k: _ex(v) for k, v in ex.items()},
            "types": {"formula mismatch": "implementation/data – stored stability not equal to (1 - CV/0.20)*100",
                      "cycle with TotalVolume 0": "data – a record with a cycle but no volume (possible empty record); "
                                                  "used as a valid value by the screening",
                      "AvgCycle 0": "data – a zero cycle length stored as a value"}}


# ---------------------------------------------------------------------- 4. Q3C phase service
def _phases(value) -> frozenset:
    return frozenset(p.strip() for p in str(value or "").split(",") if p.strip())


def audit_q3c(perf_rows: dict, period, run_sites: dict, feed: dict) -> dict:
    tag, ltag = feed["site_tag"], feed["link_tag"]
    now = _records(perf_rows[period.key], tag, ltag)
    by_site = defaultdict(dict)
    for (site, link), stamps in now.items():
        by_site[site][link] = stamps
    hist = defaultdict(list)                                       # (site, link) -> [(period, stamp, fields)]
    for pkey, rows in perf_rows.items():
        if pkey == period.key:
            continue
        for key, stamps in _records(rows, tag, ltag).items():
            for stamp, f in stamps.items():
                hist[key].append((pkey, stamp, f))

    # (a) is GreenShare built from phase durations? the share of a multi-phase approach against the sum of the
    #     single-phase shares at the same site and quarter-hour, and approaches with the same phases
    additive, same_set = Counter(), Counter()
    for site, approaches in by_site.items():
        stamps = {s for st in approaches.values() for s in st}
        for stamp in stamps:
            rows = [(_phases(st[stamp].get("Phases")), st[stamp].get("GreenShare")) for st in approaches.values()
                    if stamp in st and st[stamp].get("HasGreen") == 1 and isinstance(st[stamp].get("GreenShare"), (int, float))]
            single = {next(iter(ps)): g for ps, g in rows if len(ps) == 1}
            for ps, g in rows:
                if len(ps) > 1 and all(p in single for p in ps):
                    additive["equal" if abs(sum(single[p] for p in ps) - g) <= 0.5 else "different"] += 1
            for i, (ps, g) in enumerate(rows):
                for qs, h in rows[i + 1:]:
                    if ps and ps == qs:
                        same_set["equal" if abs(g - h) <= 0.01 else "different"] += 1

    # (b) the Grey sites with an approach without green
    nogreen, ng_ex = Counter(), defaultdict(list)
    # (c) 100 % and (d) large changes, from the run's evaluated rows
    full, full_ex, large, large_ex = Counter(), defaultdict(list), Counter(), defaultdict(list)
    for site, s in run_sites.items():
        ps = ((s.get("q3") or {}).get("components") or {}).get("phase_service") or {}
        site_now = by_site.get(site, {})
        all_phases = frozenset().union(*[_phases(f.get("Phases")) for st in site_now.values() for f in st.values()]) \
            if site_now else frozenset()
        for row in ps.get("approaches", []):
            link = row["link"]
            recs = site_now.get(link, {})
            name = f"{site} {row.get('label') or link}"
            if row.get("no_green") and s["category"] == "grey":
                if not recs:
                    kind = "no record now (data gap)"
                elif not any(_phases(f.get("Phases")) for st in site_now.values() for f in st.values()):
                    kind = "no phase information for the whole site now (empty records)"
                elif not any(_phases(f.get("Phases")) for f in recs.values()):
                    kind = "approach has no phase assigned now (phase-to-approach mapping)"
                else:
                    kind = "assigned phase did not run (signal operation)"
                weeks = sum(1 for _, _, f in hist.get((site, link), []) if f.get("HasGreen") == 1) // 2
                nogreen[kind] += 1
                ng_ex[kind].append(f"{name} (green in about {weeks} reference week(s))")
            cur = row.get("current")
            if cur is not None and cur >= 99.999:
                mine = frozenset().union(*[_phases(f.get("Phases")) for f in recs.values()]) if recs else frozenset()
                others_ran = any(f.get("HasGreen") == 1 and (f.get("GreenShare") or 0) > 0 and _phases(f.get("Phases")) - mine
                                 for st in site_now.values() for f in st.values())
                kind = ("approach runs in every phase recorded at the site (genuine)" if mine and mine == all_phases
                        else "other phases exist but did not run in the period (genuine)" if mine and not others_ran
                        else "100 % while another phase ran (check phase-to-approach mapping)" if mine
                        else "100 % without phase information (check record)")
                full[kind] += 1
                full_ex[kind].append(f"{name}: phases {','.join(sorted(mine)) or '-'} of {','.join(sorted(all_phases)) or '-'}"
                                     f", usual {row.get('usual')}")
            if cur is not None and row.get("usual") is not None and abs(cur - row["usual"]) >= 30:
                past = hist.get((site, link), [])
                now_set = frozenset().union(*[_phases(f.get("Phases")) for f in recs.values()]) if recs else frozenset()
                past_sets = Counter(_phases(f.get("Phases")) for _, _, f in past if f.get("HasGreen") == 1)
                usual_set = past_sets.most_common(1)[0][0] if past_sets else frozenset()
                empty_past = sum(1 for _, _, f in past if f.get("HasGreen") == 1 and f.get("Volume") == 0
                                 and f.get("DemandShare") == 0 and (f.get("GreenShare") or 0) >= 99.999)
                if usual_set and now_set and usual_set != now_set:
                    kind = "phases serving the approach differ from history (configuration or mapping change)"
                elif empty_past:
                    kind = "history includes 100 % green records with no volume and no demand (possible empty records)"
                elif not usual_set:
                    kind = "history has no phase information (Phases not stored then): cause not determinable"
                else:
                    kind = "same phases, different phase durations (signal operation)"
                large[kind] += 1
                large_ex[kind].append(f"{name}: {cur:.1f}% now, usual {row['usual']:.1f}%, phases now "
                                      f"{','.join(sorted(now_set)) or '-'} / usually {','.join(sorted(usual_set)) or '-'}")
    return {
        "source": "IntersectionPerfApproach GreenShare (%) and HasGreen per LinkId, mean of the two 15-minute records; "
                  "Phases lists the phases serving the approach",
        "is_green_share_from_phase_durations": {
            "multi-phase approach equal to the sum of its single-phase shares (±0.5 pp)": dict(additive),
            "approaches with the same phases have the same share": dict(same_set),
            "reading": "if nearly all are equal, GreenShare is the share of the cycle taken by the phases serving the "
                       "approach (phase durations), not measured signal-group green time"},
        "grey_no_green_approaches": dict(nogreen.most_common()), "examples_no_green": {k: _ex(v) for k, v in ng_ex.items()},
        "current_100pct": dict(full.most_common()), "examples_100pct": {k: _ex(v) for k, v in full_ex.items()},
        "change_at_least_30pp": dict(large.most_common()), "examples_large_change": {k: _ex(v) for k, v in large_ex.items()}}


# ---------------------------------------------------------------------- 6. quarter-hour of the :07/:22 records
def audit_timing(source, settings, period) -> dict:
    """PerfApproach records carry the approach Volume. Compared with the 15-minute link volumes (stamped at the
    quarter-hour end), which quarter-hour does a record stamped at :07 or :22 describe? 'ceil' is the quarter-hour its
    stamp falls in (what the screening assumes), 'floor' the quarter-hour that ended just before the stamp."""
    from datetime import timedelta
    feeds = settings.schema["influx"]["sources"]
    start, end = period.start - timedelta(minutes=45), period.end
    perf = getattr(source, "raw_all", source.raw)("approach_perf", start, end, None)
    vols = defaultdict(dict)
    for r in source.raw("link_volume", start - timedelta(minutes=15), end, None):
        vols[ids.link(r.get(feeds["link_volume"]["link_tag"]))][to_utc(r["time"]).replace(second=0, microsecond=0)] = r["value"]
    err = {"ceil": [], "floor": []}
    closer = Counter()
    for r in perf:
        if r["field"] != "Volume" or not isinstance(r["value"], (int, float)) or r["value"] <= 0:
            continue
        t = to_utc(r["time"])
        floor = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)
        ceil = floor + timedelta(minutes=15)
        series = vols.get(ids.link(r.get(feeds["approach_perf"]["link_tag"])), {})
        if floor in series and ceil in series:
            a, b = abs(series[ceil] - r["value"]), abs(series[floor] - r["value"])
            err["ceil"].append(a / max(series[ceil], 1))
            err["floor"].append(b / max(series[floor], 1))
            closer["floor" if b < a else "ceil" if a < b else "tie"] += 1
    mean = lambda xs: round(sum(xs) / len(xs) * 100, 1) if xs else None
    return {"records_compared": len(err["ceil"]),
            "mean_abs_difference_pct": {"ceil (quarter-hour the stamp falls in)": mean(err["ceil"]),
                                        "floor (quarter-hour ended before the stamp; the screening since Nov 2026)":
                                            mean(err["floor"])},
            "closer": dict(closer),
            "reading": "'floor' should be clearly closer: a record stamped hh:07 describes hh-15..hh:00 (confirmed with "
                       "the data owner), so the screening assigns it to that quarter-hour"}


# ---------------------------------------------------------------------- 5. classification trace
def audit_classification(run_sites: dict) -> dict:
    """Representative sites whose category was reached with incomplete inputs, and the reasons kept."""
    picks = defaultdict(list)
    for site, s in run_sites.items():
        q1, q3 = s.get("q1"), s.get("q3")
        if not q1 or not q3:
            continue
        c = q3["components"]
        miss_q1 = [a["link"] for a in q1["approaches"] if a["status"] == INSUFFICIENT]
        miss_q3c = [a["link"] for a in c["phase_service"]["approaches"] if a["status"] == INSUFFICIENT]
        line = (f"{site} {s['category']}: Q1 {q1['status']} (flagged {len(q1['flagged'])}, not assessable {len(miss_q1)}, "
                f"no history {len(q1['not_evaluated'])}); Q3A {c['cycle_length']['status']}, Q3B "
                f"{c['cycle_stability']['status']}, Q3C {c['phase_service']['status']} (not assessable {len(miss_q3c)}); "
                f"reasons: {'; '.join(s['reasons']) or '-'}")
        if s["category"] in ("red", "amber_traffic", "amber_signal") and (miss_q3c or q1["not_evaluated"]):
            picks[f"{s['category']} with incomplete inputs"].append(line)
        elif s["category"] == "normal" and q3.get("missing_measure_could_change"):
            picks["normal with one Q3 measure not assessable"].append(line)
        elif s["category"] == "grey":
            picks["grey (reasons kept)"].append(line)
    return {"rule": "Q1 and Q3C are ABNORMAL when any assessed approach is abnormal; a missing approach only "
                    "withholds NORMAL (then INSUFFICIENT DATA, Grey). Q3 needs 2 of 3 measures abnormal; NORMAL needs "
                    "2 assessable. Every insufficient result keeps its reason in the log.",
            "examples": {k: _ex(v, 4) for k, v in picks.items()}}


# ---------------------------------------------------------------------- run
def run(svc, end: str | None, run_id: str | None = None) -> dict:
    source, settings = svc.source, svc.settings
    period, refs, skipped = _periods(svc, end)
    baseline = svc.baselines.get(period)
    sites = [s["site"] for s in source.sites()]
    links, detectors = defaultdict(list), defaultdict(list)
    for a in source.approaches(sites):
        links[a["site"]].append(a)
    for d in source.detectors(sites):
        detectors[d["site"]].append(d)
    feeds = settings.schema["influx"]["sources"]
    late = settings.rules["alignment"].get("written_after_interval", [])
    perf_rows = _raw_by_period(source, "approach_perf", [period] + refs, "approach_perf" in late)
    kpi_rows = _raw_by_period(source, "site_kpi", [period] + refs, "site_kpi" in late)
    perf_now = {(ids.site(r.get(feeds["approach_perf"]["site_tag"])), ids.link(r.get(feeds["approach_perf"]["link_tag"])))
                for r in perf_rows[period.key]}
    try:
        mapping = tomtom_map.load(str(package_file(settings.schema["tomtom_mapping"]["file"])))
        tomtom = {s: {a["link"] for a in m["approaches"].values() if a.get("link")} for s, m in mapping.items()}
    except Exception:  # noqa: BLE001
        tomtom = {}
    run_id = run_id or next((r["run_id"] for r in svc.store.list_runs(50) if r["status"] == "complete"
                             and svc.store.get_run(r["run_id"])["payload"]["period"]["key"] == period.key), None)
    run_sites = {s["site"]: s for s in svc.store.get_run(run_id)["payload"]["sites"]} if run_id else {}
    return {"period": period.label(), "run": run_id, "reference_periods": [p.label() for p in refs],
            "reference_utc": [f"{to_utc(p.start):%Y-%m-%d %H:%M}Z" for p in refs], "skipped_days": skipped,
            "q1": audit_q1(svc, baseline, period, sites, links, perf_now, tomtom),
            "q2": audit_q2(svc, period, refs, sites, detectors),
            "q3ab": audit_kpi(kpi_rows, period, feeds["site_kpi"]["site_tag"], set(sites)),
            "q3c": audit_q3c(perf_rows, period, run_sites, feeds["approach_perf"]),
            "classification": audit_classification(run_sites),
            "timing": audit_timing(source, settings, period)}


def markdown(a: dict) -> str:
    out = [f"# Audit of Q1–Q3 inputs – {a['period']}", "", f"Run `{a['run']}`. Reference weeks (Melbourne local time; "
           "UTC shown to check daylight saving): " + ", ".join(f"{p} = {u}" for p, u in zip(a["reference_periods"],
                                                                                          a["reference_utc"])), ""]
    for key, title in (("q1", "1. Q1 – traffic volume and approach mapping"), ("q2", "2. Q2 – detectors"),
                       ("q3ab", "3. Q3A/Q3B – cycle length and stability"), ("q3c", "4. Q3C – phase service"),
                       ("classification", "5. Classification and evidence"),
                       ("timing", "6. Which quarter-hour the PerfKpi/PerfApproach records describe")):
        out += [f"## {title}", ""]
        for k, v in a[key].items():
            if isinstance(v, dict):
                out.append(f"- **{k}**" + ("" if v else ": none"))
                out += [f"  - {kk}: {vv if vv not in ({}, []) else 'none'}" for kk, vv in v.items()]
            elif isinstance(v, list):
                out.append(f"- **{k}**: " + ("; ".join(map(str, v)) or "none"))
            else:
                out.append(f"- **{k}**: {v}")
        out.append("")
    return "\n".join(out)


def save(a: dict, out_dir: str, stamp: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    js, md = out / f"audit_{stamp}.json", out / f"audit_{stamp}.md"
    js.write_text(json.dumps(a, indent=2, default=str), encoding="utf-8")
    md.write_text(markdown(a), encoding="utf-8")
    return js, md
