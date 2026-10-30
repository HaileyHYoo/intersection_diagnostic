"""TomTom identities per SCATS site, from the chatbot's verified mapping file.

For each site: the junction UUID (queue archive), and every TomTom approach and exit with its Neo4j link,
street and cardinal travel direction (used to name movements).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import ids

TRAVEL_BEARING = {"NORTH": 0, "EAST": 90, "SOUTH": 180, "WEST": 270}


def movement(approach_direction, exit_direction) -> str | None:
    """Turn type from the cardinal travel directions; Melbourne drives on the left."""
    a = TRAVEL_BEARING.get(str(approach_direction or "").upper())
    b = TRAVEL_BEARING.get(str(exit_direction or "").upper())
    if a is None or b is None:
        return None
    return {0: "through", 90: "right", 180: "u_turn", 270: "left"}[(b - a) % 360]


def _arms(entries: dict) -> dict:
    out = {}
    for tomtom_id, entry in (entries or {}).items():
        link = entry.get("link_id")
        if isinstance(link, list):
            link = link[0] if link else None
        out[str(tomtom_id)] = {"link": ids.link(link), "street": entry.get("street_name"),
                               "direction": entry.get("direction"), "name": entry.get("name")}
    return out


@lru_cache(maxsize=4)
def load(path: str) -> dict[str, dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    out = {}
    for key, record in raw.get("sites", {}).items():
        out[ids.site(record.get("site_id") or key)] = {"uuid": record.get("junction_uuid"),
                                                       "approaches": _arms(record.get("approaches")),
                                                       "exits": _arms(record.get("exits"))}
    return out


EMPTY = {"uuid": None, "approaches": {}, "exits": {}}
