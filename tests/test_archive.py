import gzip
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from diagnostics import archive, schedule, timewin
from diagnostics.contract import adapter, core
from diagnostics.contract import intersections_diagnostics_schemas as S
from diagnostics.local.fake import FakeSource
from diagnostics.service import DiagnosticsService
from diagnostics.settings import Settings
from diagnostics.store import SQLiteStore

END = "2026-10-27T08:30"


class BrokenArchive:
    def put_new(self, key, data):
        raise OSError("bucket unreachable")


class FakeS3:
    """The three S3 calls S3Archive makes, with conditional-write semantics."""

    class Error(Exception):
        def __init__(self, code):
            self.response = {"Error": {"Code": code}}

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None):
        if IfNoneMatch == "*" and Key in self.objects:
            raise self.Error("PreconditionFailed")
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self.Error("NoSuchKey")
        body = self.objects[Key]
        return {"Body": type("B", (), {"read": lambda self: body})()}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        return {"Contents": [{"Key": k} for k in self.objects if k.startswith(Prefix)], "IsTruncated": False}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings()
        self.source = FakeSource(self.settings.rules, self.settings.schema, END + ":00+11:00", n_sites=20)
        self.archive = archive.LocalArchive(self.tmp.name)
        self.svc = DiagnosticsService(self.source, self.settings, SQLiteStore(":memory:"), archive=self.archive)

    def logs(self):
        return self.archive.keys("screening-logs/")

    def test_one_log_per_completed_run(self):
        first = self.svc.screen(END)
        self.svc.screen(END)                                            # a second viewer: cached, no new log
        self.assertEqual(self.logs(), [f"screening-logs/AU-VIC-Melbourne/2026/10/27/0800_{first['run_id']}.json"])
        self.svc.archive_run(first["run_id"])                           # a retry never overwrites
        self.assertEqual(len(self.logs()), 1)

    def test_log_content_follows_18_3(self):
        run_id = self.svc.screen(END)["run_id"]
        log = archive.read_json(self.archive, self.logs()[0])
        meta = log["metadata"]
        self.assertEqual((meta["run_id"], meta["status"], meta["region"]), (run_id, "complete", "AU-VIC-Melbourne"))
        self.assertEqual(meta["period"]["end_local"], END)
        self.assertTrue(meta["started"] and meta["completed"])
        self.assertTrue(meta["baseline_version"].startswith("2026-W44."))
        self.assertEqual(len(log["intersections"]), len(log["sites"]))
        self.assertIn({"site": "4315", "name": "Flinders Street / Spencer Street", "category": "normal"},
                      log["intersections"])                             # Normal sites too, though not drawn
        dh = next(d for d in log["detector_health_issues"] if d["site"] == "4318")
        self.assertEqual(dh["threshold"], 10)
        self.assertEqual([d["detector"] for d in dh["failed_detectors"]], [3])
        self.assertIn("count_60min", dh["failed_detectors"][0])
        traffic = next(t for t in log["traffic_abnormalities"] if t["site"] == "4300")
        self.assertTrue({"current", "usual", "p_low", "p_high", "pct_difference"} <= set(traffic["approaches"][0]))
        signal = next(t for t in log["signal_abnormalities"] if t["site"] == "4300")
        self.assertEqual(signal["cycle_stability"]["status"], "ABNORMAL")
        self.assertTrue(all(g["reasons"] for g in log["insufficient_data"]))
        self.assertEqual(sum(log["summary"]["counts"].values()), len(log["intersections"]))

    def test_baseline_snapshot_is_referenced_by_the_log(self):
        self.svc.screen(END)
        log = archive.read_json(self.archive, self.logs()[0])
        key = log["metadata"]["baseline_snapshot"]
        self.assertEqual(key, f"baselines/AU-VIC-Melbourne/{log['metadata']['baseline_version']}/Tuesday/0800.json.gz")
        snap = archive.read_json(self.archive, key)
        self.assertEqual((snap["weekday"], snap["slot"]), ("Tuesday", "08:00"))
        site = snap["sites"]["4300"]
        self.assertEqual(set(site["q3a_cycle_length"]), {"usual", "p_low", "p_high", "n"})
        approach = site["approaches"]["SWANN4300Q9"]
        self.assertEqual(approach["q1_volume_30min"]["n"], 8)
        self.assertIn("q3c_green_share_pct", approach)
        self.assertNotIn("values", approach["q1_volume_30min"])            # no raw history in the snapshot

    def test_weekly_job_writes_the_snapshot(self):
        day = timewin.period_ending(END, self.settings.rules).day
        self.svc.refresh_baselines([day], slots=["07:30", "08:00"])
        keys = self.archive.keys("baselines/")
        self.assertEqual([k.rsplit("/", 1)[1] for k in keys], ["0730.json.gz", "0800.json.gz"])

    def test_archive_failure_does_not_lose_the_run(self):
        svc = DiagnosticsService(self.source, self.settings, SQLiteStore(":memory:"), archive=BrokenArchive())
        with self.assertLogs("diagnostics.service", "WARNING"):
            view = svc.screen(END)
        self.assertEqual(svc.store.get_run(view["run_id"])["status"], "complete")
        self.assertTrue(svc.store.get_audits("archive_failed", view["run_id"]))
        svc.archive = self.archive                                       # retry once the archive is back
        self.assertTrue(svc.archive_run(view["run_id"]))
        self.assertEqual(len(self.logs()), 1)

    def test_contract_path_writes_the_log(self):
        period = timewin.period_ending(END, self.settings.rules)
        core.run_screening(S.ScreeningInput(run_id="scr_log", region="AU-VIC-Melbourne", period=adapter.period_model(period),
                                            baseline_version="2026-W44", sites=[]),
                           self.source, self.settings, SQLiteStore(":memory:"), archive=self.archive)
        log = archive.read_json(self.archive, self.logs()[0])
        self.assertEqual(log["metadata"]["run_id"], "scr_log")
        self.assertEqual(log["metadata"]["contract_baseline_version"], "2026-W44")
        self.assertTrue(self.archive.get(log["metadata"]["baseline_snapshot"]))

    def test_site_history_counts_only_screened_periods(self):
        schedule.backfill(self.svc, "2026-10-27T08:00", END)
        h = archive.site_history(self.archive, "AU-VIC-Melbourne", "4300", "2026-10-27", "2026-10-27")
        self.assertEqual(h["screened_periods"], 2)
        self.assertEqual(h["counts"].get("red"), sum(c == "red" for _, c in h["timeline"]))
        self.assertEqual([p for p, _ in h["timeline"]], ["2026-10-27T08:00", END])
        none = archive.site_history(self.archive, "AU-VIC-Melbourne", "4300", "2026-10-28", "2026-10-30")
        self.assertEqual((none["screened_periods"], none["red_share"]), (0, None))


