"""Intersection arm number per incoming road link, for LinkSpeed.arm (production contract).

Reuses the production backend's own operational-sheet modules, exactly as its TomTom layer does
(tomtom/sources.py sheet()): the site's SCATS operational sheet (OperationalSheetClient), the graph's
detector-to-link rows (operational_sheet.LINK_CYPHER) and the link rule (operational_sheet.build_sheet):
a link's lowest-position active detectors name its arm through the sheet's DetectorNo -> ArmNo. A link whose
detectors split evenly over arms, or have no sheet detector, has no arm (None), never a guess.

Outside the production backend (local runs) those modules do not exist and every arm is None.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)
PACKAGE = "dash_backend.ai_brains.intersections"

_client = None
_lock = threading.Lock()


def _modules():
    """(OperationalSheetClient, build_sheet, LINK_CYPHER, OperationalSheetDB), or None outside production."""
    try:
        from importlib import import_module
        client = import_module(PACKAGE + ".db.operational_sheet_client").OperationalSheetClient
        sheet = import_module(PACKAGE + ".operational_sheet")
        store = import_module(PACKAGE + ".operational_sheet_store").OperationalSheetDB
        return client, sheet.build_sheet, sheet.LINK_CYPHER, store
    except ImportError:
        return None


def link_arms(source, site: str, region: str) -> tuple[dict[str, int], str | None]:
    """({link_id: arm_no}, note). The note says why arms are missing when the lookup could not run."""
    modules = _modules()
    graph = getattr(source, "graph", None)
    if modules is None or graph is None:
        return {}, None                                       # local run: no operational sheet here
    Client, build_sheet, link_cypher, SheetDB = modules
    global _client
    try:
        with _lock:
            if _client is None:
                _client = Client(region_tag=region)
        found = _client.get_site(str(site))
        if not found:
            return {}, "arm numbers unavailable: the site has no operational sheet"
        doc, snapshot = found
        db = SheetDB([(doc, snapshot)], origin=getattr(_client, "location", None))
        try:
            rows = graph.rows(link_cypher, {"ids": [str(site), "S" + str(site)], "region": region})
            summary = build_sheet(db, str(site), link_rows=rows, link_error=None)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - arms are display context; the speed is still shown
        log.warning("Arm lookup for site %s failed: %s", site, exc)
        return {}, f"arm numbers unavailable ({type(exc).__name__})"
    links = (summary or {}).get("links", [])
    return {str(l["link_id"]): l["arm_no"] for l in links if l.get("link_id") and l.get("arm_no") is not None}, None
