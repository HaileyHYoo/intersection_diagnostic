import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from diagnostics.settings import Settings, load_rules
from diagnostics.sources.live import LiveSource

ROOT = Path(__file__).resolve().parent.parent
T = datetime(2026, 10, 26, 21, 30, tzinfo=timezone.utc)


class StubInflux:
    def __init__(self, rows):
        self.rows_by_measurement, self.queries = rows, []

    def rows(self, flux):
        self.queries.append(flux)
        for measurement, rows in self.rows_by_measurement.items():
            if f'r._measurement == "{measurement}"' in flux:
                return rows
        return []


class StubGraph:
    def __init__(self, rows):
        self.rows_by_name, self.calls = rows, []

    def rows(self, cypher, params):
        self.calls.append((cypher, params))
        for marker, rows in self.rows_by_name.items():
            if marker in cypher:
                return rows
        return []


class LiveSourceTests(unittest.TestCase):
    def source(self, influx=None, graph=None, settings=None):
        return LiveSource(settings or Settings(), influx=StubInflux(influx or {}), graph=StubGraph(graph or {}))

    def test_detector_fields_are_parsed(self):
        src = self.source({"volume": [
            {"SiteNo": "4397", "field": "d[12]", "time": T, "value": "7"},
            {"SiteNo": "4397", "field": "DetectorCount", "time": T, "value": 8},
            {"SiteNo": "4397", "field": "d[3]", "time": T, "value": 4}]})
        rows = src.detector_counts(T, T, sites=["4397"])
        self.assertEqual([(r["detector"], r["value"]) for r in rows], [(12, "7"), (3, 4)])
        flux = src.influx.queries[0]
        self.assertIn('from(bucket: "scats")', flux)
        self.assertIn('r["Region"] == "AU-VIC-Melbourne"', flux)
        self.assertIn('set: ["4397"]', flux)                       # plain site number in the scats bucket

    def test_link_ids_are_normalised_and_fields_logical(self):
        src = self.source({"IntersectionPerfApproach": [
            {"SiteNo": "S4268", "LinkId": "'21FF5WFG64", "Bound": "E", "field": "GreenShare", "time": T, "value": 50.0},
            {"SiteNo": "S4268", "LinkId": "'21FF5WFG64", "Bound": "E", "field": "DemandShare", "time": T, "value": 1.0}]})
        rows = src.approach_perf(T, T, sites=["4268"])
        self.assertEqual(rows, [{"site": "4268", "field": "green_share", "time": T, "value": 50.0,
                                 "link": "21FF5WFG64", "bound": "E"}])
        self.assertIn('set: ["S4268"]', src.influx.queries[0])

    def test_graph_rows(self):
        src = self.source(graph={"BELONG_TO": [{"site": 4397, "detector": "5", "active": True},
                                               {"site": "4397", "detector": None, "active": True}],
                                 "EGRESS": [{"site": "4397", "link_id": " 'LONSQ9R9Q9XR", "street": "Lonsdale Street"}]})
        self.assertEqual(src.detectors(["4397"]), [{"site": "4397", "detector": 5, "active": True}])
        self.assertEqual(src.approaches(["4397"]), [{"site": "4397", "link": "LONSQ9R9Q9XR", "street": "Lonsdale Street"}])
        self.assertEqual(src.graph.calls[0][1]["region"], "AU-VIC-Melbourne")

    def test_tomtom_mapping_file(self):
        mapping = self.source().tomtom_mapping("S162")
        self.assertEqual(mapping["uuid"], "69381a5ce4939943f584e975")
        self.assertEqual(mapping["approaches"]["1996207257"]["link"], "BURWW3QWW2VW")
        self.assertEqual(mapping["approaches"]["1996207257"]["direction"], "WEST")
        self.assertIn("-1731433707", mapping["exits"])
        self.assertEqual(self.source().tomtom_mapping("99999"), {"uuid": None, "approaches": {}, "exits": {}})

    def test_queue_off_by_default(self):
        from diagnostics.sources.base import DataUnavailable
        with self.assertRaises(DataUnavailable):
            self.source().tomtom_queue("162", T, T)

    def test_fallback_only_when_enabled(self):
        from diagnostics.measures import Measures
        from diagnostics import timewin
        settings = Settings(rules=load_rules(overrides={"fallbacks": {"enabled": True}}))
        period = timewin.period_ending("2026-10-27T08:30", settings.rules)
        rows = [{"RegionNo": "1", "SubsystemNo": "39", "field": "ActiveCycleLength", "time": t, "value": 90}
                for t in period.interval_ends(15)]
        src = self.source({"subsystem_status": rows}, settings=settings)
        values, origin = Measures(src, settings.rules, settings.schema).site_kpi([period])
        self.assertEqual(values[period.key]["314"]["cycle_length"], 90)
        self.assertEqual(origin[period.key]["314"]["cycle_length"], "fallback")


class ProductionBuildTests(unittest.TestCase):
    def test_production_package_matches_source(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "build_production.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
