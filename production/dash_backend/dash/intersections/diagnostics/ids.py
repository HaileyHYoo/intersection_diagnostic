"""Identifier normalisation shared by every source.

Site numbers appear as "4397" (scats bucket, Neo4j Detector.intersect_id) and "S4397" (scats-aggregation
bucket); internally a site is always the plain number "4397".

Link IDs can arrive with characters added by spreadsheet auto-formatting, typically a leading apostrophe
("'MSMJ835J8C7"). The schema's ids.strip_chars are removed from both ends only; characters inside an ID
are part of it and are kept, so two different IDs never collapse into one.
"""
from __future__ import annotations

DEFAULT_STRIP = "'\"`‘’“” \t\r\n"


def site(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip(DEFAULT_STRIP)
    if text[:1] in ("S", "s") and text[1:].isdigit():
        text = text[1:]
    if text.isdigit():
        text = str(int(text))
    return text or None


def site_tag(value, fmt: str) -> str:
    """The site number as a source stores it: fmt 'S' -> 'S4397', 'plain' -> '4397'."""
    plain = site(value)
    return "S" + plain if fmt == "S" else plain


def link(value, strip_chars: str = DEFAULT_STRIP) -> str | None:
    if value is None:
        return None
    text = str(value).strip(strip_chars)
    return text or None
