"""`python main.py tomtom-check --site 4397 3426 --end 2026-11-10T08:30`: what TomTom data a site has (20 Nov 2026).

For the methodology owner's request to show TomTom values per approach with their usual values, as for SCATS:
- the site's entry in the TomTom mapping file (junction UUID, approaches and their links);
- TomTom delay per approach now (IntersectionTurnKpi: approach delay, control delay; quarter-hours observed), and
  in each reference week of the screening (same weekday and slot, holidays left out), with the median of the weeks
  that have a value and their number;
- the site-level TomTom KPIs (IntersectionKpi) now and usual;
- the Junction Analytics queue per approach now (and usual when --queue-history is given: one archive call per week);
- the TomTom link speed of the site's EGRESS links now and usual.
Read only. Writes out/tomtom_check_{site}.json.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean, median

DELAYS = ("approach_delay", "control_delay")


def _r(x, d=1):
    return None if x is None else round(float(x), d)


def _delays(rows: list[dict], period, rules: dict) -> dict[str, dict]:
    """{TomTom approach: {approach_delay, control_delay, quarters}}: plain means of the period's quarter-hour records
    (put on the grid as in the report, D002), negative delay = 0."""
    from ..series import Aligner
    aligner = Aligner(rules["alignment"])
    ends = set(period.interval_ends(15))
    series = defaultdict(list)
    for r in rows:
        if r["field"] in DELAYS and r.get("value") is not None:
            series[(r["approach"], r["exit"], r["field"])].append((r["time"], float(r["value"])))
    acc, quarters = defaultdict(lambda: defaultdict(list)), defaultdict(set)
    for (approach, _exit, field), points in series.items():
        for t, v in aligner.align(points, 15, "end").items():
            if t in ends:
                acc[approach][field].append(max(v, 0.0))
                quarters[approach].add(t)
    return {a: {**{f: _r(mean(v)) for f, v in fields.items()}, "quarters": len(quarters[a])} for a, fields in acc.items()}


def _site_kpi(rows: list[dict]) -> dict:
    acc = defaultdict(list)
    for r in rows:
        if r.get("value") is not None:
            acc[r["field"]].append(float(r["value"]))
    return {f: _r(mean(v), 2) for f, v in acc.items()}


def _queue(source, site, period) -> tuple[dict, str]:
    try:
        rows = source.tomtom_queue(site, period.start, period.end)
    except Exception as exc:  # noqa: BLE001
        return {}, f"unavailable - {type(exc).__name__}: {str(exc)[:160]}"
    per = defaultdict(list)
    for r in rows:
        per[r["approach"]].append(float(r["queue_m"]))
    return {a: {"mean_m": _r(mean(v)), "max_m": _r(max(v)), "records": len(v)} for a, v in per.items()}, \
        ("available" if per else "no rows for the period")


def _usual(weeks: list[dict], key: str) -> dict:
    """{item: {usual (median), weeks}} over the weeks that have a value."""
    vals = defaultdict(list)
    for w in weeks:
        for item, v in (w.get(key) or {}).items():
            if v is not None:
                vals[item].append(v)
    return {item: {"usual": _r(median(v)), "weeks": len(v)} for item, v in vals.items()}


def raw_stamps(source, site: str, period, rules: dict) -> dict:
    """Record stamps (local time) of the TomTom feeds from 30 minutes before to 30 minutes after the period, to see
    how they are labelled: at the quarter-hour (end or start label) or some minutes after it (written after)."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from ..timewin import to_utc, tz_name
    tz = ZoneInfo(tz_name(rules))
    a, b = period.start - timedelta(minutes=30), period.end + timedelta(minutes=30)
    out = {}
    try:
        per = defaultdict(set)
        for r in source.tomtom_turn_kpi(site, a, b):
            per[f"{r['approach']} {r['field']}"].add(to_utc(r["time"]).astimezone(tz).strftime("%H:%M:%S"))
        out["turn_kpi"] = {k: sorted(v) for k, v in sorted(per.items()) if k.endswith(("approach_delay", "sample_count"))}
    except Exception as exc:  # noqa: BLE001
        out["turn_kpi"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    try:
        out["site_kpi"] = sorted({to_utc(r["time"]).astimezone(tz).strftime("%H:%M:%S") for r in source.tomtom_site_kpi(site, a, b)})
    except Exception as exc:  # noqa: BLE001
        out["site_kpi"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    try:
        rows = source.tomtom_turn_kpi(site, a, b)
        out["turn_kpi_values"] = sorted((to_utc(r["time"]).astimezone(tz).strftime("%H:%M:%S"), r["approach"], r["exit"],
                                         r["field"], r["value"]) for r in rows
                                        if r["field"] in ("approach_delay", "control_delay", "sample_count"))
    except Exception:  # noqa: BLE001
        pass
    return out


def check(source, settings, site: str, period, queue_history: bool = False) -> dict:
    from ..link_speed import harmonic
    from ..timewin import reference_periods
    rules = settings.rules
    mapping = source.tomtom_mapping(site)
    approaches = mapping.get("approaches", {})
    links = [a["link"] for a in source.approaches([site])]
    out = {"site": site, "period": period.label(),
           "mapping": {"in_file": bool(approaches), "junction_uuid": mapping.get("uuid"),
                       "approaches": {k: {"link": v.get("link"), "street": v.get("street"), "direction": v.get("direction"),
                                          "egress_of_site": v.get("link") in links}
                                      for k, v in approaches.items()}},
           "egress_links": links}

    def read(p):
        w = {"period": p.label()}
        try:
            w["delay"] = _delays(source.tomtom_turn_kpi(site, p.start, p.end), p, rules)
        except Exception as exc:  # noqa: BLE001
            w["delay_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        try:
            w["site_kpi"] = _site_kpi(source.tomtom_site_kpi(site, p.start, p.end))
        except Exception as exc:  # noqa: BLE001
            w["site_kpi_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        try:
            per = defaultdict(list)
            from ..timewin import to_utc
            a, b = to_utc(p.start), to_utc(p.end)
            for r in source.link_speeds(links, p.start, p.end):           # [start, end), as link_speed.py
                if r.get("value") and float(r["value"]) > 0 and a <= to_utc(r["time"]) < b:
                    per[r["link"]].append(float(r["value"]))
            w["speed"] = {l: _r(harmonic(v)) for l, v in per.items()}
        except Exception as exc:  # noqa: BLE001
            w["speed_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return w

    out["now"] = read(period)
    out["now"]["queue"], out["now"]["queue_status"] = _queue(source, site, period)
    refs, skipped = reference_periods(period, rules)
    out["reference_skipped"] = skipped
    out["weeks"] = []
    for p in refs:
        w = read(p)
        if queue_history:
            q, status = _queue(source, site, p)
            w["queue"] = {a: v["mean_m"] for a, v in q.items()}
            w["queue_status"] = status
        out["weeks"].append(w)
    flat = [{**w, "approach_delay": {a: v.get("approach_delay") for a, v in (w.get("delay") or {}).items()},
             "control_delay": {a: v.get("control_delay") for a, v in (w.get("delay") or {}).items()}} for w in out["weeks"]]
    out["usual"] = {"approach_delay": _usual(flat, "approach_delay"), "control_delay": _usual(flat, "control_delay"),
                    "site_kpi": _usual(out["weeks"], "site_kpi"), "speed": _usual(out["weeks"], "speed")}
    if queue_history:
        out["usual"]["queue_mean"] = _usual(out["weeks"], "queue")
    return out


def raw_text(r: dict) -> str:
    lines = ["  raw stamps (local) of the TomTom feeds, period -30 min to +30 min:"]
    if isinstance(r.get("turn_kpi"), str):
        lines.append(f"    IntersectionTurnKpi: {r['turn_kpi']}")
    else:
        for k, v in r.get("turn_kpi", {}).items():
            lines.append(f"    IntersectionTurnKpi {k}: {', '.join(v)}")
    site_kpi = r.get("site_kpi")
    lines.append("    IntersectionKpi: " + (site_kpi if isinstance(site_kpi, str) else ", ".join(site_kpi) or "none"))
    return "\n".join(lines)


def text(c: dict) -> str:
    m = c["mapping"]
    lines = [f"TomTom check for site {c['site']}, {c['period']}",
             f"  mapping file: {'yes' if m['in_file'] else 'NO (Q5 cannot tie TomTom approaches to the site links)'}"
             + (f", junction {m['junction_uuid']}, {len(m['approaches'])} approaches" if m["in_file"] else ""),
             f"  reference weeks read: {len(c['weeks'])}" + (f" (skipped: {', '.join(f'{d} {r}' for d, r in c['reference_skipped'].items())})"
                                                              if c["reference_skipped"] else "")]
    now, u = c["now"], c["usual"]
    for key in ("delay_error", "site_kpi_error", "speed_error"):
        if key in now:
            lines.append(f"  {key}: {now[key]}")
    names = {a: (v["street"] or "?") + f" [{(v['direction'] or '?')[:1]}] -> {v['link']}" for a, v in m["approaches"].items()}
    delay_ids = sorted(set(now.get("delay") or {}) | set(u["approach_delay"]) | set(u["control_delay"]))
    lines.append(f"  TomTom delay per approach (s): now / usual (weeks)  [{len(delay_ids)} approaches with records]")
    for a in delay_ids:
        n = (now.get("delay") or {}).get(a, {})
        ad, cd = u["approach_delay"].get(a, {}), u["control_delay"].get(a, {})
        lines.append(f"    {a} {names.get(a, '(not in the mapping file)')}: approach {n.get('approach_delay')} / "
                     f"{ad.get('usual')} ({ad.get('weeks', 0)}), control {n.get('control_delay')} / {cd.get('usual')} "
                     f"({cd.get('weeks', 0)}), quarter-hours now {n.get('quarters', 0)}")
    lines.append("  TomTom site KPIs: " + (", ".join(f"{f} {v} / {u['site_kpi'].get(f, {}).get('usual')} "
                                                     f"({u['site_kpi'].get(f, {}).get('weeks', 0)})"
                                                     for f, v in (now.get("site_kpi") or {}).items()) or "none"))
    lines.append(f"  queue now: {now['queue_status']}")
    for a, q in (now.get("queue") or {}).items():
        uq = u.get("queue_mean", {}).get(a, {})
        lines.append(f"    {a} {names.get(a, '')}: mean {q['mean_m']} m, max {q['max_m']} m, {q['records']} records"
                     + (f"; usual mean {uq.get('usual')} m ({uq.get('weeks', 0)} weeks)" if "queue_mean" in u else ""))
    lines.append("  link speed (km/h): now / usual (weeks)")
    for link in c["egress_links"]:
        s = u["speed"].get(link, {})
        lines.append(f"    {link}: {(now.get('speed') or {}).get(link)} / {s.get('usual')} ({s.get('weeks', 0)})")
    return "\n".join(lines)
