import copy
import unittest

from diagnostics import link_speed, timewin
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

    def test_contract_path(self):
        s = Settings()
        source = FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=20)
        period = timewin.period_ending(END, s.rules)
        result = core.run_screening(S.ScreeningInput(run_id="scr", region="AU-VIC-Melbourne", period=adapter.period_model(period),
                                                     baseline_version="2026-W44", sites=[]), source, s, SQLiteStore(":memory:"))
        amber = next(x for x in result.sites if x.site_no == "4309")
        speed = core.run_link_speed(amber, result.period, source, s)
        self.assertTrue(speed["available"])
        store = SQLiteStore(":memory:")
        red = next(x for x in result.sites if x.site_no == "4300")
        core.run_diagnosis(S.DiagnosisInput(
            diagnosis_id="d", screening_run_id="scr", region=result.region, period=result.period,
            site=S.ScreeningSite(site_no="4300"), evidence=red,
            q4_template=S.TemplateRef(template_id="ID_Q4_SCATS_INTERPRETATION", version="1.0.0"),
            q5_template=S.TemplateRef(template_id="ID_Q5_TOMTOM_CONFIRMATION", version="1.0.0")), source, s, audit_store=store)
        self.assertEqual(store.get_audits("diagnosis", "d")[0]["link_speed"]["unit"], "km/h")


if __name__ == "__main__":
    unittest.main()
