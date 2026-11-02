import copy
import tempfile
import unittest

from diagnostics import archive, link_speed, timewin
from diagnostics.contract import adapter, core
from diagnostics.contract import intersections_diagnostics_schemas as S
from diagnostics.local.fake import FakeSource
from diagnostics.service import DiagnosticsService
from diagnostics.settings import Settings
from diagnostics.sources.base import DataUnavailable
from diagnostics.store import SQLiteStore

END = "2026-10-27T08:30"


class NoSpeed(FakeSource):
    def link_speeds(self, links, start, end, key="link_speed"):
        raise DataUnavailable("aimes/speed timed out")


def service(source_cls=FakeSource, settings=None):
    s = settings or Settings()
    return DiagnosticsService(source_cls(s.rules, s.schema, END + ":00+11:00", n_sites=20), s, SQLiteStore(":memory:"))


class LinkSpeedTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.run_id = self.svc.screen(END)["run_id"]

    def test_red_report_has_the_speed_beside_delay_and_queue(self):
        r = self.svc.diagnose(self.run_id, "4300")
        section = r["report"]["sections"][2]
        speed = section["tables"][-1]
        self.assertTrue(speed["title"].startswith("Supplementary: TomTom incoming-link speed"))
        self.assertEqual(speed["rows"][0][:2], ["Swanston Street [N]", "18.1"])
        self.assertIn("Supplementary: TomTom incoming-link speed", r["report"]["markdown"])
        self.assertEqual(r["link_speed"]["approaches"][0]["link"], "SWANN4300Q9")   # kept in the diagnosis record
        self.assertEqual(self.svc.store.latest_diagnosis(self.run_id, "4300")["link_speed"]["unit"], "km/h")

    def test_amber_click_shows_speed_without_q4_q5(self):
        for site in ("4309", "4312"):                                  # amber traffic, amber signal
            e = self.svc.diagnose(self.run_id, site)
            self.assertEqual(e["mode"], "evidence")
            self.assertTrue(e["link_speed"]["available"])
            self.assertNotIn("report", e)
        self.assertNotIn("link_speed", self.svc.diagnose(self.run_id, "4315"))   # normal: not read

    def test_missing_speed_is_unavailable(self):
        r = self.svc.diagnose(self.run_id, "4303")                     # red_disagree: west approach has no speed
        west = next(a for a in r["link_speed"]["approaches"] if a["link"].endswith("W4303Q9"))
        self.assertEqual((west["speed_kmh"], west["status"]), (None, "unavailable"))
        self.assertIn("no TomTom speed for", r["link_speed"]["notes"][0])
        self.assertEqual(r["link_speed"]["reference"], "unavailable - no existing historical reference speed is configured")

    def test_harmonic_mean_ignores_zero_samples(self):
        self.assertAlmostEqual(link_speed.harmonic([30.0, 60.0, 0.0]), 40.0)
        self.assertIsNone(link_speed.harmonic([0.0]))
        r = self.svc.diagnose(self.run_id, "4300")
        east = next(a for a in r["link_speed"]["approaches"] if a["link"] == "FLINE4300Q9")
        self.assertEqual(east["samples"], 6)                           # the 0 km/h sample is not counted

    def test_a_speed_failure_changes_nothing_else(self):
        broken = service(NoSpeed)
        view = broken.screen(END)
        self.assertEqual(view["counts"], self.svc.screen(END)["counts"])           # classification untouched
        r = broken.diagnose(view["run_id"], "4300")
        self.assertEqual(r["report"]["sections"][2]["bullets"][0], "Agreement with SCATS findings: agreement")
        self.assertIn("could not be read", r["link_speed"]["notes"][0])
        self.assertFalse(r["link_speed"]["available"])

    def test_reference_speed_is_read_only_when_configured(self):
        settings = Settings()
        settings.schema = copy.deepcopy(settings.schema)
        settings.schema["influx"]["sources"]["link_speed_reference"]["enabled"] = True
        svc = service(settings=settings)
        e = svc.diagnose(svc.screen(END)["run_id"], "4309")
        self.assertTrue(e["link_speed"]["reference"].startswith("unavailable - DataUnavailable"))

    def test_switch_and_categories(self):
        settings = Settings()
        settings.rules = copy.deepcopy(settings.rules)
        settings.rules["link_speed"]["enabled"] = False
        svc = service(settings=settings)
        run_id = svc.screen(END)["run_id"]
        self.assertNotIn("link_speed", svc.diagnose(run_id, "4309"))
        self.assertIsNone(svc.diagnose(run_id, "4300")["link_speed"])

    def test_contract_site_report(self):
        s = Settings()
        source = FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=20)
        period = timewin.period_ending(END, s.rules)
        result = core.run_screening(S.ScreeningInput(run_id="scr", region="AU-VIC-Melbourne", period=adapter.period_model(period),
                                                     baseline_version="2026-W44", sites=[]), source, s, SQLiteStore(":memory:"))
        run = S.ScreeningRun(run_id="scr", status=S.RunStatus.COMPLETED, started_at=result.completed_at,
                             key=S.ScreeningCacheKey(region="AU-VIC-Melbourne", period_end=result.period.end,
                                                     baseline_version="2026-W44"), result=result)
        request = lambda site: S.SiteReportRequest(region="AU-VIC-Melbourne", screening_run_id="scr", site_no=site)
        amber = core.run_site_report(request("4309"), run, source, s)
        self.assertIsNone(amber.diagnosis)
        self.assertTrue(amber.link_speed.available)
        self.assertEqual(amber.link_speed.period, result.period)
        self.assertEqual(amber.link_speed.links[0].street_name, "William Street")
        self.assertIn("Reference speed: unavailable", amber.link_speed.notes[-1])
        with tempfile.TemporaryDirectory() as d:
            arch = archive.LocalArchive(d)
            red = core.run_site_report(request("4300"), run, source, s, archive=arch)
            self.assertEqual(red.diagnosis.q5.scats_comparison[0].agreement, S.ScatsAgreement.AGREE)
            self.assertEqual(arch.keys("site-reports/"), ["site-reports/AU-VIC-Melbourne/2026/10/27/0800_scr_4300.json"])
            amber_again = core.run_site_report(request("4309"), run, source, s, archive=arch)
            self.assertIsNone(amber_again.diagnosis)
            self.assertEqual(len(arch.keys("site-reports/")), 1)          # only Red reports are 18.2 records
        with self.assertRaises(ValueError):
            core.run_site_report(request("4315"), run, source, s)         # Normal: no report
        broken = NoSpeed(s.rules, s.schema, END + ":00+11:00", n_sites=20)
        report = core.run_site_report(request("4309"), run, broken, s)
        self.assertFalse(report.link_speed.available)
        self.assertEqual(report.link_speed.notes[0], S.LINK_SPEED_UNAVAILABLE_MESSAGE)


