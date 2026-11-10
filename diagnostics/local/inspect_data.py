"""Inspect the live feeds for one site and a short window, and check the schema's assumptions.

    python main.py inspect --site 4397 --end 2026-10-27T08:30 --hours 2

For each feed it reports the record count, the interval between stamps, how many stamps fall on the
expected grid, duplicates, value types and sample rows; then:

    detectors   Neo4j BELONG_TO detector numbers (active and inactive) against the d[n] fields present
    links       Neo4j EGRESS links against volume DetectorGroupId and IntersectionPerfApproach LinkId,
                with the raw IDs that needed normalising
    stamps      the first and last stamps in the window, to confirm end-of-interval labelling
    tomtom      the site's junction UUID and approach mapping, and the queue archive rows for the window
    link_speed  TomTom speed samples of the site's EGRESS links in the analysis period (supplementary)

    python main.py inspect --site 994 --end 2026-10-30T15:00 --history

adds the history behind the baseline: for each reference period (same weekday and 30-minute slot in the
previous weeks) the value of every measure, or why it is missing, and per approach how many usable values
the baseline gets.

Nothing is written to the databases. The report is printed and saved as JSON.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from .. import ids
from ..settings import Settings
from ..timewin import period_ending, latest_period, to_utc


def _grid_report(stamps: list, step: int) -> dict:
    stamps = sorted({to_utc(t) for t in stamps})
    diffs = Counter(int((b - a).total_seconds()) for a, b in zip(stamps, stamps[1:]))
    offsets = Counter(f"{t.minute % step:02d}:{t.second:02d}" for t in stamps)
    on_grid = sum(1 for t in stamps if t.minute % step == 0 and t.second == 0 and t.microsecond == 0)
    return {"distinct_stamps": len(stamps), "first": stamps[0].isoformat() if stamps else None,
            "last": stamps[-1].isoformat() if stamps else None, "on_grid": on_grid,
            "off_grid": len(stamps) - on_grid, "step_seconds": dict(diffs.most_common(5)),
            "offset_within_step (mm:ss)": dict(offsets.most_common(6))}


def _feed_report(rows: list[dict], step: int, entity_keys: list[str]) -> dict:
    by_entity = defaultdict(list)
    for r in rows:
        by_entity[tuple(str(r.get(k)) for k in entity_keys) + (r.get("field"),)].append(to_utc(r["time"]))
    duplicates = sum(len(v) - len(set(v)) for v in by_entity.values())
    near = 0
    for v in by_entity.values():
        v = sorted(v)
        near += sum(1 for a, b in zip(v, v[1:]) if 0 < (b - a).total_seconds() < step * 60 / 2)
    types = Counter(type(r.get("value")).__name__ for r in rows)
    fields = Counter(str(r.get("field")) for r in rows)
    return {"records": len(rows), "series": len(by_entity), "exact_duplicate_stamps": duplicates,
            "records_closer_than_half_a_step": near, "value_types": dict(types),
            "fields": dict(fields.most_common(60)), **_grid_report([r["time"] for r in rows], step),
            "samples": [{k: (str(v) if k == "time" else v) for k, v in r.items()} for r in rows[:5]]}


def inspect(source, settings: Settings, site: str, end=None, hours: float = 2.0) -> dict:
    schema, rules = settings.schema, settings.rules
    feeds = schema["influx"]["sources"]
    period = period_ending(end, rules) if end else latest_period(rules)
    stop = period.end
    start = stop - timedelta(hours=hours)
    site = ids.site(site)
    report = {"site": site, "window": {"start": start.isoformat(), "end": stop.isoformat(), "local_end": period.label()},
              "schema_version": schema.get("version"), "feeds": {}, "checks": {}, "errors": {}}

    def attempt(name, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - every feed is reported, even when one fails
            report["errors"][name] = f"{type(exc).__name__}: {exc}"
            return None

    detectors = attempt("neo4j.detectors", lambda: source.detectors([site])) or []
    approaches = attempt("neo4j.approaches", lambda: source.approaches([site])) or []
    report["neo4j"] = {"detectors": detectors, "approaches": approaches}

    raw = {}
    for key in ("detector_counts", "link_volume", "site_kpi", "approach_perf", "tomtom_site_kpi", "tomtom_turn_kpi"):
        feed = feeds[key]
        rows = attempt(f"influx.{key}", lambda k=key: source.raw(k, start, stop, [site]))
        if rows is None:
            continue
        if key == "link_volume":
            wanted = {a["link"] for a in approaches}
            rows = [r for r in rows if ids.link(r.get(feed["link_tag"])) in wanted]
        raw[key] = rows
        entity = [t for t in (feed.get("site_tag"), feed.get("link_tag"), feed.get("approach_tag"), feed.get("exit_tag")) if t]
        report["feeds"][key] = {"measurement": f"{feed['bucket']}/{feed['measurement']}",
                                "expected_step_minutes": feed["interval_minutes"],
                                **_feed_report(rows, feed["interval_minutes"], entity)}

    # detectors: Neo4j numbers against d[n] fields
    if "detector_counts" in raw:
        pattern = re.compile(re.escape(feeds["detector_counts"]["detector_field"]).replace(r"\{n\}", r"(\d+)") + "$")
        present = sorted({int(m.group(1)) for r in raw["detector_counts"] for m in [pattern.match(str(r.get("field")))] if m})
        active = sorted(d["detector"] for d in detectors if d["active"])
        inactive = sorted(d["detector"] for d in detectors if not d["active"])
        nonzero = sorted({int(m.group(1)) for r in raw["detector_counts"] for m in [pattern.match(str(r.get("field")))]
                          if m and _num(r.get("value"))})
        report["checks"]["detectors"] = {
            "neo4j_active": active, "neo4j_inactive": inactive, "fields_present": present,
            "fields_with_nonzero_counts": nonzero,
            "active_without_field": sorted(set(active) - set(present)),
            "fields_without_neo4j_detector": sorted(set(present) - set(active) - set(inactive)),
            "other_fields": sorted({str(r.get("field")) for r in raw["detector_counts"] if not pattern.match(str(r.get("field")))}),
            "reading": "If active_without_field and fields_without_neo4j_detector are both empty, d[n] numbering "
                       "matches Detector.detector_number."}

    # links: Neo4j EGRESS against volume and perf tags
    egress = {a["link"] for a in approaches}
    vol_tag, perf_tag = feeds["link_volume"]["link_tag"], feeds["approach_perf"]["link_tag"]
    raw_vol = {str(r.get(vol_tag)) for r in raw.get("link_volume", [])}
    raw_perf = {str(r.get(perf_tag)) for r in raw.get("approach_perf", [])}
    report["checks"]["links"] = {
        "neo4j_egress": sorted(egress),
        "volume_links_matched": sorted(egress & {ids.link(x) for x in raw_vol}),
        "perf_links_for_site": sorted({ids.link(x) for x in raw_perf}),
        "egress_without_volume": sorted(egress - {ids.link(x) for x in raw_vol}),
        "egress_without_perf": sorted(egress - {ids.link(x) for x in raw_perf}),
        "perf_links_not_egress": sorted({ids.link(x) for x in raw_perf} - egress),
        "raw_ids_normalised": sorted({x for x in raw_vol | raw_perf if ids.link(x) != x}),
    }
    report["checks"]["timestamps"] = {
        "convention": schema["timestamps"]["label"],
        "reading": "With end labelling, a window ending at the period end holds a record stamped exactly at that end "
                   "(and none stamped at the window start). Compare 'first'/'last' of each feed with the window.",
        "window_start": start.isoformat(), "window_end": stop.isoformat(),
        "per_feed": {k: {"first": v.get("first"), "last": v.get("last")} for k, v in report["feeds"].items()},
    }

    # TomTom: the approach mapping and the queue archive (Q5)
    mapping = source.tomtom_mapping(site)
    tomtom = {"junction_uuid": mapping["uuid"], "mapped_approaches": len(mapping["approaches"]),
              "mapped_links_not_egress": sorted({a["link"] for a in mapping["approaches"].values()} - egress),
              "api_enabled": rules["tomtom"]["api_enabled"]}
    queue = attempt("tomtom.queue", lambda: source.tomtom_queue(site, start, stop)) if mapping["uuid"] else None
    if not mapping["uuid"]:
        tomtom["queue_skipped"] = "the site has no TomTom junction in the mapping file"
    if queue is not None:
        per = defaultdict(list)
        for r in queue:
            per[r["approach"]].append(r["queue_m"])
        raw_times = [str(r.get("raw_time")) for r in queue[:3]]
        tomtom["queue_time_format"] = {
            "raw_samples": raw_times, "naive_timestamps_read_as": settings.schema["tomtom_queue"]["naive_timestamp_timezone"],
            "has_offset": all(t.endswith("Z") or "+" in t[10:] or t[10:].count("-") > 0 for t in raw_times) if raw_times else None}
        tomtom["queue"] = {"rows": len(queue), "first": str(min((r["time"] for r in queue), default=None)),
                           "last": str(max((r["time"] for r in queue), default=None)),
                           "approaches": {a: {"minutes": len(v), "mean_m": round(sum(v) / len(v), 1),
                                              "mapped_link": mapping["approaches"].get(a, {}).get("link")}
                                          for a, v in per.items()}}
    report["checks"]["tomtom"] = tomtom
    links = [a["link"] for a in approaches]
    speed_rows = attempt("influx.link_speed", lambda: source.link_speeds(links, period.start, period.end)) if links else []
    if speed_rows is not None:
        from ..link_speed import _per_link, harmonic
        per_link = _per_link(speed_rows, period)                      # the samples a click uses: [start, end)
        report["checks"]["link_speed"] = {
            "links": len(links), "rows": len(speed_rows),
            "per_link": {k: {"samples": sum(x > 0 for x in v), "harmonic_kmh": None if harmonic(v) is None else round(harmonic(v), 1)}
                         for k, v in sorted(per_link.items())},
            "links_without_speed": sorted(set(links) - set(per_link)),
            # Stamps and series per link, to check the feed's interval (one record = how many minutes?)
            "stamps": _speed_stamps(speed_rows, period, settings),
            "samples": [{k: str(v) for k, v in r.items()} for r in speed_rows[:3]]}
    report["checks"]["period_values"] = attempt("period_values", lambda: period_values(source, settings, site, period, approaches))
    return report


def period_values(source, settings: Settings, site: str, period, approaches: list[dict]) -> dict:
    """What the screening would use for this site in the window's last 30-minute period."""
    from ..measures import Measures
    rules, schema = settings.rules, settings.schema
    m = Measures(source, rules, schema)
    totals = m.detector_totals(period, rules["q2"]["window_minutes"], sites=[site]).get(site, {})
    links = {a["link"] for a in approaches}
    volume = {k: v for k, v in m.link_volumes([period])[period.key].items() if k in links}
    kpi, _ = m.site_kpi([period], sites=[site])
    green = m.approach_green([period], sites=[site])[period.key].get(site, {})
    turn = source.tomtom_turn_kpi(site, period.start, period.end)
    label = schema["influx"]["sources"]["tomtom_turn_kpi"].get("timestamp_label", "end")
    from ..series import Aligner
    aligner, quarters = Aligner(rules["alignment"]), defaultdict(set)
    ends = set(period.interval_ends(15))
    by_approach = defaultdict(list)
    for r in turn:
        by_approach[r["approach"]].append((r["time"], r["value"]))
    for approach, points in by_approach.items():
        quarters[approach] = {t.isoformat() for t in aligner.align(points, 15, label) if t in ends}
    return {"period": period.label(), "period_end_utc": period.end.isoformat(),
            "q2_detector_totals_60min": {str(k): v for k, v in sorted(totals.items())},
            "q2_reading": "total = 60-minute count of the valid 5-minute records (negatives are treated as missing); records = valid records of expected",
            "q1_volume_30min": {k: volume.get(k) for k in sorted(links)},
            "q3_kpi": kpi[period.key].get(site),
            "q3c_green": green,
            "tomtom_quarters_used": {a: sorted(q) for a, q in quarters.items()},
            "reading": "None means the value is missing for this period and the site would be Grey (or TomTom partial)."}


