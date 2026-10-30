import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from diagnostics.local import inspect_data
from diagnostics.local.fake import FakeSource
from diagnostics.local.viewer import export_html, make_handler
from diagnostics.service import DiagnosticsService
from diagnostics.settings import Settings
from diagnostics.store import SQLiteStore

END = "2026-10-27T08:30"


def service():
    s = Settings()
    return DiagnosticsService(FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=16), s, SQLiteStore(":memory:"))


class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = service()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.svc))
        cls.server.RequestHandlerClass.log_message = lambda *a: None
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read()

    def test_page_and_api(self):
        status, html = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"leaflet@1.9.4", html)
        _, body = self.get(f"/api/screen?end={END}")
        view = json.loads(body)
        self.assertEqual(view["period"]["end_local"], END)
        _, body = self.get(f"/api/diagnose?run={view['run_id']}&site=4300")
        self.assertEqual(json.loads(body)["mode"], "report")

    def test_bad_request(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/diagnose?run=nope&site=1")
        self.assertEqual(ctx.exception.code, 400)

    def test_static_export_embeds_evidence(self):
        run_id = self.svc.screen(END)["run_id"]
        with tempfile.TemporaryDirectory() as d:
            path = export_html(self.svc, run_id, Path(d) / "map.html")
            text = path.read_text(encoding="utf-8")
        self.assertIn("window.__STATIC__", text)
        self.assertIn('"4300"', text)


class SummaryTests(unittest.TestCase):
    def test_summary_explains_the_categories(self):
        from diagnostics.local import summary
        svc = service()
        run = svc.store.get_run(svc.screen(END)["run_id"])
        result = summary.summarise(run["payload"])
        self.assertEqual(result["detector_health"]["sites_where_every_failed_detector_counted_0"], 1)
        self.assertEqual(result["grey"]["sites"], 4)
        self.assertIn("Q3C: approach without green", result["grey"]["causes (a site can have several)"])
        self.assertEqual(result["traffic_abnormal"]["direction"], {"HIGH": 4, "LOW": 1})
        self.assertIn("categories", summary.text(result))


class InspectTests(unittest.TestCase):
    def test_inspection_checks(self):
        s = Settings()
        source = FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=16)
        report = inspect_data.inspect(source, s, "4336", END, 2)       # the "dirty" site
        self.assertEqual(report["errors"], {})
        self.assertEqual(report["checks"]["detectors"]["active_without_field"], [])
        self.assertTrue(report["checks"]["links"]["raw_ids_normalised"])
        self.assertEqual(report["feeds"]["site_kpi"]["value_types"], {"str": 18})
        self.assertEqual(report["feeds"]["site_kpi"]["on_grid"], 0)    # 20 s late on every stamp
        clean = inspect_data.inspect(source, s, "4339", END, 2)
        self.assertEqual(clean["checks"]["detectors"]["fields_present"], list(range(1, 10)))
        self.assertEqual(clean["checks"]["detectors"]["neo4j_inactive"], [9])
        red = inspect_data.inspect(source, s, "4300", END, 2)
        self.assertEqual(red["checks"]["tomtom"]["mapped_approaches"], 4)
        self.assertEqual(len(red["checks"]["tomtom"]["queue"]["approaches"]), 4)


if __name__ == "__main__":
    unittest.main()