if __name__ == "__main__":
    unittest.main()


class ArmTests(unittest.TestCase):
    """The production operational-sheet modules, simulated, give LinkSpeed.arm; without them arm is None."""

    def setUp(self):
        import sys
        import types
        from diagnostics import arms
        calls = self.calls = []

        class Client:
            location = "s3://sheets"

            def __init__(self, region_tag):
                calls.append(("client", region_tag))

            def get_site(self, site):
                return ({"site": site}, "2026-10-01") if site != "4303" else None

        class SheetDB:
            def __init__(self, docs, origin=None):
                self.docs = docs

            def close(self):
                calls.append(("closed",))

        def build_sheet(db, site, link_rows=None, link_error=None):
            return {"links": [{"link_id": "SWANN4300Q9", "arm_no": 1}, {"link_id": "FLINE4300Q9", "arm_no": None},
                              {"link_id": "SWANS4300Q9", "arm_no": 3}]}

        base = "dash_backend.ai_brains.intersections"
        mods = {base + ".db.operational_sheet_client": types.SimpleNamespace(OperationalSheetClient=Client),
                base + ".operational_sheet": types.SimpleNamespace(build_sheet=build_sheet, LINK_CYPHER="MATCH ..."),
                base + ".operational_sheet_store": types.SimpleNamespace(OperationalSheetDB=SheetDB)}
        for name in ("dash_backend", "dash_backend.ai_brains", base, base + ".db"):
            mods.setdefault(name, types.ModuleType(name))
        self.saved = {k: sys.modules.get(k) for k in mods}
        sys.modules.update(mods)
        arms._client = None
        self.addCleanup(self.restore)

    def restore(self):
        import sys
        from diagnostics import arms
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        arms._client = None

    def source(self):
        s = Settings()
        src = FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=20)
        queries = self.queries = []

        class Graph:
            def rows(self, cypher, params):
                queries.append(params)
                return []

        src.graph = Graph()
        return s, src

    def test_arms_from_the_operational_sheet(self):
        s, src = self.source()
        svc = DiagnosticsService(src, s, SQLiteStore(":memory:"))
        r = svc.diagnose(svc.screen(END)["run_id"], "4300")
        by = {a["link"]: a["arm"] for a in r["link_speed"]["approaches"]}
        self.assertEqual((by["SWANN4300Q9"], by["FLINE4300Q9"], by["SWANS4300Q9"]), (1, None, 3))
        self.assertEqual(self.queries[0], {"ids": ["4300", "S4300"], "region": "AU-VIC-Melbourne"})
        table = r["report"]["sections"][2]["tables"][-1]
        self.assertEqual(table["columns"][:2], ["Approach", "Arm"])
        period = timewin.period_ending(END, s.rules)
        report = adapter.link_speed_report(r["link_speed"], "4300", adapter.period_model(period))
        self.assertEqual({l.link_id: l.arm for l in report.links}["SWANS4300Q9"], 3)

    def test_site_without_a_sheet(self):
        s, src = self.source()
        svc = DiagnosticsService(src, s, SQLiteStore(":memory:"))
        r = svc.diagnose(svc.screen(END)["run_id"], "4303")
        self.assertTrue(all(a["arm"] is None for a in r["link_speed"]["approaches"]))
        self.assertIn("arm numbers unavailable: the site has no operational sheet", r["link_speed"]["notes"])

    def test_local_runs_have_no_arm(self):
        self.restore()
        s = Settings()
        svc = DiagnosticsService(FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=20), s, SQLiteStore(":memory:"))
        r = svc.diagnose(svc.screen(END)["run_id"], "4300")
        self.assertTrue(all(a["arm"] is None for a in r["link_speed"]["approaches"]))
        self.assertNotIn("Arm", r["report"]["sections"][2]["tables"][-1]["columns"])
