"""`python main.py measure-check`: the tag and field keys of SCATS measurements not yet used, and a site's records in a
period, to see whether they can support the diagnosis (split plan, phases, signal groups, cycle time ...)."""
from __future__ import annotations

import re
from datetime import timedelta

from .. import ids
from ..sources.influx import flux_string, flux_time

DEFAULT = [("scats", "scats_split_plan"), ("scats", "site_phase"), ("scats", "site_signal_group"),
           ("scats-aggregation", "intersection_cycle_time"), ("scats-aggregation", "link_green_percentage"),
           ("scats-aggregation", "site_phase"), ("scats-aggregation", "congestion"), ("scats-aggregation", "hazard")]


def _keys(influx, fn: str, bucket: str, measurement: str, period) -> list[str] | str:
    flux = (f'import "influxdata/influxdb/schema"\nschema.{fn}(bucket: {flux_string(bucket)}, '
            f'measurement: {flux_string(measurement)}, start: {flux_time(period.start - timedelta(days=1))}, '
            f'stop: {flux_time(period.end)})')
    try:
        return sorted(str(r["value"]) for r in influx.rows(flux))
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:160]}"


def check(source, settings, site: str, period, measurements=None, limit: int = 40) -> dict:
    influx = source.influx
    site = ids.site(site)
    out = {"site": site, "period": period.label(), "measurements": []}
    for bucket, m in measurements or DEFAULT:
        e = {"bucket": bucket, "measurement": m,
             "tags": _keys(influx, "measurementTagKeys", bucket, m, period),
             "fields": _keys(influx, "measurementFieldKeys", bucket, m, period), "site_tag": None, "records": []}
        tags = e["tags"] if isinstance(e["tags"], list) else []
        site_tag = next((t for t in tags if t.lower() in ("siteno", "site_no", "site", "scats_site_no", "sitenumber")),
                        next((t for t in tags if "site" in t.lower() and "critical" not in t.lower()), None))
        e["site_tag"] = site_tag
        if not site_tag and "DetectorGroupId" in tags:
            site_tag = e["site_tag"] = "DetectorGroupId"
        if site_tag:
            if site_tag == "DetectorGroupId":            # stored link IDs may carry extra characters: match by content
                links = [re.sub(r"[^A-Za-z0-9]", "", a["link"]) for a in source.approaches([site])]
                cond = f"r[{flux_string(site_tag)}] =~ /{'|'.join(links)}/" if links else "false"
            else:
                values = [site, f"S{site}", site.zfill(4), f"S{site.zfill(4)}"]
                cond = " or ".join(f"r[{flux_string(site_tag)}] == {flux_string(v)}" for v in dict.fromkeys(values))
            flux = (f"from(bucket: {flux_string(bucket)})\n  |> range(start: {flux_time(period.start)}, "
                    f"stop: {flux_time(period.end + timedelta(minutes=15))})\n"
                    f"  |> filter(fn: (r) => r._measurement == {flux_string(m)})\n  |> filter(fn: (r) => {cond})\n"
                    # values of different types (string, bool, float) cannot share one table: compare as text
                    f"  |> map(fn: (r) => ({{r with _value: string(v: r._value)}}))\n"
                    f"  |> group()\n  |> sort(columns: [\"_time\"])\n  |> limit(n: {limit})")
            try:
                e["records"] = [{k: (str(v) if k == "time" else v) for k, v in r.items()} for r in influx.rows(flux)]
            except Exception as exc:  # noqa: BLE001
                e["records"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        out["measurements"].append(e)
    return out


def text(c: dict) -> str:
    lines = [f"Measurement check for site {c['site']}, {c['period']}"]
    for e in c["measurements"]:
        lines.append(f"  {e['bucket']}/{e['measurement']}")
        lines.append(f"    tags: {e['tags'] if isinstance(e['tags'], str) else ', '.join(e['tags'])}")
        lines.append(f"    fields: {e['fields'] if isinstance(e['fields'], str) else ', '.join(e['fields'])}")
        if not e["site_tag"]:
            lines.append("    records: no site tag found")
        elif isinstance(e["records"], str):
            lines.append(f"    records: {e['records']}")
        else:
            lines.append(f"    records for {e['site_tag']}={c['site']}: {len(e['records'])} (first ones)")
            for r in e["records"][:12]:
                tags = ", ".join(f"{k}={v}" for k, v in sorted(r.items()) if k not in ("time", "field", "value"))
                lines.append(f"      {r['time']}  {r['field']}={r['value']}  [{tags}]")
    return "\n".join(lines)
