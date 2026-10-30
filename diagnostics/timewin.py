"""Analysis periods, quarter-hours and reference periods.

Timestamps are labelled at the END of the interval they cover: a 15-minute record stamped 01:15 covers
01:00-01:15, and a 5-minute record stamped 01:05 covers 01:00-01:05. A 30-minute analysis period ending
at T is therefore made of the two quarter-hour records stamped T-15 and T, and the Q2 detector window is
the twelve 5-minute records stamped T-55 ... T.

Melbourne's UTC offset is a whole number of hours (+10 or +11), so flooring to 30 minutes in UTC gives
the same boundaries as flooring in local time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .vic_calendar import exclusion_reason

UTC = timezone.utc


def tz_name(rules: dict) -> str:
    """The region's local time zone. Data are stored in UTC; inputs, slots, weekdays, holidays and display
    use local time, and queries convert to UTC (as the chatbot does from its Region tag)."""
    zones = rules.get("region_timezones", {})
    if rules["region"] in zones:
        return zones[rules["region"]]
    if rules.get("timezone"):
        return rules["timezone"]
    raise ValueError(f"No time zone configured for region {rules['region']} (rules region_timezones).")


def zone(rules: dict) -> ZoneInfo:
    return ZoneInfo(tz_name(rules))


def to_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Timestamps must carry a timezone.")
    return value.astimezone(UTC)


def floor_to(value: datetime, minutes: int) -> datetime:
    value = to_utc(value)
    step = minutes * 60
    seconds = int(value.timestamp())
    return datetime.fromtimestamp(seconds - seconds % step, UTC)


@dataclass(frozen=True)
class Period:
    """One analysis period, (start, end] in UTC, with its local slot."""
    start: datetime
    end: datetime
    tz: str = "Australia/Melbourne"

    @property
    def local_start(self) -> datetime:
        return self.start.astimezone(ZoneInfo(self.tz))

    @property
    def local_end(self) -> datetime:
        return self.end.astimezone(ZoneInfo(self.tz))

    @property
    def day(self) -> date:
        """Local date of the period (its start), e.g. 23:30-24:00 belongs to the earlier day."""
        return self.local_start.date()

    @property
    def weekday(self) -> int:
        return self.day.weekday()

    @property
    def slot(self) -> str:
        """Local clock time of the period start, e.g. '17:30'; the same slot on another day is comparable."""
        return self.local_start.strftime("%H:%M")

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def key(self) -> str:
        return self.end.strftime("%Y-%m-%dT%H:%M:%SZ")

    def label(self) -> str:
        a, b = self.local_start, self.local_end
        return f"{a.strftime('%a %d %b %Y')} {a.strftime('%H:%M')}-{b.strftime('%H:%M')} ({self.tz})"

    def interval_ends(self, step_minutes: int, window_minutes: int | None = None) -> list[datetime]:
        """Record stamps (interval ends) covering the window that ends with this period."""
        window = window_minutes or self.minutes
        count = window // step_minutes
        return [self.end - timedelta(minutes=step_minutes * i) for i in reversed(range(count))]

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "local": self.label(),
                "end_local": self.local_end.strftime("%Y-%m-%dT%H:%M"),
                "slot": self.slot, "weekday": self.local_start.strftime("%A"), "key": self.key}


def latest_period(rules: dict, now: datetime | None = None) -> Period:
    """The latest completed period, allowing for the configured data latency."""
    now = to_utc(now or datetime.now(UTC)) - timedelta(minutes=rules.get("data_latency_minutes", 0))
    minutes = rules["period_minutes"]
    end = floor_to(now, minutes)
    return Period(end - timedelta(minutes=minutes), end, tz_name(rules))


def period_ending(end: datetime | str, rules: dict) -> Period:
    """The period that ends at a given time; the time must fall on a period boundary."""
    tz = zone(rules)
    if isinstance(end, str):
        end = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    end = to_utc(end)
    minutes = rules["period_minutes"]
    if floor_to(end, minutes) != end:
        raise ValueError(f"A period must end on a {minutes}-minute boundary (got {end.astimezone(tz):%H:%M}).")
    return Period(end - timedelta(minutes=minutes), end, tz_name(rules))


def period_at(day: date, slot: str, rules: dict) -> Period:
    """The period that starts at local clock time `slot` (HH:MM) on `day`."""
    tz = zone(rules)
    start = datetime.combine(day, time.fromisoformat(slot)).replace(tzinfo=tz)
    start = to_utc(start)
    return Period(start, start + timedelta(minutes=rules["period_minutes"]), tz_name(rules))


def reference_periods(period: Period, rules: dict) -> tuple[list[Period], dict[str, str]]:
    """Same weekday and slot in each of the previous N weeks, without the excluded days.

    Returns (periods used, {date: reason} skipped). Excluded weeks are not replaced by earlier ones.
    """
    history = rules["history"]
    used, skipped = [], {}
    for k in range(1, history["weeks"] + 1):
        day = period.day - timedelta(days=7 * k)
        reason = exclusion_reason(day, history.get("exclude", {}))
        if reason:
            skipped[day.isoformat()] = reason
        else:
            used.append(period_at(day, period.slot, rules))
    return used, skipped
