import importlib.util
import unittest
from pathlib import Path

from diagnostics import timewin
from diagnostics.contract import adapter, core
from diagnostics.contract import intersections_diagnostics_schemas as S
from diagnostics.local.fake import FakeSource
from diagnostics.service import DiagnosticsService
from diagnostics.settings import Settings, load_rules
from diagnostics.store import SQLiteStore

END = "2026-10-27T08:30"
SCHEMA_FILE = Path(adapter.__file__).with_name("intersections_diagnostics_schemas.py")


def proposed_contract():
    """The contract with the two changes asked of the production team, to show the adapter picks them up."""
    text = SCHEMA_FILE.read_text(encoding="utf-8")
    text = text.replace('''    approaches: list[Q3CPhaseServiceApproach] = Field(default_factory=list)
''', '''    approaches: list[Q3CPhaseServiceApproach] = Field(default_factory=list)
    site_grey_no_green: bool = False
''', 1)
    text = text.replace('''    if AssessmentStatus.INSUFFICIENT_DATA in (q1.status, q3.status):''', '''    if q3.phase_service and q3.phase_service.site_grey_no_green:
        return SiteCategory.GREY
    if AssessmentStatus.INSUFFICIENT_DATA in (q1.status, q3.status):''', 1)
    text = text.replace("    has_largest_queue: bool\n", "    has_largest_queue: bool | None\n", 1)
    spec = importlib.util.spec_from_loader("proposed_contract", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(text, "proposed_contract", "exec"), module.__dict__)
    return module


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings()
        cls.source = FakeSource(cls.settings.rules, cls.settings.schema, END + ":00+11:00", n_sites=20)
        cls.svc = DiagnosticsService(cls.source, cls.settings, SQLiteStore(":memory:"))
        cls.saved = cls.svc.store.get_run(cls.svc.screen(END)["run_id"])
        cls.result = adapter.screening_result(cls.saved["payload"], cls.settings)

    def test_every_representable_site_validates(self):
        expected = {s: c for s, c in self.source.expected().items() if s != "4327"}
        got = {s.site_no: adapter.CATEGORY_BACK[s.category] for s in self.result.sites}
        self.assertEqual(got, expected)

    def test_no_green_site_is_reported_until_the_contract_has_the_flag(self):
        self.assertEqual(list(self.result.errors), ["4327"])
        self.assertIn("site_grey_no_green", self.result.errors["4327"])

    def test_proposed_flag_makes_the_no_green_site_grey(self):
        try:
            adapter.use_contract(proposed_contract())
            result = adapter.screening_result(self.saved["payload"], self.settings)
            self.assertEqual(result.errors, {})
            site = next(s for s in result.sites if s.site_no == "4327")
            self.assertEqual(site.category.value, "grey")
            self.assertTrue(site.q3.phase_service.site_grey_no_green)
            self.assertTrue(adapter.accepts_none(adapter.S.ScatsComparison, "has_largest_queue"))
        finally:
            adapter.use_contract(S)

    def test_store_round_trip_and_panel(self):
        run = S.ScreeningRun(run_id=self.result.run_id, status=S.RunStatus.COMPLETED, started_at=self.result.completed_at,
                             key=S.ScreeningCacheKey(region=self.result.region, period_end=self.result.period.end,
                                                     baseline_version=self.result.baseline_version), result=self.result)
        panel = S.ScreeningPanelData.from_run(S.ScreeningRun.from_store_record(run.to_store_record()), from_cache=True)
        self.assertEqual(panel.category_counts[S.SiteCategory.RED], 4)
        red = [m for m in panel.markers if m.category == S.SiteCategory.RED]
        self.assertIn("Swanston Street [N]", red[0].abnormal_approaches)
        self.assertEqual([d.site_no for d in panel.detector_health_issues], ["4318"])

    def test_period_and_config(self):
        p = self.result.period
        self.assertEqual((p.slot_index, p.weekday), (16, 1))
        self.assertEqual(p.end.isoformat(), "2026-10-27T08:30:00+11:00")
        self.assertEqual(p.detector_window_start.isoformat(), "2026-10-27T07:30:00+11:00")
        self.assertEqual((self.result.config.percentile_low, self.result.config.percentile_high), (10, 90))
        self.assertEqual(self.result.run_id.split("_")[2], "20261027T0830")

    def test_values_are_copied(self):
        site = next(s for s in self.result.sites if s.site_no == "4300")
        ours = next(s for s in self.saved["payload"]["sites"] if s["site"] == "4300")
        a = site.q1.approaches[0]
        self.assertEqual((a.approach_id, a.volume.current, a.volume.reference),
                         (ours["q1"]["approaches"][0]["link"], ours["q1"]["approaches"][0]["current"],
                          ours["q1"]["approaches"][0]["usual"]))
        self.assertEqual(site.coordinates, (ours["lon"], ours["lat"]))
        self.assertTrue(all(isinstance(d.count_60min, int) for d in site.q2.detectors))
        self.assertEqual(site.q3.cycle_stability.polarity, S.StabilityPolarity.LOWER_IS_POORER)
        self.assertGreater(site.total_volume_veh_h, 0)


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings()
        cls.source = FakeSource(cls.settings.rules, cls.settings.schema, END + ":00+11:00", n_sites=20)
        cls.period = timewin.period_ending(END, cls.settings.rules)
        cls.result = core.run_screening(S.ScreeningInput(run_id="scr_test", region="AU-VIC-Melbourne",
                                                         period=adapter.period_model(cls.period), baseline_version="2026-W44",
                                                         sites=[]), cls.source, cls.settings, SQLiteStore(":memory:"))

    def diagnose(self, site_no):
        ev = next(s for s in self.result.sites if s.site_no == site_no)
        return core.run_diagnosis(S.DiagnosisInput(
            diagnosis_id=f"diag_{site_no}", screening_run_id=self.result.run_id, region=self.result.region,
            period=self.result.period, site=S.ScreeningSite(site_no=site_no), evidence=ev,
            q4_template=S.TemplateRef(template_id="ID_Q4_SCATS_INTERPRETATION", version="1.0.0"),
            q5_template=S.TemplateRef(template_id="ID_Q5_TOMTOM_CONFIRMATION", version="1.0.0")), self.source, self.settings)

    def test_screening_keeps_the_hosts_ids(self):
        self.assertEqual((self.result.run_id, self.result.baseline_version), ("scr_test", "2026-W44"))
        self.assertEqual(len(self.result.sites), 19)

    def test_host_site_list_limits_the_run(self):
        sites = [S.ScreeningSite(site_no="4300", name="Test", coordinates=(144.96, -37.81),
                                 detector_ids=[str(n) for n in range(1, 9)],
                                 approaches=[S.ApproachRef(approach_id=link, approach_name="x")
                                             for link in ("SWANN4300Q9", "FLINE4300Q9", "SWANS4300Q9", "FLINW4300Q9")])]
        r = core.run_screening(S.ScreeningInput(run_id="one", region="AU-VIC-Melbourne", period=adapter.period_model(self.period),
                                                baseline_version="w", sites=sites), self.source, self.settings, SQLiteStore(":memory:"))
        self.assertEqual([(s.site_no, s.category.value) for s in r.sites], [("4300", "red")])

    def test_config_thresholds_override_rules(self):
        cfg = S.ScreeningConfig(detector_min_count_60min=100000)
        settings = core.settings_for(cfg)
        self.assertEqual(settings.rules["q2"]["min_vehicles"], 100000)
        self.assertEqual(settings.rules["q3c"], load_rules()["q3c"])

    def test_red_diagnosis(self):
        d = self.diagnose("4300")
        self.assertEqual(d.q4.template.template_id, "ID_Q4_SCATS_INTERPRETATION")
        self.assertEqual([e.source for e in d.q4.supporting_evidence], ["Q1", "Q3A", "Q3B", "Q3C"])
        self.assertTrue(d.q5.available)
        self.assertEqual(d.q5.largest_delay_approach_id, "SWANN4300Q9")
        self.assertEqual(d.q5.scats_comparison[0].agreement, S.ScatsAgreement.AGREE)
        self.assertEqual({m.movement for m in d.q5.movements}, {"left", "through", "right"})
        self.assertEqual(d.period, self.result.period)

    def test_tomtom_unavailable(self):
        d = self.diagnose("4306")
        self.assertFalse(d.q5.available)
        self.assertEqual(d.q5.narrative, S.TOMTOM_UNAVAILABLE_MESSAGE)

    def test_only_red_sites(self):
        with self.assertRaises(ValueError):
            self.diagnose("4309")


if __name__ == "__main__":
    unittest.main()
