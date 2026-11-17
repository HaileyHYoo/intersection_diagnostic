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
            mates.append({"site": other, "name": None, "category": "not screened"})
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
    for bucket in sorted({f["bucket"] for f in settings.schema["influx"]["sources"].values()} | {feed["bucket"]}):
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
