"""Supplementary TomTom link speed for a selected Amber or Red site (methodology, speed addition).

For the site's incoming (EGRESS) links and the same 30-minute period as Q1/Q3:

    current speed     harmonic mean of the positive TomTom speed samples in [start, end) (schema link_speed),
                      as the chatbot's link-speed reading (binned_query how="pace")
    reference speed   an existing historical reference speed, only when one is configured
                      (schema link_speed_reference); no speed baseline is calculated here

It is display information only: Q1, Q2, Q3, the Q5 agreement and the category never read it. A link without
samples, or a feed that cannot be read, is reported as unavailable with the reason, never estimated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .templates.d001 import approach_label
from .timewin import Period, to_utc

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


def link_speed(source, site: dict, period: Period, schema: dict) -> dict:
    approaches = incoming_links(site)
    links = [a["link"] for a in approaches]
    out = {"metric": METRIC, "period": period.label(), "unit": "km/h", "affects_classification": False,
           "available": False, "approaches": [], "reference": "unavailable", "notes": []}
    if not links:
        out["notes"].append("the site has no incoming (EGRESS) links")
        return out
    try:
        current = _per_link(source.link_speeds(links, period.start, period.end), period)
    except Exception as exc:  # noqa: BLE001 - supplementary: the reason is shown, nothing else changes
        out["notes"].append(f"TomTom link speed could not be read ({type(exc).__name__}: {str(exc)[:120]})")
        current = {}
    ref_feed = schema.get("influx", {}).get("sources", {}).get("link_speed_reference", {})
    reference = {}
    if ref_feed.get("enabled"):
        try:
            reference = _per_link(source.link_speeds(links, period.start, period.end, key="link_speed_reference"), period)
            out["reference"] = "available"
        except Exception as exc:  # noqa: BLE001
            out["reference"] = f"unavailable - {type(exc).__name__}: {str(exc)[:120]}"
    else:
        out["reference"] = "unavailable - no existing historical reference speed is configured"
    for a in approaches:
        values = current.get(a["link"], [])
        speed = harmonic(values)
        ref = harmonic(reference.get(a["link"], []))
        out["approaches"].append({"link": a["link"], "approach": approach_label(a), "street": a.get("street"),
                                  "speed_kmh": None if speed is None else round(speed, 1),
                                  "samples": sum(1 for v in values if v > 0),
                                  "reference_kmh": None if ref is None else round(ref, 1),
                                  "status": "available" if speed is not None else "unavailable"})
    missing = [a["approach"] for a in out["approaches"] if a["speed_kmh"] is None]
    out["available"] = len(missing) < len(out["approaches"])
    if missing:
        out["notes"].append("no TomTom speed for: " + ", ".join(missing))
    return out


def table(speed: dict) -> dict:
    """The report table (section 3, supplementary)."""
    fmt = lambda x: "-" if x is None else f"{x:.1f}"
    return {"title": "Supplementary: TomTom incoming-link speed (same 30 min; not used for the classification)",
            "columns": ["Approach", "Speed (km/h)", "Samples", "Reference (km/h)"],
            "rows": [[a["approach"], fmt(a["speed_kmh"]) if a["speed_kmh"] is not None else "unavailable",
                      str(a["samples"]), fmt(a["reference_kmh"])] for a in speed["approaches"]]}