def _num(value) -> bool:
    try:
        return float(value) != 0
    except (TypeError, ValueError):
        return False


def save(report: dict, out_dir: str = "out") -> Path:
    path = Path(out_dir) / f"inspect_S{report['site']}_{report['window']['end'][:16].replace(':', '')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def summary(report: dict) -> str:
    lines = [f"Site {report['site']}  window {report['window']['start']} -> {report['window']['end']}"]
    for key, f in report["feeds"].items():
        lines.append(f"  {key:16} {f['records']:6} records  series {f['series']:4}  on-grid {f['on_grid']}/{f['distinct_stamps']}"
                     f"  steps {f['step_seconds']}  types {f['value_types']}  dup {f['exact_duplicate_stamps']}")
    d = report["checks"].get("detectors")
    if d:
        lines.append(f"  detectors: neo4j active {d['neo4j_active']} | fields {d['fields_present']} | "
                     f"active without field {d['active_without_field']} | fields without detector {d['fields_without_neo4j_detector']}")
    li = report["checks"]["links"]
    lines.append(f"  links: egress {len(li['neo4j_egress'])}, without volume {li['egress_without_volume']}, "
                 f"without perf {li['egress_without_perf']}, normalised raw ids {li['raw_ids_normalised'][:5]}")
    pv = report["checks"].get("period_values")
    if pv:
        missing_det = [k for k, v in pv["q2_detector_totals_60min"].items() if v["records"] < v["expected"]]
        negative_det = [k for k, v in pv["q2_detector_totals_60min"].items() if v["negatives"]]
        lines.append(f"  period {pv['period']}: Q2 detectors {len(pv['q2_detector_totals_60min'])} (records missing {missing_det}, negatives {negative_det}), "
                     f"Q1 volumes {pv['q1_volume_30min']}, Q3 {pv['q3_kpi']}")
        lines.append(f"    Q3C green {{link: share}} {{{', '.join(f'{k}: {v['green_share']}' for k, v in pv['q3c_green'].items())}}}, "
                     f"TomTom quarters per approach {[len(v) for v in pv['tomtom_quarters_used'].values()]}")
    t = report["checks"].get("tomtom", {})
    q = t.get("queue")
    lines.append(f"  tomtom: junction {t.get('junction_uuid')}, mapped approaches {t.get('mapped_approaches')}, "
                 + (f"queue rows {q['rows']} over {len(q['approaches'])} approaches" if q else
                    t.get("queue_skipped") or "queue not read (see errors)"))
    s = report["checks"].get("link_speed")
    if s and s.get("stamps"):
        for link, info in s["stamps"].items():
            lines.append(f"  link speed stamps {link}: {len(info['times'])} in the period, series {info['series']}: "
                         + " ".join(info["times"]))
    if s:
        lines.append(f"  link speed (period): {s['rows']} samples, per link {{"
                     + ", ".join(f"{k}: {v['harmonic_kmh']} km/h ({v['samples']})" for k, v in s["per_link"].items())
                     + f"}}, without speed {s['links_without_speed']}")
    for k, v in report["errors"].items():
        lines.append(f"  ERROR {k}: {v}")
    return "\n".join(lines)


