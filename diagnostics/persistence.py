"""Whether a site's condition recurs: its category at the same weekday and time in the previous weeks and in the
earlier periods of the same day, read from the archived screening logs (18 Nov 2026).

Only periods that were screened count; an unscreened period is reported as such, never as Normal. Both our log
format and the production contract's ScreeningLog are read (as in archive.site_history).
"""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache

from . import ids
from .archive import read_json
from .timewin import Period

FLAGGED = {"red", "amber_traffic", "amber_signal"}


def _log_categories(log: dict) -> dict[str, str]:
    if "metadata" in log:
        return {s["site"]: s["category"] for s in log.get("intersections", [])}
    names = {"detector_health_issue": "detector_health"}
    return {s["site_no"]: names.get(s["category"], s["category"]) for s in log.get("sites", [])}


def _category(archive, region: str, period: Period, site: str, cache: dict) -> str | None:
    """The site's category in the latest log of that period; None when the period was not screened."""
    folder = f"screening-logs/{region}/{period.day:%Y/%m/%d}/"       # a folder prefix works for both archives
    prefix = folder + f"{period.slot.replace(':', '')}_"
    if folder not in cache:
        cache[folder] = archive.keys(folder)
    keys = sorted(k for k in cache[folder] if k.startswith(prefix))
    if not keys:
        return None
    key = keys[-1]
    if key not in cache:
        cache[key] = _log_categories(read_json(archive, key))
    return cache[key].get(site, "not in the run")


def site_persistence(archive, region: str, site: str, period: Period, weeks: int = 4, earlier: int = 2,
                     cache: dict | None = None) -> dict | None:
    if archive is None:
        return None
    cache = {} if cache is None else cache
    site = ids.site(site)
    same_slot, same_day = [], []
    try:
        for k in range(1, weeks + 1):
            p = Period(period.start - timedelta(days=7 * k), period.end - timedelta(days=7 * k), period.tz)
            same_slot.append({"day": p.day.isoformat(), "category": _category(archive, region, p, site, cache)})
        for j in range(1, earlier + 1):
            step = timedelta(minutes=period.minutes * j)
            p = Period(period.start - step, period.end - step, period.tz)
            same_day.append({"period": f"{p.local_start:%H:%M}-{p.local_end:%H:%M}",
                             "category": _category(archive, region, p, site, cache)})
    except Exception:  # noqa: BLE001 - supplementary only
        return None
    screened = [x for x in same_slot if x["category"] not in (None, "not in the run")]
    return {"same_slot": same_slot, "same_day": same_day, "weeks_screened": len(screened),
            "weeks_flagged": sum(x["category"] in FLAGGED for x in screened),
            "weeks_red": sum(x["category"] == "red" for x in screened)}


LABELS = {"red": "Red", "amber_traffic": "Amber - traffic", "amber_signal": "Amber - signal", "normal": "Normal",
          "grey": "Grey", "detector_health": "Detector Health", None: "not screened", "not in the run": "not screened"}


def sentence(p: dict | None, slot: str | None = None) -> str | None:
    if not p or (not p["weeks_screened"] and all(x["category"] in (None, "not in the run") for x in p["same_day"])):
        return None
    parts = []
    if p["weeks_screened"]:
        parts.append(f"Red or Amber at this time in {p['weeks_flagged']} of the previous {p['weeks_screened']} screened "
                     f"weeks (Red in {p['weeks_red']})")
    today = [f"{x['period']} {LABELS.get(x['category'], x['category'])}" for x in p["same_day"]]
    if today:
        parts.append("earlier today: " + ", ".join(today))
    return "History: " + "; ".join(parts) + "."
