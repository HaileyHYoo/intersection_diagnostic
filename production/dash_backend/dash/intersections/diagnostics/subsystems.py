"""SCATS control context of a site: its Region and subsystem, and the other sites of that subsystem (18 Nov 2026).

SCATS Region sets the cycle length (and the split and link plans) per subsystem, from the strategic measurements of
the subsystem; the local controller then extends, terminates or skips phases within that plan. A cycle change seen at
one site is therefore usually a subsystem decision when the site shares its subsystem (in the four-period review,
14 of 16 cycle-length findings at sites with an assessed subsystem neighbour were shared by that neighbour).

The membership comes from data/site_subsystem_map.json (static: marriages between subsystems and the critical site
are not in it). Subsystem 0 is read as "no subsystem".
"""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache

from . import ids
from .settings import package_file
from .stats import ABNORMAL

MAP_FILE = "data/site_subsystem_map.json"


@lru_cache(maxsize=1)
def _map() -> tuple[dict, dict]:
    raw = json.loads(package_file(MAP_FILE).read_text(encoding="utf-8"))
    sites, members = {}, defaultdict(list)
    for site, e in raw.items():
        s = ids.site(site)
        sites[s] = e
        if e.get("subsystem_no"):
            members[(e["region_no"], e["subsystem_no"])].append(s)
    return sites, {k: sorted(v, key=lambda x: int(x) if x.isdigit() else x) for k, v in members.items()}


def membership(site: str) -> dict | None:
    """{"region", "region_no", "subsystem", "members"} or None when the site is not in a subsystem."""
    sites, members = _map()
    e = sites.get(ids.site(site))
    if not e or not e.get("subsystem_no"):
        return None
    return {"region": e.get("region_name"), "region_no": e["region_no"], "subsystem": e["subsystem_no"],
            "members": members[(e["region_no"], e["subsystem_no"])]}


def _measure(s: dict, key: str) -> dict | None:
    c = ((s.get("q3") or {}).get("components") or {}).get(key)
    if not c:
        return None
    r = lambda x: None if x is None else round(float(x), 1)
    return {"status": c["status"], "current": r(c.get("current")), "usual": r(c.get("usual")),
            "direction": c.get("direction")}


def context(site: str, lookup) -> dict | None:
    """The control context of a site, with the same-period results of the other sites of its subsystem.
    lookup(site_no) returns that site's screening record of the same run, or None."""
    m = membership(site)
    if not m:
        return None
    mates = []
    for other in m["members"]:
        if other == ids.site(site):
            continue
        s = lookup(other)
        if not s:
            mates.append({"site": other, "name": None, "category": "not in the screened network"})
            continue
        mates.append({"site": other, "name": s.get("name"), "category": s.get("category"),
                      "cycle_length_s": _measure(s, "cycle_length"), "cycle_stability": _measure(s, "cycle_stability")})
    return {**m, "single_site": len(m["members"]) == 1, "others": mates}


def shared_cycle(ctx: dict | None, own: dict) -> dict:
    """How the site's cycle compares with the other assessed sites of its subsystem:
    {"same_change": [...], "same_value": [...], "usual": [...], "assessed": n}."""
    out = {"same_change": [], "same_value": [], "usual": [], "assessed": 0}
    if not ctx:
        return out
    for o in ctx["others"]:
        c = o.get("cycle_length_s")
        if not c or c.get("current") is None:
            continue
        out["assessed"] += 1
        name = f"{o['site']}" + (f" {o['name']}" if o.get("name") else "")
        if own.get("current") is not None and abs(c["current"] - own["current"]) < 1.0:
            out["same_value"].append(name)
        if c["status"] == ABNORMAL and own.get("status") == ABNORMAL and c.get("direction") == own.get("direction"):
            out["same_change"].append(name)
        elif c["status"] != ABNORMAL:
            out["usual"].append(name)
    return out


STATUS_FIELDS = ("DegreeOfSaturation", "RequiredCycleLength", "ActiveCycleLength")


def _status_rows(source, settings, m: dict, period) -> list[dict]:
    feed = dict(settings.schema["influx"]["fallbacks"]["cycle_length"])
    feed["filters"] = {feed["region_no_tag"]: str(m["region_no"]), feed["subsystem_no_tag"]: str(m["subsystem"])}
    rows = source._query("subsystem_status", period.start, period.end, fields=list(STATUS_FIELDS), feed=feed)
    out = {}
    for r in rows:
        e = out.setdefault(str(r["time"]), {"time": r["time"], "critical": r.get("CriticalSite")})
        e[r["field"]] = r["value"]
    return [e for e in out.values() if all(isinstance(e.get(f), (int, float)) for f in STATUS_FIELDS)]


