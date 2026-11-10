"""Supplementary TomTom link speed for a selected Amber or Red site (methodology, speed addition).

For the site's incoming (EGRESS) links and the same 30-minute period as Q1/Q3:

    current speed     harmonic mean of the positive TomTom speed samples in [start, end) (schema link_speed),
                      as the chatbot's link-speed reading (binned_query how="pace")
    reference speed   the same feed's speed in the same 30 minutes of the reference weeks (the screening's own
                      reference periods: same weekday and slot, holidays left out), read on the click: the median
                      of the weeks' harmonic means, with the number of weeks (rules link_speed.reference_from_history).
                      Nothing is stored and no network-wide speed baseline exists. A separately configured reference
                      series (schema link_speed_reference) takes precedence when enabled.
    arm               the link's intersection arm from the production operational sheet (arms.py),
                      in the production backend only

It is display information only: Q1, Q2, Q3, the Q5 agreement and the category never read it. A link without
samples, or a feed that cannot be read, is reported as unavailable with the reason, never estimated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from . import arms as arm_lookup
from .templates.d001 import approach_label
from statistics import median

from .timewin import Period, reference_periods, reference_span, to_utc

METRIC = "TomTom link speed (km/h), harmonic mean of the samples in the 30-minute period"


def applies(category: str, rules: dict) -> bool:
    rule = rules.get("link_speed", {})
    return bool(rule.get("enabled")) and category in rule.get("categories", [])


def incoming_links(site: dict) -> list[dict]:
    """The site's EGRESS approaches as screened: evaluated ones first, then those without history."""
    q1 = site.get("q1") or {}
    seen, out = set(), []
    for a in q1.get("approaches", []) + q1.get("not_evaluated", []):
        if a["link"] not in seen:
            seen.add(a["link"])
            out.append(a)
    return out


def harmonic(values: list[float]) -> float | None:
    positive = [v for v in values if v is not None and v > 0]
    return len(positive) / sum(1 / v for v in positive) if positive else None


def _per_link(rows: list[dict], period: Period) -> dict[str, list[float]]:
    start, end = to_utc(period.start), to_utc(period.end)
    out = defaultdict(list)
    for r in rows:
        t = r["time"] if isinstance(r["time"], datetime) else datetime.fromisoformat(str(r["time"]))
        if start <= to_utc(t) < end:
            try:
                out[r["link"]].append(float(r["value"]))
            except (TypeError, ValueError):
                continue
    return out


def _stamps(rows: list[dict], period: Period) -> dict[str, list[datetime]]:
    """{link: sorted distinct stamps of positive samples in [start, end)}."""
    start, end = to_utc(period.start), to_utc(period.end)
    out = defaultdict(set)
    for r in rows:
        t = to_utc(r["time"] if isinstance(r["time"], datetime) else datetime.fromisoformat(str(r["time"])))
        try:
            positive = float(r["value"]) > 0
        except (TypeError, ValueError):
            continue
        if positive and start <= t < end:
            out[r["link"]].add(t)
    return {link: sorted(v) for link, v in out.items()}


