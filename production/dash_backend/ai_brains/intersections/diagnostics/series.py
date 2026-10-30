"""Put raw time-series records onto a fixed grid, one value per interval.

Records are labelled at the interval end (see timewin.py); a feed labelled at the interval start
(schema "timestamp_label": "start") is shifted by one interval first. A record exactly on a grid point keeps
it. One within alignment.tolerance_seconds of a grid point is moved to that point; this absorbs small write
delays without shifting a record into the neighbouring interval. Anything further off the grid is assigned
to the interval its stamp falls in (alignment.off_grid = "ceil": 03:22:05 -> the interval ending 03:30) or
dropped ("drop"). Live feeds are written off the grid at a fixed offset (5-minute detector counts at :03,
:08, ...; IntersectionPerfKpi/Approach at :07, :22, ...), so "ceil" is the default. When two records land on
the same interval, alignment.duplicates decides: "last" keeps the latest raw timestamp, "first" the
earliest. Every decision is counted so the inspection report can show how clean a feed is.

A missing or non-numeric value is missing, never zero.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from .timewin import to_utc


def number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def grid_point(stamp: datetime, step_minutes: int, tolerance_seconds: float, off_grid: str) -> datetime | None:
    stamp = to_utc(stamp)
    step = step_minutes * 60
    seconds = stamp.timestamp()
    below = seconds - seconds % step
    nearest = below if seconds - below <= step / 2 else below + step
    if abs(seconds - nearest) <= tolerance_seconds:
        return datetime.fromtimestamp(nearest, stamp.tzinfo)
    if off_grid == "ceil":
        return datetime.fromtimestamp(below + step, stamp.tzinfo)
    return None


class Aligner:
    def __init__(self, alignment: dict):
        self.tolerance = float(alignment.get("tolerance_seconds", 60))
        self.off_grid = alignment.get("off_grid", "drop")
        self.duplicates = alignment.get("duplicates", "last")
        self.stats = {"records": 0, "on_grid": 0, "snapped": 0, "off_grid_dropped": 0, "off_grid_ceiled": 0,
                      "duplicates": 0, "invalid_values": 0}

    def align(self, points, step_minutes: int, label: str = "end") -> dict[datetime, float]:
        """{interval end: value} from (timestamp, value) pairs of one series."""
        chosen: dict[datetime, tuple[datetime, float]] = {}
        shift = timedelta(minutes=step_minutes) if label == "start" else timedelta(0)
        for stamp, raw in points:
            self.stats["records"] += 1
            value = number(raw)
            if value is None:
                self.stats["invalid_values"] += 1
                continue
            stamp = to_utc(stamp) + shift
            point = grid_point(stamp, step_minutes, self.tolerance, self.off_grid)
            if point is None:
                self.stats["off_grid_dropped"] += 1
                continue
            if point == stamp:
                self.stats["on_grid"] += 1
            elif abs((point - stamp).total_seconds()) <= self.tolerance:
                self.stats["snapped"] += 1
            else:
                self.stats["off_grid_ceiled"] += 1
            if point in chosen:
                self.stats["duplicates"] += 1
                keep_new = stamp > chosen[point][0] if self.duplicates == "last" else stamp < chosen[point][0]
                if not keep_new:
                    continue
            chosen[point] = (stamp, value)
        return {point: value for point, (_, value) in chosen.items()}


def window_values(series: dict[datetime, float], ends: list[datetime]) -> list[float] | None:
    """The values at every required interval end, or None if any one is missing."""
    values = [series.get(end) for end in ends]
    return None if any(v is None for v in values) else values


def ends_between(start: datetime, end: datetime, step_minutes: int) -> list[datetime]:
    out, t = [], to_utc(start) + timedelta(minutes=step_minutes)
    while t <= to_utc(end):
        out.append(t)
        t += timedelta(minutes=step_minutes)
    return out