def history(source, settings: Settings, site: str, end=None) -> dict:
    """Per reference period: Q1 volume per EGRESS link, Q3A/Q3B KPIs, Q3C green share per link (or why not)."""
    from ..measures import Measures
    from ..timewin import reference_periods
    rules, schema = settings.rules, settings.schema
    period = period_ending(end, rules) if end else latest_period(rules)
    used, skipped = reference_periods(period, rules)
    links = sorted({a["link"] for a in source.approaches([site])})
    rows, usable = [], defaultdict(lambda: {"volume": 0, "green_share": 0})
    usable_kpi = Counter()
    for ref in [period] + used:
        m = Measures(source, rules, schema)
        volume = m.link_volumes([ref])[ref.key]
        kpi, _ = m.site_kpi([ref], sites=[site])
        green = m.approach_green([ref], sites=[site])[ref.key].get(site, {})
        row = {"period": ref.label(), "role": "analysis" if ref is period else "reference",
               "volume_30min": {link: None if volume.get(link) is None else round(volume[link], 1) for link in links},
               "kpi": kpi[ref.key].get(site, {}), "green_share": {}}
        for link in sorted(set(links) | set(green)):
            g = green.get(link)
            if g is None:
                state = "no records"
            elif not g["complete"]:
                state = "a quarter-hour missing"
            elif not g["green"]:
                state = f"HasGreen = 0 (GreenShare {g['raw_share']})"
            else:
                state = g["green_share"]
            row["green_share"][link] = state
            if ref is not period and isinstance(state, float):
                usable[link]["green_share"] += 1
        if ref is not period:
            for link in links:
                usable[link]["volume"] += volume.get(link) is not None
            usable_kpi.update(k for k in ("cycle_length", "cycle_stability") if k in row["kpi"])
        rows.append(row)
    return {"site": site, "period": period.label(), "minimum": rules["history"]["min_observations"],
            "reference_periods_used": len(used), "skipped": skipped, "periods": rows,
            "usable_history_per_link": {k: dict(v) for k, v in sorted(usable.items())},
            "usable_history_kpi": dict(usable_kpi)}


