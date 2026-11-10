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
    """The contract with the optional audit fields proposed to the production team, to show the adapter fills them."""
    text = SCHEMA_FILE.read_text(encoding="utf-8")
    audit = "    generated_by: str | None = None\n    llm_rejected: str | None = None\n"
    text = text.replace("    limitations: list[str] = Field(default_factory=list)\n",
                        "    limitations: list[str] = Field(default_factory=list)\n" + audit, 1)
    narrative = '    narrative: str = Field(default="", description="Template answer explaining the calculated evidence")\n'
    text = text.replace(narrative, narrative + audit, 1)
    refs = "    config_version: str | None = None\n    audit_ref: str | None = None\n"
    text = text.replace("    completed_at: datetime\n", "    completed_at: datetime\n" + refs)
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

    def test_every_site_validates(self):
        got = {s.site_no: adapter.CATEGORY_BACK[s.category] for s in self.result.sites}
        self.assertEqual(got, self.source.expected())
        self.assertEqual(self.result.errors, {})

    def test_no_green_site_is_grey_with_the_flag(self):
        site = next(s for s in self.result.sites if s.site_no == "4327")
        self.assertEqual(site.category, S.SiteCategory.GREY)
        self.assertTrue(site.q3.phase_service.site_grey_no_green)
        self.assertIn("without green", site.insufficient_data_reason)
        self.assertTrue(adapter.accepts_none(S.ScatsComparison, "has_largest_queue"))

    def test_grey_sites_give_a_reason_and_missing_counts_are_none(self):
        grey = [s for s in self.result.sites if s.category == S.SiteCategory.GREY]
        self.assertTrue(grey and all(s.insufficient_data_reason for s in grey))
        self.assertTrue(all(s.insufficient_data_reason is None for s in self.result.sites if s not in grey))
        ours = {s["site"]: s for s in self.saved["payload"]["sites"]}
        gap = next(s for s in self.result.sites if s.site_no == "4321")              # detector_gap scenario
        for d in gap.q2.detectors:
            row = next(r for r in ours["4321"]["q2"]["detectors"] if str(r["detector"]) == d.detector_id)
            if row["status"] == "INSUFFICIENT DATA":
                self.assertEqual((d.count_60min, d.passed), (None, None))
        no_green = next(s for s in self.result.sites if s.site_no == "4327")
        back = adapter.site_from_model(no_green)
        self.assertEqual(back["reasons"][0], no_green.insufficient_data_reason)
        first = ours["4327"]["q1"]["approaches"][0]
        self.assertEqual((back["q1"]["approaches"][0]["street"], back["q1"]["approaches"][0]["bound"]),
                         (first["street"], first["bound"]))

    def test_a_link_without_street_name_keeps_its_label_through_the_contract(self):
        """Seen live (9 Nov 2026): "Link X [S] (no street name)" read back from the contract became
        "Link X [S] (no street name) (link X)" in every Red report text."""
        from diagnostics.names import approach_label
        site = next(s for s in self.result.sites if s.q1.approaches)
        model = site.model_copy(deep=True)
        a = model.q1.approaches[0]
        a.approach_name = f"Link {a.approach_id} [S] (no street name)"
        back = adapter.site_from_model(model)["q1"]["approaches"][0]
        self.assertEqual(approach_label(back), f"Link {a.approach_id} [S] (no street name)")
        named = adapter.site_from_model(site)["q1"]["approaches"][0]
        self.assertEqual(approach_label(named), site.q1.approaches[0].approach_name)

    def test_tomtom_unavailable_keeps_its_reason(self):
        """SCATS 1037, 10 Nov 2026: the production report showed only the fixed message."""
        from diagnostics.timewin import period_ending
        period = period_ending(END, self.settings.rules)
        d002 = {"evidence": {"available": False, "missing_approach_links": [], "coverage_note": "the site has no TomTom approach mapping"},
                "answer": {"road_user_impact": "TomTom confirmation unavailable for this intersection or analysis period."},
                "generated_by": "code", "rejected": None}
        q5 = adapter.q5_output(d002, period, self.settings.rules)
        self.assertEqual(q5.narrative, "TomTom confirmation unavailable for this intersection or analysis period. "
                                       "Reason: the site has no TomTom approach mapping.")

    def test_scats_approach_without_tomtom_row_is_named(self):
        """Seen live (9 Nov 2026): "PRINVH6GVH2H: Q3C abnormal_high" because Princess Street [S] had no TomTom row."""
        from diagnostics.timewin import period_ending
        row = {"link": "L1", "approach": "A St [N]", "tomtom_approach": "t1", "delay_s": 50.0, "control_delay_s": 40.0,
               "multi_stop_rate": 0.2, "queue_mean_m": 30.0, "queue_adequate": True, "adequate": True, "movements": []}
        comp = {"per_approach": [{"link": "L1", "approach": "A St [N]", "scats_findings": ["Q1 high"], "has_largest_delay": True,
                                  "has_largest_queue": True, "agreement": "agreement"},
                                 {"link": "L2", "approach": "B St [S]", "scats_findings": ["Q3C abnormal_high"],
                                  "has_largest_delay": False, "has_largest_queue": None, "agreement": "insufficient coverage"}],
                "greatest_delay": {"link": "L1"}, "longest_queue": {"link": "L1"}}
        d002 = {"evidence": {"available": True, "approaches": [row], "comparison": comp, "missing_approach_links": ["L2"]},
                "answer": {"road_user_impact": "x"}, "generated_by": "code", "rejected": None}
        q5 = adapter.q5_output(d002, period_ending(END, self.settings.rules), self.settings.rules)
        added = [a for a in q5.approaches if a.approach_id == "L2"]
        self.assertEqual([(a.approach_name, a.is_observed, a.delay_s) for a in added], [("B St [S]", False, None)])
        row["approach_delay_s"] = 55.0                        # both ranked delays reach the page (9-10 Nov 2026)
        q5 = adapter.q5_output(d002, period_ending(END, self.settings.rules), self.settings.rules)
        first = q5.approaches[0]
        self.assertEqual((first.delay_s, first.control_delay_s), (55.0, 40.0))

    def test_reference_dates_and_excluded_days(self):
        """Methodology owner, Nov 2026: the reference weeks as dates, with each excluded day and its reason."""
        from diagnostics.timewin import period_ending, reference_text
        text = reference_text(period_ending("2026-11-10T10:30", self.settings.rules), self.settings.rules)
        self.assertTrue(text.startswith("Reference: Tuesdays 10:00-10:30 in the 8 weeks 2026-09-15 to 2026-11-03 "
                                        "(7 used; excluded: 2026-11-03, public holiday: Melbourne Cup)."))

    def test_contract_report_view(self):
        from diagnostics.local import contract_view
        report = contract_view.site_report(self.svc, self.saved["run_id"], "4300")
        text = contract_view.page(report)
        self.assertIn("_diagnosis.q4.supporting_evidence[].statement_", text)
        self.assertIn("- Reference: Tuesdays 08:00-08:30 in the 8 weeks", text)
        self.assertIn("veh/30 min", text)

    def test_not_evaluated_approaches_survive_the_contract(self):
        """SCATS 1037, 10 Nov 2026: Leicester and Barry Street dropped out of the report built from the contract."""
        site = {"q1": {"not_evaluated": [{"link": "LEICV6W2W673", "street": "Leicester Street", "bound": "N",
                                          "label": "Leicester Street [N]", "reason": "no volume data in the reference weeks"}]}}
        note = adapter.not_evaluated_note(site["q1"]["not_evaluated"][0])
        self.assertEqual(note, "Approach Leicester Street [N] not assessed (Q1): no volume data in the reference weeks. "
                               "Link LEICV6W2W673.")
        back = adapter.not_evaluated_from_notes(["other note", note])
        self.assertEqual([(r["link"], r["street"], r["bound"]) for r in back], [("LEICV6W2W673", "Leicester Street", "N")])
        from diagnostics.names import approach_label
        self.assertEqual(approach_label(back[0]), "Leicester Street [N]")

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


