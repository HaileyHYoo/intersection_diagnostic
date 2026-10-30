"""The data-source interface the screening and the templates read through.

Every method returns plain dict rows with internal identifiers (plain site numbers, normalised link IDs)
and logical field names (the keys of the schema's "fields" maps), so nothing above this layer depends on
bucket, measurement or tag names. Time-series methods return the raw records whose timestamps fall in
[start - tolerance, end + tolerance]; putting them on the grid is done by series.Aligner.

Rows:
    sites()                    {site, lat, lon, streets}
    detectors(sites)           {site, detector, active}
    approaches(sites)          {site, link, street}
    detector_counts(a, b)      {site, detector, time, value}          5-minute, raw
    link_volumes(a, b)         {link, time, value}                    15-minute
    site_kpi(a, b)             {site, field, time, value}             cycle_length, cycle_stability
    approach_perf(a, b)        {site, link, bound, field, time, value} green_share, has_green
    tomtom_site_kpi(s, a, b)   {site, field, time, value}
    tomtom_turn_kpi(s, a, b)   {site, approach, exit, field, time, value}
    tomtom_mapping(site)       {approach id: {link, street, direction}}
    cycle_length_fallback(a,b) {site, field, time, value}             only when fallbacks are enabled
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol


class DataUnavailable(RuntimeError):
    """A source cannot be read; the message names it. Never answered as zero."""


class DataSource(Protocol):
    region: str
    provenance: list

    def sites(self) -> list[dict]: ...
    def detectors(self, sites: list[str]) -> list[dict]: ...
    def approaches(self, sites: list[str]) -> list[dict]: ...
    def detector_counts(self, start: datetime, end: datetime) -> list[dict]: ...
    def link_volumes(self, start: datetime, end: datetime) -> list[dict]: ...
    def site_kpi(self, start: datetime, end: datetime) -> list[dict]: ...
    def approach_perf(self, start: datetime, end: datetime) -> list[dict]: ...
    def tomtom_site_kpi(self, site: str, start: datetime, end: datetime) -> list[dict]: ...
    def tomtom_turn_kpi(self, site: str, start: datetime, end: datetime) -> list[dict]: ...
    def tomtom_mapping(self, site: str) -> dict: ...
    def cycle_length_fallback(self, start: datetime, end: datetime) -> list[dict]: ...
