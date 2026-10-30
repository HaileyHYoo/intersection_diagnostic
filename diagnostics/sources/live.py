"""The live source: InfluxDB time series and the Neo4j network, as described by the schema."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime

from .. import ids, tomtom_map
from ..settings import Settings, connection_env, package_file
from .base import DataUnavailable
from .graph import GraphReader
from .influx import InfluxReader, build_flux, padded


class LiveSource:
    def __init__(self, settings: Settings | None = None, influx: InfluxReader | None = None,
                 graph: GraphReader | None = None):
        self.settings = settings or Settings()
        self.schema = self.settings.schema
        self.region = self.settings.region
        self.tolerance = self.settings.rules["alignment"]["tolerance_seconds"]
        self.strip = self.schema.get("ids", {}).get("strip_chars", ids.DEFAULT_STRIP)
        self._influx, self._graph = influx, graph
        self.provenance: list[dict] = []

    # -------------------------------------------------------------- connections (opened on first use)
    @property
    def influx(self) -> InfluxReader:
        if self._influx is None:
            env = connection_env()
            self._influx = InfluxReader(env["influx_url"], env["influx_token"], env["influx_org"], env["influx_timeout_ms"])
        return self._influx

    @property
    def graph(self) -> GraphReader:
        if self._graph is None:
            env = connection_env()
            self._graph = GraphReader(env["neo4j_uri"], env["neo4j_user"], env["neo4j_password"], env["neo4j_database"])
        return self._graph

    def _feed(self, key: str) -> dict:
        return self.schema["influx"]["sources"][key]

    def _query(self, key: str, start: datetime, end: datetime, *, fields=None, field_regex=None, tag_in=None,
               feed: dict | None = None) -> list[dict]:
        feed = feed or self._feed(key)
        a, b = padded(start, end, self.tolerance)
        flux = build_flux(feed["bucket"], feed["measurement"], a, b, region_tag=self.schema["influx"]["region_tag"],
                          region=self.region, filters=feed.get("filters"), fields=fields, field_regex=field_regex,
                          tag_in=tag_in)
        rows = self.influx.rows(flux)
        self.provenance.append({"source": "InfluxDB", "feed": key, "bucket": feed["bucket"],
                                "measurement": feed["measurement"], "start": a.isoformat(), "stop": b.isoformat(),
                                "rows": len(rows)})
        return rows

    def _graph_rows(self, name: str, params: dict) -> list[dict]:
        rows = self.graph.rows(self.schema["graph"][name], {"region": self.region, **params})
        self.provenance.append({"source": "Neo4j", "query": name, "rows": len(rows)})
        return rows

    # -------------------------------------------------------------- network
    def sites(self) -> list[dict]:
        out = {}
        for r in self._graph_rows("sites", {}):
            site = ids.site(r.get("site"))
            if site and site not in out:
                out[site] = {"site": site, "lat": r.get("lat"), "lon": r.get("lon"), "streets": r.get("streets")}
        return list(out.values())

    def detectors(self, sites: list[str]) -> list[dict]:
        rows = self._graph_rows("detectors", {"sites": list(sites)})
        out = []
        for r in rows:
            try:
                number = int(r.get("detector"))
            except (TypeError, ValueError):
                continue
            out.append({"site": ids.site(r.get("site")), "detector": number, "active": r.get("active") is True})
        return out

    def approaches(self, sites: list[str]) -> list[dict]:
        return [{"site": ids.site(r.get("site")), "link": ids.link(r.get("link_id"), self.strip), "street": r.get("street")}
                for r in self._graph_rows("approaches", {"sites": list(sites)}) if ids.link(r.get("link_id"), self.strip)]

    # -------------------------------------------------------------- time series
    def detector_counts(self, start: datetime, end: datetime) -> list[dict]:
        feed = self._feed("detector_counts")
        pattern = re.compile(re.escape(feed["detector_field"]).replace(r"\{n\}", r"(\d+)") + "$")
        out = []
        for r in self._query("detector_counts", start, end, field_regex=feed["detector_field_regex"]):
            m = pattern.match(str(r.get("field")))
            if m:
                out.append({"site": ids.site(r.get(feed["site_tag"])), "detector": int(m.group(1)),
                            "time": r["time"], "value": r["value"]})
        return out

    def link_volumes(self, start: datetime, end: datetime) -> list[dict]:
        feed = self._feed("link_volume")
        return [{"link": ids.link(r.get(feed["link_tag"]), self.strip), "time": r["time"], "value": r["value"]}
                for r in self._query("link_volume", start, end, fields=list(feed["fields"].values()))]

    def _logical(self, feed: dict, rows: list[dict], extra: dict) -> list[dict]:
        names = {physical: logical for logical, physical in feed["fields"].items()}
        out = []
        for r in rows:
            if r.get("field") in names:
                row = {"site": ids.site(r.get(feed["site_tag"])), "field": names[r["field"]], "time": r["time"],
                       "value": r["value"]}
                row.update({key: convert(r.get(tag)) for key, (tag, convert) in extra.items()})
                out.append(row)
        return out

    def site_kpi(self, start: datetime, end: datetime) -> list[dict]:
        feed = self._feed("site_kpi")
        return self._logical(feed, self._query("site_kpi", start, end, fields=list(feed["fields"].values())), {})

    def approach_perf(self, start: datetime, end: datetime) -> list[dict]:
        feed = self._feed("approach_perf")
        rows = self._query("approach_perf", start, end, fields=list(feed["fields"].values()))
        return self._logical(feed, rows, {"link": (feed["link_tag"], lambda v: ids.link(v, self.strip)),
                                          "bound": (feed["bound_tag"], lambda v: v)})

    def tomtom_site_kpi(self, site: str, start: datetime, end: datetime) -> list[dict]:
        feed = self._feed("tomtom_site_kpi")
        rows = self._query("tomtom_site_kpi", start, end, fields=list(feed["fields"].values()),
                           tag_in=(feed["site_tag"], [ids.site_tag(site, feed["site_format"])]))
        return self._logical(feed, rows, {})

    def tomtom_turn_kpi(self, site: str, start: datetime, end: datetime) -> list[dict]:
        feed = self._feed("tomtom_turn_kpi")
        rows = self._query("tomtom_turn_kpi", start, end, fields=list(feed["fields"].values()),
                           tag_in=(feed["site_tag"], [ids.site_tag(site, feed["site_format"])]))
        return self._logical(feed, rows, {"approach": (feed["approach_tag"], str), "exit": (feed["exit_tag"], str)})

    def tomtom_mapping(self, site: str) -> dict:
        return tomtom_map.load(str(package_file(self.schema["tomtom_mapping"]["file"]))).get(ids.site(site), {})

    def cycle_length_fallback(self, start: datetime, end: datetime) -> list[dict]:
        """Subsystem active cycle length, given to every site of the subsystem (stated as a fallback)."""
        feed = self.schema["influx"]["fallbacks"]["cycle_length"]
        mapping = json.loads(package_file(feed["site_map_file"]).read_text(encoding="utf-8"))
        members = defaultdict(list)
        for site, entry in mapping.items():
            members[(str(entry["region_no"]), str(entry["subsystem_no"]))].append(ids.site(site))
        rows = self._query("cycle_length_fallback", start, end, fields=[feed["field"]], feed=feed)
        out = []
        for r in rows:
            for site in members.get((str(r.get(feed["region_no_tag"])), str(r.get(feed["subsystem_no_tag"]))), []):
                out.append({"site": site, "field": "cycle_length", "time": r["time"], "value": r["value"],
                            "origin": "subsystem_status"})
        return out

    def close(self) -> None:
        for conn in (self._influx, self._graph):
            if conn is not None:
                conn.close()


__all__ = ["LiveSource", "DataUnavailable"]
