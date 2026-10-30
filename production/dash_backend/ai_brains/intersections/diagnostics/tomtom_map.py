"""TomTom ApproachId -> Neo4j EGRESS link per SCATS site, from the chatbot's verified mapping file."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import ids


@lru_cache(maxsize=4)
def load(path: str) -> dict[str, dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    out = {}
    for key, record in raw.get("sites", {}).items():
        approaches = {}
        for approach_id, entry in (record.get("approaches") or {}).items():
            link = entry.get("link_id")
            if isinstance(link, list):
                link = link[0] if link else None
            approaches[str(approach_id)] = {"link": ids.link(link), "street": entry.get("street_name"),
                                            "direction": entry.get("direction"), "name": entry.get("name")}
        out[ids.site(record.get("site_id") or key)] = approaches
    return out
