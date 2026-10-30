"""Inspect the live feeds for one site and a short window, and check the schema's assumptions.

    python main.py inspect --site 4397 --end 2026-10-27T08:30 --hours 2

For each feed it reports the record count, the interval between stamps, how many stamps fall on the
expected grid, duplicates, value types and sample rows; then:

    detectors   Neo4j BELONG_TO detector numbers (active and inactive) against the d[n] fields present
    links       Neo4j EGRESS links against volume DetectorGroupId and IntersectionPerfApproach LinkId,
                with the raw IDs that needed normalising
    stamps      the first and last stamps in the window, to confirm end-of-interval labelling

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
    return report


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
    for k, v in report["errors"].items():
        lines.append(f"  ERROR {k}: {v}")
    return "\n".join(lines)
