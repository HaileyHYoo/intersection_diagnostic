"""Quarter-hour detail for a Red diagnosis (read on click, 17 Nov 2026).

The screening uses 30-minute values. A diagnosis also reads, for the analysis period only, every field of the two
IntersectionPerfKpi / IntersectionPerfApproach records and the two 15-minute link volumes, so that it can say when a
change started and which phases gained or lost green:

    {"quarters": ["08:00-08:15", "08:15-08:30"],
     "kpi": [{"AvgCycle": 120.0, "CycleCvPct": 0.0, ...}, {...}],
     "approaches": {link: [{"GreenShare": 65.1, "Phases": "A,C", ...}, {...}]},
     "volume": {link: [355.0, 290.0]}}

A record written after its quarter-hour (rules alignment.written_after_interval, e.g. stamped 08:22:08) describes the
quarter-hour that ended before its stamp (08:00-08:15), as in the screening. Nothing here changes a category; when the
read fails the diagnosis is written from the 30-minute values alone.
"""
from __future__ import annotations

from datetime import timedelta

from . import ids
from .timewin import Period, to_utc, zone


def _quarter(t, period: Period, late: bool) -> int | None:
    t = to_utc(t)
    q = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0) if late else t
    if not to_utc(period.start) < q <= to_utc(period.end):
        return None
    return int((q - to_utc(period.start)).total_seconds() // 900) - 1


def quarter_detail(source, settings, site: str, period: Period, links: list[str]) -> dict | None:
    rules, feeds = settings.rules, settings.schema["influx"]["sources"]
    n = period.minutes // 15
    if n < 2:
        return None
    tz = zone(rules)
    starts = [to_utc(period.start) + timedelta(minutes=15 * k) for k in range(n)]
    out = {"quarters": [f"{s.astimezone(tz):%H:%M}-{(s + timedelta(minutes=15)).astimezone(tz):%H:%M}" for s in starts],
           "kpi": [{} for _ in range(n)], "approaches": {}, "volume": {}}
    read = getattr(source, "raw_all", source.raw)
    late_feeds = rules["alignment"].get("written_after_interval", [])
    for key in ("site_kpi", "approach_perf"):
        feed, late = feeds[key], key in late_feeds
        for r in read(key, period.start, period.end + timedelta(minutes=15 if late else 0), [site]):
            k = _quarter(r["time"], period, late)
            if k is None or not 0 <= k < n:
                continue
            if key == "site_kpi":
                out["kpi"][k][r["field"]] = r["value"]
            else:
                link = ids.link(r.get(feed["link_tag"]))
                out["approaches"].setdefault(link, [{} for _ in range(n)])[k][r["field"]] = r["value"]
    feed, wanted = feeds["link_volume"], set(links)
    for r in source.raw("link_volume", period.start, period.end, None):
        link = ids.link(r.get(feed["link_tag"]))
        k = _quarter(r["time"], period, False)
        if link in wanted and k is not None and 0 <= k < n:
            out["volume"].setdefault(link, [None] * n)[k] = r["value"]
    return out


def safe_detail(source, settings, site: dict, period: Period) -> dict | None:
    """The detail, or None when it cannot be read (the diagnosis is then written from the 30-minute values)."""
    links = [a["link"] for a in (site.get("q1") or {}).get("approaches") or []]
    try:
        return quarter_detail(source, settings, site["site"], period, links)
    except Exception:  # noqa: BLE001 - supplementary only
        return None