def _minutes(stamps: list[datetime], period_minutes: int, step: float) -> int:
    """Minutes of the period with speed: each record stands for one interval of the feed (5 minutes,
    schema link_speed.interval_minutes), counted once per interval slot, so two records in one slot (e.g. two
    series of one link) are not counted twice and the result never exceeds the period."""
    if not stamps:
        return 0
    slot = step * 60
    slots = {int(t.timestamp() // slot) for t in stamps}
    return int(min(period_minutes, len(slots) * step))


def history_reference(source, links: list[str], period: Period, rules: dict) -> tuple[dict, dict, int]:
    """({link: median km/h}, {link: weeks with samples}, reference weeks read) from the same feed."""
    used, _ = reference_periods(period, rules)
    per_week = {link: [] for link in links}
    for ref in used:
        rows = _per_link(source.link_speeds(links, ref.start, ref.end), ref)
        for link in links:
            value = harmonic(rows.get(link, []))
            if value is not None:
                per_week[link].append(value)
    minimum = rules["history"]["min_observations"]                      # the screening's own minimum
    centre = median if rules.get("reference_value") == "median" else (lambda v: sum(v) / len(v))   # as Q1/Q3
    ref = {link: centre(v) for link, v in per_week.items() if len(v) >= minimum}
    return ref, {link: len(v) for link, v in per_week.items()}, len(used)


def link_speed(source, site: dict, period: Period, schema: dict, region: str | None = None,
               rules: dict | None = None) -> dict:
    approaches = incoming_links(site)
    links = [a["link"] for a in approaches]
    out = {"metric": METRIC, "period": period.label(), "unit": "km/h", "affects_classification": False,
           "available": False, "approaches": [], "reference": "unavailable", "notes": []}
    if not links:
        out["notes"].append("the site has no incoming (EGRESS) links")
        return out
    try:
        rows_now = source.link_speeds(links, period.start, period.end)
        current = _per_link(rows_now, period)
        stamps = _stamps(rows_now, period)
    except Exception as exc:  # noqa: BLE001 - supplementary: the reason is shown, nothing else changes
        out["notes"].append(f"TomTom link speed could not be read ({type(exc).__name__}: {str(exc)[:120]})")
        current, stamps = {}, {}
    ref_feed = schema.get("influx", {}).get("sources", {}).get("link_speed_reference", {})
    reference = {}
    if ref_feed.get("enabled"):
        try:
            reference = _per_link(source.link_speeds(links, period.start, period.end, key="link_speed_reference"), period)
            out["reference"] = "available"
        except Exception as exc:  # noqa: BLE001
            out["reference"] = f"unavailable - {type(exc).__name__}: {str(exc)[:120]}"
    elif rules and rules.get("link_speed", {}).get("reference_from_history"):
        try:
            hist, weeks, read = history_reference(source, links, period, rules)
            reference = {link: [v] for link, v in hist.items()}
            out["reference_weeks"] = weeks
            word = "median" if rules.get("reference_value") == "median" else "mean"
            out["reference"] = (f"{word} TomTom speed of the same 30 minutes, {reference_span(period, rules)}, read "
                                f"from the same feed; shown when at least {rules['history']['min_observations']} "
                                "weeks have samples")
        except Exception as exc:  # noqa: BLE001
            out["reference"] = f"unavailable - {type(exc).__name__}: {str(exc)[:120]}"
    else:
        out["reference"] = "unavailable - no existing historical reference speed is configured"
    step = schema.get("influx", {}).get("sources", {}).get("link_speed", {}).get("interval_minutes", 5)
    out["period_minutes"] = period.minutes
    arms, arm_note = arm_lookup.link_arms(source, site["site"], region) if region else ({}, None)
    if arm_note:
        out["notes"].append(arm_note)
    for a in approaches:
        values = current.get(a["link"], [])
        speed = harmonic(values)
        ref = harmonic(reference.get(a["link"], []))
        out["approaches"].append({"link": a["link"], "approach": approach_label(a), "street": a.get("street"),
                                  "arm": arms.get(a["link"]),
                                  "speed_kmh": None if speed is None else round(speed, 1),
                                  "samples": sum(1 for v in values if v > 0),
                                  "minutes": _minutes(stamps.get(a["link"], []), period.minutes, step),
                                  "reference_kmh": None if ref is None else round(ref, 1),
                                  "reference_weeks": out.get("reference_weeks", {}).get(a["link"]),
                                  "status": "available" if speed is not None else "unavailable"})
    missing = [a["approach"] for a in out["approaches"] if a["speed_kmh"] is None]
    out["available"] = len(missing) < len(out["approaches"])
    if missing:
        out["notes"].append("no TomTom speed for: " + ", ".join(missing))
    return out


def table(speed: dict) -> dict:
    """The report table (section 3, supplementary)."""
    fmt = lambda x: "-" if x is None else f"{x:.1f}"
    with_arm = any(a.get("arm") is not None for a in speed["approaches"])
    return {"title": "TomTom incoming-link speed (same 30 min)",
            "columns": ["Approach"] + (["Arm"] if with_arm else [])
                       + ["Speed (km/h)", f"Minutes with speed (of {speed.get('period_minutes', 30)})", "Reference (km/h)"]
                       + (["Reference weeks"] if "reference_weeks" in speed else []),
            "rows": [[a["approach"]] + (["-" if a.get("arm") is None else str(a["arm"])] if with_arm else [])
                     + [fmt(a["speed_kmh"]) if a["speed_kmh"] is not None else "unavailable",
                        str(a.get("minutes", a["samples"])), fmt(a["reference_kmh"])]
                     + ([str(a.get("reference_weeks") or 0)] if "reference_weeks" in speed else [])
                     for a in speed["approaches"]]}
