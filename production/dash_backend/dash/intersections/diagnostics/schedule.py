"""Scheduled screening: a possible later extension (methodology 18.6), not part of V1.

V1 screens only when an operator activates the layer, and every completed run is logged (archive.py). A
scheduled screening would fill the periods nobody looked at, so recurrence counts (how often a site is Red)
have a complete denominator. It needs nothing beyond the normal run:

    run_scheduled(service)        screen each new period as soon as its data is in (period end + latency)
    backfill(service, start, end) screen past periods one by one (historical back-calculation)

Both go through service.screen(), so a period already screened (by an operator or an earlier schedule) is
reused, not repeated, and each run writes its own JSON log. An OS scheduler can do the same by calling
`python main.py screen` at minutes 06 and 36 (with the 5-minute latency).
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from .timewin import floor_to, period_ending, to_utc

log = logging.getLogger(__name__)


def next_run_time(rules: dict, now: datetime | None = None) -> datetime:
    """When the next period's data is complete: the next period end plus the data latency (UTC)."""
    now = to_utc(now or datetime.now(UTC))
    minutes = rules["period_minutes"]
    latency = timedelta(minutes=rules.get("data_latency_minutes", 0))
    return floor_to(now - latency, minutes) + timedelta(minutes=minutes) + latency


def run_scheduled(service, stop: threading.Event | None = None, max_runs: int | None = None,
                  clock=lambda: datetime.now(UTC), on_run=None) -> int:
    """Screens every new period until `stop` is set (or `max_runs` runs). A failed run is logged and the
    schedule continues with the next period."""
    stop = stop or threading.Event()
    runs = 0
    while not stop.is_set() and (max_runs is None or runs < max_runs):
        due = next_run_time(service.settings.rules, clock())
        if stop.wait(max(0.0, (due - clock()).total_seconds())):
            break
        try:
            view = service.screen(now=due)
            log.info("Scheduled screening %s: %s", view["period"]["local"], view["counts"])
            if on_run:
                on_run(view)
        except Exception:  # noqa: BLE001 - keep the schedule alive
            log.exception("Scheduled screening at %s failed", due.isoformat())
        runs += 1
    return runs


def backfill(service, start, end, on_run=None) -> int:
    """Screens every period whose end is between `start` and `end`, both included (local times or datetimes)."""
    rules = service.settings.rules
    t, last = period_ending(start, rules).end, period_ending(end, rules).end
    step = timedelta(minutes=rules["period_minutes"])
    count = 0
    while t <= last:
        view = service.screen(t)
        count += 1
        if on_run:
            on_run(view)
        t += step
    return count