def history_text(h: dict) -> str:
    lines = [f"History for site {h['site']}, {h['period']}: {h['reference_periods_used']} reference periods "
             f"(minimum {h['minimum']}), skipped {h['skipped'] or 'none'}"]
    for row in h["periods"]:
        green = ", ".join(f"{k}: {v}" for k, v in row["green_share"].items())
        kpi = ", ".join(f"{k} {v:.1f}" for k, v in row["kpi"].items()) or "no KPI"
        lines.append(f"  {row['role'][:3]} {row['period']}")
        lines.append(f"      volume {row['volume_30min']}")
        lines.append(f"      {kpi} | green {green or 'no records'}")
    lines.append(f"  usable history per link: {h['usable_history_per_link']}")
    lines.append(f"  usable history KPI: {h['usable_history_kpi']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- kpi-check
def kpi_check(source, settings: Settings, site: str, end=None, references: int = 0) -> dict:
    """Every stored field of IntersectionPerfKpi and IntersectionPerfApproach per quarter-hour, for the analysis
    period (and the first `references` reference periods), next to the site's Neo4j EGRESS approaches: to check
    GreenShare (100% values, large changes), the LinkId/Bound to approach mapping, and CycleCvPct against
    CycleStability (e.g. a stability of 0)."""
    from ..timewin import reference_periods, zone
    rules, schema = settings.rules, settings.schema
    feeds = schema["influx"]["sources"]
    site = ids.site(site)
    period = period_ending(end, rules) if end else latest_period(rules)
    periods = [period] + reference_periods(period, rules)[0][:references]
    read = getattr(source, "raw_all", source.raw)
    approaches = source.approaches([site])
    out = {"site": site, "period": period.label(),
           "neo4j_egress": [{"link": a["link"], "street": a.get("street")} for a in approaches], "periods": []}
    kpi_feed, app_feed = feeds["site_kpi"], feeds["approach_perf"]
    for p in periods:
        entry = {"period": p.label(), "role": "analysis" if p is period else "reference", "kpi": {}, "approaches": {}}
        for key, feed, target in (("site_kpi", kpi_feed, "kpi"), ("approach_perf", app_feed, "approaches")):
            late = key in rules["alignment"].get("written_after_interval", [])
            try:
                rows = read(key, p.start, p.end + timedelta(minutes=15 if late else 0), [site])
            except Exception as exc:  # noqa: BLE001
                entry[target] = f"{type(exc).__name__}: {exc}"
                continue
            for r in rows:
                t = to_utc(r["time"])
                # the quarter-hour a record describes: the one it falls in, or for a record written after its
                # quarter-hour (alignment.written_after_interval) the one that ended before its stamp
                q = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0) if late else t
                if not to_utc(p.start) < q <= to_utc(p.end):
                    continue
                stamp = t.astimezone(zone(rules)).strftime("%H:%M:%S").removesuffix(":00")
                if target == "kpi":
                    entry["kpi"].setdefault(stamp, {})[r["field"]] = r["value"]
                else:
                    name = f"{ids.link(r.get(feed['link_tag']))} [{r.get(feed['bound_tag'])}]"
                    entry["approaches"].setdefault(name, {}).setdefault(stamp, {})[r["field"]] = r["value"]
        if isinstance(entry["approaches"], dict):
            feed_field = app_feed["fields"]["green_share"]
            totals = defaultdict(float)
            for per_stamp in entry["approaches"].values():
                for stamp, fields in per_stamp.items():
                    if isinstance(fields.get(feed_field), (int, float)):
                        totals[stamp] += fields[feed_field]
            entry[f"sum_of_{feed_field}_over_approaches"] = {k: round(v, 1) for k, v in sorted(totals.items())}
        out["periods"].append(entry)
    # Timing check: the 15-minute link volumes (stamped on the grid, end-labelled) around the analysis period, to
    # compare with the PerfApproach Volume of the records stamped :07/:22 and see which quarter-hour they describe.
    links = {a["link"] for a in approaches}
    feed = feeds["link_volume"]
    try:
        rows = source.raw("link_volume", period.start - timedelta(minutes=30), period.end, None)
        vols = {}
        for r in rows:
            link = ids.link(r.get(feed["link_tag"]))
            if link in links:
                stamp = to_utc(r["time"]).astimezone(zone(rules)).strftime("%H:%M")
                vols.setdefault(link, {})[stamp] = r["value"]
        out["link_volume_15min"] = {k: dict(sorted(v.items())) for k, v in sorted(vols.items())}
    except Exception as exc:  # noqa: BLE001
        out["link_volume_15min"] = f"{type(exc).__name__}: {exc}"
    return out


