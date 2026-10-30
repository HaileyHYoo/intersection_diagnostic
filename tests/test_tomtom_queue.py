import io
import unittest
import zipfile
from datetime import datetime, timezone

from diagnostics.local.fake import FakeSource
from diagnostics.service import DiagnosticsService
from diagnostics.settings import Settings, load_rules
from diagnostics.sources.base import DataUnavailable
from diagnostics.sources.tomtom_queue import QueueArchive
from diagnostics.store import SQLiteStore

UTC = timezone.utc


def archive(csv_text: str, name="queue.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, csv_text)
        z.writestr("readme.txt", "ignored")
    return buf.getvalue()


class QueueArchiveTests(unittest.TestCase):
    spec = Settings().schema["tomtom_queue"]

    def test_parse_and_filter_to_the_period(self):
        calls = []
        blob = archive("time,approachId,queueLengthMeters\n"
                       "2026-10-26T21:00:00Z,A,10\n2026-10-26T21:01:00Z,A,12.5\n"
                       "2026-10-26T21:30:00Z,B,40\n2026-10-26T21:31:00Z,B,41\n2026-10-26T21:05:00Z,B,-1\n")
        q = QueueArchive(self.spec, fetch=lambda url, params: calls.append((url, params)) or blob)
        rows = q.rows("abc/1", datetime(2026, 10, 26, 21, 0, tzinfo=UTC), datetime(2026, 10, 26, 21, 30, tzinfo=UTC))
        self.assertEqual([(r["approach"], r["queue_m"]) for r in rows], [("A", 12.5), ("B", 40.0)])   # (start, end]; negative dropped
        self.assertIn("abc%2F1", calls[0][0])
        self.assertEqual(calls[0][1], {"from": "2026-10-26", "to": "2026-10-27"})                   # UTC and local dates
        q.rows("abc/1", datetime(2026, 10, 26, 21, 0, tzinfo=UTC), datetime(2026, 10, 26, 21, 30, tzinfo=UTC))
        self.assertEqual(len(calls), 1)                                                              # cached

    def test_queue_file_without_approach_column_fails(self):
        q = QueueArchive(self.spec, fetch=lambda url, params: archive("time,queueLengthMeters\n2026-10-26T21:01:00Z,5\n"))
        with self.assertRaises(DataUnavailable):
            q.rows("x", datetime(2026, 10, 26, 21, tzinfo=UTC), datetime(2026, 10, 26, 22, tzinfo=UTC))


class QueueInDiagnosisTests(unittest.TestCase):
    def diagnose(self, api_enabled, site):
        settings = Settings(rules=load_rules(overrides={"tomtom": {"api_enabled": api_enabled}}))
        source = FakeSource(settings.rules, settings.schema, "2026-10-27T08:30:00+11:00", n_sites=8)
        svc = DiagnosticsService(source, settings, SQLiteStore(":memory:"))
        run_id = svc.screen("2026-10-27T08:30")["run_id"]
        return svc.diagnose(run_id, site)["templates"]["D002"]

    def test_queue_off(self):
        d = self.diagnose(False, "4300")
        self.assertTrue(d["evidence"]["queue"].startswith("unavailable"))
        self.assertIsNone(d["evidence"]["comparison"]["per_approach"][0]["has_largest_queue"])
        self.assertIn("Queue length: unavailable", d["answer"]["road_user_impact"])

    def test_queue_on(self):
        d = self.diagnose(True, "4300")
        comp = d["evidence"]["comparison"]
        self.assertEqual(d["evidence"]["queue"], "available")
        self.assertEqual(comp["longest_queue"]["link"], "SWANN4300Q9")
        self.assertTrue(comp["per_approach"][0]["has_largest_queue"])
        west = next(a for a in d["evidence"]["approaches"] if a["link"].startswith("FLINW"))
        self.assertEqual(west["queue_minutes"], 15)                  # every other minute observed
        self.assertIn("longest mean queue", d["answer"]["road_user_impact"])

    def test_queue_disagreement(self):
        d = self.diagnose(True, "4303")
        self.assertEqual(d["answer"]["agreement"], "disagreement")
        self.assertFalse(d["evidence"]["comparison"]["per_approach"][0]["has_largest_queue"])


if __name__ == "__main__":
    unittest.main()
