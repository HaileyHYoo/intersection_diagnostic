"""Approved diagnostic templates D001 (Q4) and D002 (Q5), invoked directly from a map click."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict]:
    entries = json.loads((Path(__file__).resolve().parent / "catalog.json").read_text(encoding="utf-8"))
    return {e["id"]: e for e in entries}


def definition(template_id: str) -> dict:
    return catalog()[template_id]