def kpi_check_text(k: dict) -> str:
    lines = [f"KPI check for site {k['site']}, {k['period']}",
             "  scats-aggregation/volume per link (15-min, stamped at the quarter-hour end): "
             + (json.dumps(k.get("link_volume_15min")) if k.get("link_volume_15min") is not None else "-"),
             "  Neo4j EGRESS approaches: " + ", ".join(f"{a['link']} ({a['street']})" for a in k["neo4j_egress"])]
    for e in k["periods"]:
        lines.append(f"  {e['role'][:3]} {e['period']}")
        if isinstance(e["kpi"], str) or not e["kpi"]:
            lines.append(f"      IntersectionPerfKpi: {e['kpi'] or 'no records'}")
        else:
            for stamp, fields in sorted(e["kpi"].items()):
                lines.append(f"      IntersectionPerfKpi {stamp}: " + ", ".join(f"{f}={_short(v)}" for f, v in sorted(fields.items())))
        if isinstance(e["approaches"], str) or not e["approaches"]:
            lines.append(f"      IntersectionPerfApproach: {e['approaches'] or 'no records'}")
            continue
        for name, per_stamp in sorted(e["approaches"].items()):
            for stamp, fields in sorted(per_stamp.items()):
                lines.append(f"      {name} {stamp}: " + ", ".join(f"{f}={_short(v)}" for f, v in sorted(fields.items())))
        for key, v in e.items():
            if key.startswith("sum_of_"):
                lines.append(f"      {key}: {v}")
    return "\n".join(lines)


def _short(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else v


def _speed_stamps(rows: list[dict], period, settings) -> dict:
    """{link: {times: local HH:MM:SS of the positive samples in [start, end), series: the distinct tag sets}}."""
    from collections import defaultdict
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ..timewin import to_utc, tz_name
    tz = ZoneInfo(tz_name(settings.rules))
    skip = {"time", "field", "value", "link", "Region", "DetectorGroupId"}
    start, end = to_utc(period.start), to_utc(period.end)
    out = defaultdict(lambda: {"times": [], "series": set()})
    for r in rows:
        t = r["time"] if isinstance(r["time"], datetime) else datetime.fromisoformat(str(r["time"]))
        t = to_utc(t)
        if not start <= t < end:
            continue
        link = str(r.get("link") or r.get("DetectorGroupId"))
        out[link]["times"].append(t.astimezone(tz).strftime("%H:%M:%S"))
        out[link]["series"].add(tuple(sorted((k, str(v)) for k, v in r.items() if k not in skip)))
    return {k: {"times": sorted(v["times"]), "series": [dict(x) for x in sorted(v["series"])]} for k, v in sorted(out.items())}