class StorageTests(unittest.TestCase):
    def test_local_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            a = archive.LocalArchive(d)
            self.assertTrue(a.put_new("x/y.json", b"1"))
            self.assertFalse(a.put_new("x/y.json", b"2"))
            self.assertEqual(a.get("x/y.json"), b"1")

    def test_s3_conditional_write(self):
        s3 = FakeS3()
        a = archive.S3Archive("s3://bucket/diag", client=s3)
        self.assertTrue(a.put_new("baselines/x.json.gz", gzip.compress(b'{"a": 1}')))
        self.assertFalse(a.put_new("baselines/x.json.gz", b"other"))
        self.assertEqual(archive.read_json(a, "baselines/x.json.gz"), {"a": 1})
        self.assertEqual(a.keys("baselines/"), ["baselines/x.json.gz"])
        self.assertIsNone(a.get("missing"))
        self.assertEqual(list(s3.objects), ["diag/baselines/x.json.gz"])

    def test_open_archive(self):
        self.assertIsNone(archive.open_archive("off"))
        self.assertIsInstance(archive.open_archive("some/folder"), archive.LocalArchive)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.rules = Settings().rules
        self.tz = timewin.zone(self.rules)

    def test_next_run_is_the_next_period_end_plus_latency(self):
        at = lambda h, m: datetime(2026, 10, 30, h, m, tzinfo=self.tz)
        self.assertEqual(schedule.next_run_time(self.rules, at(16, 19)), at(16, 35))
        self.assertEqual(schedule.next_run_time(self.rules, at(16, 35)), at(17, 5))
        self.assertEqual(schedule.next_run_time(self.rules, at(16, 34)), at(16, 35))

    def test_run_scheduled_screens_each_new_period(self):
        settings = Settings()
        source = FakeSource(settings.rules, settings.schema, END + ":00+11:00", n_sites=8)
        svc = DiagnosticsService(source, settings, SQLiteStore(":memory:"))
        now = [datetime(2026, 10, 27, 8, 20, tzinfo=self.tz).astimezone(timezone.utc)]

        def clock():
            return now[0]

        seen = []

        def on_run(view):
            seen.append(view["period"]["end_local"])
            now[0] += timedelta(minutes=30)

        stop = threading.Event()
        stop.wait = lambda timeout: False                               # no real waiting in the test
        self.assertEqual(schedule.run_scheduled(svc, stop, max_runs=2, clock=clock, on_run=on_run), 2)
        self.assertEqual(seen, ["2026-10-27T08:30", "2026-10-27T09:00"])


if __name__ == "__main__":
    unittest.main()