def _summary(rows: list[dict], period) -> dict | None:
    """DS, required (RL) and active cycle (CL) of the subsystem over the period and by quarter-hour. DS swings widely
    from cycle to cycle (often 40-160 in one half-hour), so its mean is compared with usual as well as its median."""
    from statistics import median, pstdev
    from .timewin import to_utc
    if not rows:
        return None
    r1 = lambda x: None if x is None else round(float(x), 1)

    def block(rs):
        if not rs:
            return None
        ds = [r["DegreeOfSaturation"] for r in rs]
        cl = [r["ActiveCycleLength"] for r in rs]
        rl = [r["RequiredCycleLength"] for r in rs]
        return {"records": len(rs), "ds_median": r1(median(ds)), "ds_mean": r1(sum(ds) / len(ds)), "ds_max": r1(max(ds)),
                "ds_at_least_100": sum(d >= 100 for d in ds), "rl_mean": r1(sum(rl) / len(rl)),
                "cl_mean": r1(sum(cl) / len(cl)), "cl_min": r1(min(cl)), "cl_max": r1(max(cl)), "cl_sd": r1(pstdev(cl)),
                "cl_above_rl": sum(c >= q + 3 for c, q in zip(cl, rl)), "cl_below_rl": sum(c <= q - 3 for c, q in zip(cl, rl)),
                "cl_with_rl": sum(abs(c - q) <= 2 for c, q in zip(cl, rl))}
    start = to_utc(period.start)
    quarters = [[], []]
    for r in rows:
        k = int((to_utc(r["time"]) - start).total_seconds() // 900)
        if 0 <= k < 2:
            quarters[k].append(r)
    crit = next((r["critical"] for r in rows if r.get("critical")), None)
    # the period itself: a record stamped just before the start or at the end belongs to the cycle before or after
    inside = quarters[0] + quarters[1]
    return {**block(inside or rows), "critical_site": ids.site(crit) if crit else None, "by_quarter": [block(q) for q in quarters]}


def status_context(source, settings, site: str, period, reference: bool = True) -> dict | None:
    """The subsystem's DS, required and active cycle in the period ("now") and the median of the same values in the
    reference weeks ("usual"), from subsystem_status (one small query per week). None when not readable."""
    from statistics import median
    from .timewin import reference_periods
    m = membership(site)
    if not m or not hasattr(source, "_query"):
        return None
    try:
        now = _summary(_status_rows(source, settings, m, period), period)
    except Exception:  # noqa: BLE001 - supplementary only
        return None
    if not now:
        return None
    usual, weeks = {}, 0
    if reference:
        refs = []
        for p in reference_periods(period, settings.rules)[0]:
            try:
                s = _summary(_status_rows(source, settings, m, p), p)
            except Exception:  # noqa: BLE001
                s = None
            if s:
                refs.append(s)
        weeks = len(refs)
        if weeks >= settings.rules["history"]["min_observations"]:
            usual = {k: round(median(r[k] for r in refs), 1) for k in ("ds_median", "ds_mean", "ds_max", "cl_mean", "rl_mean", "cl_sd")
                     if all(r.get(k) is not None for r in refs)}
            usual["ds_at_least_100_share"] = round(median(r["ds_at_least_100"] / r["records"] for r in refs), 2)
    return {"now": now, "usual": usual, "weeks": weeks}


def status_probe(source, settings, site: str, period) -> dict:
    """Every field and tag of the subsystem_status records of the site's subsystem in the period (to see which
    subsystem measures are stored: DS, required and active cycle length, plan numbers, critical site ...), and the
    measurements of the SCATS buckets."""
    m = membership(site)
    out = {"site": ids.site(site), "period": period.label(), "membership": m, "records": {}, "measurements": {}}
    feed = dict(settings.schema["influx"]["fallbacks"]["cycle_length"])
    if m:
        feed["filters"] = {feed["region_no_tag"]: str(m["region_no"]), feed["subsystem_no_tag"]: str(m["subsystem"])}
        try:
            rows = source._query("subsystem_status", period.start, period.end, feed=feed)
            for r in rows:
                stamp = str(r["time"])
                tags = {k: v for k, v in r.items() if k not in ("time", "field", "value")}
                entry = out["records"].setdefault(stamp, {"tags": tags, "fields": {}})
                entry["fields"][r["field"]] = r["value"]
        except Exception as exc:  # noqa: BLE001
            out["records"] = f"{type(exc).__name__}: {exc}"
    influx = getattr(source, "influx", None)
    buckets = {f.get("bucket") for f in settings.schema["influx"]["sources"].values()} | {feed["bucket"]}
    for bucket in sorted(b for b in buckets if b):
        try:
            rows = influx.rows(f'import "influxdata/influxdb/schema"\nschema.measurements(bucket: "{bucket}")')
            out["measurements"][bucket] = sorted(str(r["value"]) for r in rows)
        except Exception as exc:  # noqa: BLE001
            out["measurements"][bucket] = f"{type(exc).__name__}: {exc}"
    return out


def status_probe_text(p: dict) -> str:
    m = p["membership"]
    lines = [f"Subsystem check for site {p['site']}, {p['period']}",
             "  membership (site_subsystem_map.json): " + (f"Region {m['region']} ({m['region_no']}), subsystem "
                                                          f"{m['subsystem']}, sites {', '.join(m['members'])}" if m
                                                          else "not in a subsystem")]
    if isinstance(p["records"], str) or not p["records"]:
        lines.append(f"  subsystem_status: {p['records'] or 'no records'}")
    else:
        first = next(iter(p["records"].values()))
        lines.append("  subsystem_status tags: " + ", ".join(f"{k}={v}" for k, v in sorted(first["tags"].items())))
        for stamp, e in sorted(p["records"].items()):
            lines.append(f"  subsystem_status {stamp}: " + ", ".join(f"{k}={v}" for k, v in sorted(e["fields"].items())))
    for bucket, names in p["measurements"].items():
        lines.append(f"  measurements in {bucket}: " + (", ".join(names) if isinstance(names, list) else names))
    return "\n".join(lines)