class AuditTests(unittest.TestCase):
    """Methodology 18 on the contract path: an audit record now, contract fields once they exist."""

    def setUp(self):
        self.settings = Settings()
        self.source = FakeSource(self.settings.rules, self.settings.schema, END + ":00+11:00", n_sites=8)
        self.store = SQLiteStore(":memory:")
        self.period = timewin.period_ending(END, self.settings.rules)

    def screen(self):
        S = adapter.S                                                   # the contract in use (bundled or proposed)
        return core.run_screening(S.ScreeningInput(run_id="scr_audit", region="AU-VIC-Melbourne",
                                                   period=adapter.period_model(self.period), baseline_version="2026-W44",
                                                   sites=[]), self.source, self.settings, self.store, audit_store=self.store)

    def diagnose(self, result):
        S = adapter.S
        ev = next(s for s in result.sites if s.site_no == "4300")
        return core.run_diagnosis(S.DiagnosisInput(
            diagnosis_id="diag_4300", screening_run_id=result.run_id, region=result.region, period=result.period,
            site=S.ScreeningSite(site_no="4300"), evidence=ev,
            q4_template=S.TemplateRef(template_id="ID_Q4_SCATS_INTERPRETATION", version="1.0.0"),
            q5_template=S.TemplateRef(template_id="ID_Q5_TOMTOM_CONFIRMATION", version="1.0.0")),
            self.source, self.settings, audit_store=self.store)

    def test_audit_records_hold_what_the_contract_cannot(self):
        result = self.diagnose(self.screen())
        run = self.store.get_audits("screening", "scr_audit")[0]
        self.assertEqual(run["contract_baseline_version"], "2026-W44")
        self.assertTrue(run["provenance"])
        config = self.store.get_config(run["config_version"])
        self.assertEqual(config["rules"]["q2"]["min_vehicles"], 10)
        diag = self.store.get_audits("diagnosis", "diag_4300")[0]
        self.assertEqual(diag["templates"]["D001"]["registry"]["template_id"], "ID_Q4_SCATS_INTERPRETATION")
        self.assertEqual(diag["templates"]["D001"]["generated_by"], "code")
        self.assertFalse(hasattr(result.q4, "generated_by"))           # the current contract has no such field

    def test_future_contract_fields_are_filled(self):
        try:
            adapter.use_contract(proposed_contract())
            result = self.screen()
            self.assertTrue(result.config_version and result.audit_ref)
            diag = self.diagnose(result)
            self.assertEqual(diag.q4.generated_by, "code")
            self.assertIsNone(diag.q4.llm_rejected)
            self.assertTrue(diag.audit_ref)
        finally:
            adapter.use_contract(S)


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
        self.assertEqual(len(self.result.sites), 20)

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
        ev = d.q4.supporting_evidence                     # every approach and measure, out-of-range first, with values
        self.assertEqual([e.source for e in ev], ["Reference"] + ["Q1"] * 4 + ["Q3A", "Q3B"] + ["Q3C"] * 5)
        self.assertTrue(ev[0].statement.startswith("Reference: Tuesdays 08:00-08:30 in the 8 weeks 2026-09-01 to 2026-10-20 (8 used)"))
        self.assertTrue(ev[1].statement.endswith("outside its normal range."))
        self.assertIn("veh/30 min; usual", ev[1].statement)                       # units after every value
        self.assertIn("reference weeks)", ev[1].statement)
        self.assertTrue(ev[2].statement.endswith("within its normal range."))
        self.assertIn(" s; usual ", ev[5].statement)
        self.assertIn("from phase durations; not measured signal-group green time", ev[7].statement)
        self.assertTrue(ev[8].statement.endswith("outside its normal range.") and "%; usual" in ev[8].statement)
        self.assertTrue(d.q5.available)
        self.assertEqual(d.q5.largest_delay_approach_id, "SWANN4300Q9")
        self.assertEqual(d.q5.scats_comparison[0].agreement, S.ScatsAgreement.AGREE)
        self.assertEqual({m.movement for m in d.q5.movements}, {"left", "through", "right"})
        self.assertEqual(d.period, self.result.period)

    def test_tomtom_unavailable(self):
        d = self.diagnose("4306")
        self.assertFalse(d.q5.available)
        self.assertTrue(d.q5.narrative.startswith(S.TOMTOM_UNAVAILABLE_MESSAGE))     # the fixed message, then its reason
        self.assertIn("Reason: ", d.q5.narrative)

    def test_only_red_sites(self):
        with self.assertRaises(ValueError):
            self.diagnose("4309")


if __name__ == "__main__":
    unittest.main()
