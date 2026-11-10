"""Victorian calendar used to exclude unusual days from the historical baseline.

The tables are the ones the intersection chatbot uses (tomtom/anomaly.py). Excluded from the history:
public holidays, the two daylight-saving change days, and the year-end period (24 Dec - 1 Jan).
Each group can be switched off in rules.json (history.exclude). An excluded week is not replaced by an
earlier one: the baseline uses the remaining weeks of the eight.
"""
from __future__ import annotations

from datetime import date

PUBLIC_HOLIDAYS = {
    "2024-01-01": "New Year's Day", "2024-01-26": "Australia Day", "2024-03-11": "Labour Day",
    "2024-03-29": "Good Friday", "2024-03-30": "Saturday before Easter", "2024-03-31": "Easter Sunday",
    "2024-04-01": "Easter Monday", "2024-04-25": "Anzac Day", "2024-06-10": "King's Birthday",
    "2024-09-27": "AFL Grand Final Friday", "2024-11-05": "Melbourne Cup", "2024-12-25": "Christmas Day",
    "2024-12-26": "Boxing Day",
    "2025-01-01": "New Year's Day", "2025-01-27": "Australia Day (observed)", "2025-03-10": "Labour Day",
    "2025-04-18": "Good Friday", "2025-04-19": "Saturday before Easter", "2025-04-20": "Easter Sunday",
    "2025-04-21": "Easter Monday", "2025-04-25": "Anzac Day", "2025-06-09": "King's Birthday",
    "2025-09-26": "AFL Grand Final Friday", "2025-11-04": "Melbourne Cup", "2025-12-25": "Christmas Day",
    "2025-12-26": "Boxing Day",
    "2026-01-01": "New Year's Day", "2026-01-26": "Australia Day", "2026-03-09": "Labour Day",
    "2026-04-03": "Good Friday", "2026-04-04": "Saturday before Easter", "2026-04-05": "Easter Sunday",
    "2026-04-06": "Easter Monday", "2026-04-25": "Anzac Day", "2026-06-08": "King's Birthday",
    "2026-09-25": "AFL Grand Final Friday", "2026-11-03": "Melbourne Cup", "2026-12-25": "Christmas Day",
    "2026-12-26": "Boxing Day", "2026-12-28": "Boxing Day (substitute)",
    "2027-01-01": "New Year's Day", "2027-01-26": "Australia Day", "2027-03-08": "Labour Day",
    "2027-03-26": "Good Friday", "2027-03-27": "Saturday before Easter", "2027-03-28": "Easter Sunday",
    "2027-03-29": "Easter Monday", "2027-04-25": "Anzac Day", "2027-06-14": "King's Birthday",
    "2027-09-24": "AFL Grand Final Friday", "2027-11-02": "Melbourne Cup", "2027-12-25": "Christmas Day",
    "2027-12-26": "Boxing Day", "2027-12-27": "Christmas Day (substitute)", "2027-12-28": "Boxing Day (substitute)",
}

# VIC daylight saving ends on the first Sunday of April and starts on the first Sunday of October.
DST_CHANGE_DAYS = {
    "2024-04-07", "2024-10-06", "2025-04-06", "2025-10-05",
    "2026-04-05", "2026-10-04", "2027-04-04", "2027-10-03",
}

YEAR_END_PERIODS = [
    ("2024-12-24", "2025-01-01"), ("2025-12-24", "2026-01-01"),
    ("2026-12-24", "2027-01-01"), ("2027-12-24", "2028-01-01"),
]

COVERED_YEARS = (2024, 2027)


def _iso(d: date) -> str:
    return d.isoformat()


def is_year_end(d: date) -> bool:
    return any(a <= _iso(d) <= b for a, b in YEAR_END_PERIODS)


def exclusion_reason(d: date, exclude: dict) -> str | None:
    """Why a day is left out of the history, or None when it is kept."""
    if exclude.get("public_holidays", True) and _iso(d) in PUBLIC_HOLIDAYS:
        return "public holiday: " + PUBLIC_HOLIDAYS[_iso(d)]
    if exclude.get("dst_change_days", True) and _iso(d) in DST_CHANGE_DAYS:
        return "daylight-saving change day"
    if exclude.get("year_end", True) and is_year_end(d):
        return "year-end period (24 Dec - 1 Jan)"
    return None


def day_note(d: date) -> str | None:
    """A note for the analysis day itself; it is still screened."""
    if _iso(d) in PUBLIC_HOLIDAYS:
        return f"The analysis day is a public holiday ({PUBLIC_HOLIDAYS[_iso(d)]}); traffic may differ from the usual pattern."
    if _iso(d) in DST_CHANGE_DAYS:
        return "The analysis day is a daylight-saving change day."
    if is_year_end(d):
        return "The analysis day is in the year-end period (24 Dec - 1 Jan)."
    if not COVERED_YEARS[0] <= d.year <= COVERED_YEARS[1]:
        return f"The holiday table covers {COVERED_YEARS[0]}-{COVERED_YEARS[1]}; holidays outside it are not excluded."
    return None
