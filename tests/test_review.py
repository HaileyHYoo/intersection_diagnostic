"""The methodology owner's review of run eebc0b2964f4 (3 Nov 2026): Q4 wording, Q5 verdicts, names, summary."""
import unittest

from diagnostics import screening
from diagnostics.local import summary
from diagnostics.stats import ABNORMAL, INSUFFICIENT, NORMAL
from diagnostics.templates import d001, d002


def measure(status=NORMAL, direction=None, current=100.0):
    return {"status": status, "direction": direction, "current": current, "usual": 100.0, "normal_range": [95.0, 105.0],
            "pct_difference": 0.0, "decimals": 1, "position": "within its normal range", "reason": None}


def evidence(traffic=(), cycle=None, stability=None, service=(), same=(), traffic_only=(), signal_only=()):
    row = lambda name, d: {"approach": name, "link": name, "direction": d, "current_volume": 150.0, "usual_volume": 100.0,
                           "normal_range": [90.0, 110.0], "pct_difference": 50.0 if d == "HIGH" else -50.0}
    green = lambda name, d: {"approach": name, "link": name, "direction": d, "current_green_share_pct": 20.0,
                             "usual_green_share_pct": 30.0, "normal_range": [28.0, 32.0]}
    return {"traffic": {"status": ABNORMAL, "abnormal_approaches": [row(n, d) for n, d in traffic]},
            "signal": {"cycle_length_s": cycle or measure(), "cycle_stability": stability or measure(),
                       "phase_service": {"status": ABNORMAL if service else NORMAL,
                                         "abnormal_approaches": [green(n, d) for n, d in service]}},
            "same_approach": list(same), "traffic_only_approaches": list(traffic_only),
            "signal_only_approaches": list(signal_only)}


class Q4WordingTests(unittest.TestCase):
    def test_longer_cycle_with_higher_volume_may_be_adaptive(self):
        ev = evidence(traffic=[("A St [N]", "HIGH")], cycle=measure(ABNORMAL, "HIGH", 130.0),
                      stability=measure(ABNORMAL, "POORER", 50.0), traffic_only=["A St [N]"])
        a = d001.written(ev)
        self.assertIn("Traffic differs from history on A St [N] (higher volume than usual).", a["diagnosis"])
        self.assertIn("cycle length (longer than usual)", a["diagnosis"])
        self.assertIn(d001.ADAPTIVE, a["diagnosis"])
        self.assertIn("\nPossible explanations (not demonstrated by these data): " + d001.ADAPTIVE + " The longer cycle "
                      "with higher volume on A St [N] may be SCATS lengthening the cycle as demand rose", a["diagnosis"])
        self.assertTrue(a["diagnosis"].startswith("What the data show: Traffic differs"))
        self.assertNotIn("%", a["diagnosis"])                          # the figures are in the supporting evidence
        self.assertTrue(a["suggested_checks"][0].startswith("Verify whether the longer cycle was SCATS's adaptive "
                                                            "response or a plan or coordination change"))
        self.assertIn("coordination (linking and offsets)", a["suggested_checks"][0])
        self.assertEqual(llm_problems(a), [])

    def test_cycle_change_without_matching_demand(self):
        ev = evidence(traffic=[("A St [N]", "LOW")], cycle=measure(ABNORMAL, "HIGH", 130.0), traffic_only=["A St [N]"])
        self.assertIn("The longer cycle is not matched by higher volume on the screened approaches, so a plan or "
                      "coordination change is a possible explanation", d001.written(ev)["diagnosis"])

    def test_cycle_change_with_volume_moving_both_ways(self):
        """SCATS 1037, 10 Nov 2026: shorter cycle, volume lower on [W] but higher on [E]."""
        ev = evidence(traffic=[("Q St [W]", "LOW"), ("Q St [E]", "HIGH")], cycle=measure(ABNORMAL, "LOW", 70.0),
                      traffic_only=["Q St [W]", "Q St [E]"])
        a = d001.written(ev)
        self.assertIn("Volume is lower on Q St [W] but higher on Q St [E], so the shorter cycle is not clearly a "
                      "response to demand; a plan or coordination change is also possible", a["diagnosis"])
        self.assertNotIn("shortening the cycle", a["diagnosis"])
        self.assertEqual(llm_problems(a), [])

    def test_less_green_to_busier_approach_is_checked_first(self):
        ev = evidence(traffic=[("A St [N]", "HIGH"), ("B Rd [E]", "HIGH")], cycle=measure(ABNORMAL, "HIGH", 130.0),
                      service=[("A St [N]", "LOW"), ("B Rd [E]", "HIGH")], same=["A St [N]", "B Rd [E]"])
        a = d001.written(ev)
        self.assertIn("less green to A St [N] while its volume is higher is the opposite of a demand response",
                      a["diagnosis"])
        self.assertIn("more green to B Rd [E] with higher volume may be SCATS following its demand", a["diagnosis"])
        self.assertTrue(a["suggested_checks"][0].startswith("Verify phase service on A St [N] against its demand"))
        self.assertTrue(a["suggested_checks"][1].startswith("Verify phase service on B Rd [E]"))
        self.assertTrue(a["suggested_checks"][2].startswith("Verify whether the longer cycle"))

    def test_plain_normal_measures_stay_in_the_table(self):
        ev = evidence(traffic=[("A St [N]", "HIGH")], service=[("A St [N]", "LOW")], same=["A St [N]"])
        support = d001.written(ev)["supporting_evidence"]
        self.assertFalse(any(s.startswith(("Cycle length", "Cycle Stability")) for s in support))
        self.assertIn("Phase service A St [N]: green share 20.0% against a usual 30.0% (normal range 28.0-32.0%) - "
                      "below its normal range.", support)


def llm_problems(answer):
    from diagnostics import llm
    return [p for p in llm.check(answer, ["diagnosis", "supporting_evidence", "suggested_checks"], {}, None)
            if p.startswith("forbidden")]


class Q5VerdictTests(unittest.TestCase):
    def test_site_verdict(self):
        A, D, N = d002.AGREE, d002.DISAGREE, d002.NO_COVERAGE
        self.assertEqual(d002.site_verdict([A, A]), A)
        self.assertEqual(d002.site_verdict([A, D]), d002.PARTIAL)
        self.assertEqual(d002.site_verdict([A, N]), d002.PARTIAL)
        self.assertEqual(d002.site_verdict([D, N]), D)
        self.assertEqual(d002.site_verdict([N]), N)
        self.assertEqual(d002.site_verdict([]), N)

    def test_partial_agreement_names_both_sides_and_coverage(self):
        flagged = {"LA": {"approach": "A St [N]", "findings": ["Q1 high"]},
                   "LB": {"approach": "B Rd [E]", "findings": ["Q1 low"]}}
        rows = [{"link": "LA", "quarters_observed": 2, "queue_minutes": 30},
                {"link": "LB", "quarters_observed": 1, "queue_minutes": 12}]
        cov = d002.coverage(rows, flagged, "available")
        self.assertFalse(cov["full_period"])
        self.assertEqual(cov["statement"], "SCATS-identified approaches: A St [N]: delay in 30 of 30 minutes, "
                         "queue in 30 of 30 minutes; B Rd [E]: delay in 15 of 30 minutes, queue in 12 of 30 minutes.")
        full = d002.coverage(rows[:1], {"LA": flagged["LA"]}, "available")
        self.assertEqual(full["statement"], "Delay and queue are available for the full 30 minutes on every "
                                            "SCATS-identified approach.")
        per = [{"approach": "A St [N]", "agreement": d002.AGREE, "scats_findings": ["Q1 high"], "has_largest_queue": True,
                "largest_by_delay": {"control_delay": True}, "has_largest_delay": True},
               {"approach": "B Rd [E]", "agreement": d002.DISAGREE, "scats_findings": ["Q1 low"],
                "has_largest_queue": False, "largest_by_delay": {"control_delay": False}, "has_largest_delay": False}]
        comp = {"agreement": d002.PARTIAL, "per_approach": per, "greatest_delays": {}, "greatest_delay": None,
                "longest_queue": None}
        text = d002.written({"available": True, "comparison": comp, "coverage": cov, "queue": "available",
                             "coverage_note": ""})["road_user_impact"]
        self.assertIn("Overall: partial agreement - TomTom matches the SCATS findings on A St [N] but differs on "
                      "B Rd [E]. This supports a road-user impact on A St [N] only, without establishing its cause.", text)
        self.assertIn("queue in 12 of 30 minutes", text)

    def test_contract_keeps_the_three_per_approach_values(self):
        from diagnostics.contract import adapter
        self.assertEqual(set(adapter.AGREEMENT), {d002.AGREE, d002.DISAGREE, d002.NO_COVERAGE})


class NameTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(d001.approach_label({"link": "L1", "street": "Main Rd", "bound": "N"}), "Main Rd [N]")
        self.assertEqual(d001.approach_label({"link": "L1", "street": "Main Rd"}), "Main Rd (link L1)")
        self.assertEqual(d001.approach_label({"link": "STNA8GJG8GMW", "bound": "E"}),
                         "Link STNA8GJG8GMW [E] (no street name)")

    def test_names_filled_from_the_lookup(self):
        class Source:
            def link_names(self, links):
                self.asked = links
                return {"L2": "Second St", "Q9": "Ninth Ave"}
        src = Source()
        links = {"1": [{"site": "1", "link": "L1", "street": "First St"}, {"site": "1", "link": "L2", "street": None}]}
        names = screening.street_names(src, links, {"1": {"L1": {}, "Q9": {}}}, {"green": {"1": {"Q9": {}}}})
        self.assertEqual(src.asked, ["L2", "Q9"])
        self.assertEqual(links["1"][1]["street"], "Second St")
        self.assertEqual(names["Q9"], "Ninth Ave")
        self.assertEqual(screening.street_names(object(), links, {}, {}), {})      # a source without names


class SummaryReviewTests(unittest.TestCase):
    def grey_site(self, recorded):
        comp = lambda status: {"status": status, "current": 100.0, "usual": 100.0, "p_low": 95.0, "p_high": 105.0}
        rows = [{"link": "A", "status": NORMAL, "current": 30.0, "usual": 30.0, "p_low": 28.0, "p_high": 32.0,
                 "no_green": False},
                {"link": "B", "status": INSUFFICIENT, "current": None, "usual": 20.0, "p_low": 18.0, "p_high": 22.0,
                 "no_green": True, "reason": "HasGreen = 0 in the period", "recorded_green_share": recorded}]
        return {"site": "9", "category": "grey", "q2": {"status": "PASS", "detectors": []},
                "q1": {"status": ABNORMAL, "approaches": []},
                "q3": {"status": NORMAL, "components": {
                    "cycle_length": comp(ABNORMAL), "cycle_stability": comp(NORMAL),
                    "phase_service": {"status": INSUFFICIENT, "approaches": rows, "grey_site": True, "without_green": ["B"]}}}}

    def test_no_green_alternatives(self):
        cf = summary.counterfactual(self.grey_site(0.0))
        self.assertEqual(cf["a_no_green_not_assessable"], "amber_traffic")   # Q3C not assessable: Q3 NORMAL (1 of 2)
        self.assertEqual(cf["b_recorded_no_green_as_zero"], "red")           # 0% below 18%: Q3C + Q3A abnormal
        review = summary.review([self.grey_site(0.0)])["grey"]
        self.assertEqual(review["grey_only_because_of_no_green"], 1)
        self.assertEqual(review["of_which_q3a_and_q3b_both_assessable"], 1)
        self.assertEqual(review["no_green_approaches"], {"HasGreen = 0 recorded in both quarter-hours": 1})


if __name__ == "__main__":
    unittest.main()


class LiveFindingTests(unittest.TestCase):
    """Seen in run 651303f563f6 (Fri 30 Oct 2026 15:00)."""

    def test_two_links_with_the_same_name_get_their_ids(self):
        from diagnostics.names import approach_label, label_site
        q1 = [{"link": "W1", "street": "William Street", "bound": "N"}, {"link": "W2", "street": "William Street", "bound": "N"},
              {"link": "F1", "street": "Flinders Street", "bound": "W"}]
        q3c = [{"link": "W1", "street": "William Street", "bound": "N"}]
        label_site(q1, [], q3c)
        self.assertEqual([approach_label(r) for r in q1], ["William Street [N] (link W1)", "William Street [N] (link W2)",
                                                           "Flinders Street [W]"])
        self.assertEqual(approach_label(q3c[0]), "William Street [N] (link W1)")

    def test_within_is_read_against_the_measure_it_follows(self):
        ev = {"signal": {"cycle_length_s": {"position": "within its normal range"},
                         "cycle_stability": {"position": "below its normal range"}}}
        say = lambda t: d001.contradictions({"diagnosis": t, "supporting_evidence": []}, ev)
        self.assertEqual(say("Cycle stability is below its normal range; cycle length is within its normal range."), [])
        self.assertEqual(say("Cycle stability is below its normal range, while cycle length is within it."), [])
        self.assertTrue(say("Cycle stability is within its normal range."))


class SharedLinkTests(unittest.TestCase):
    def test_two_tomtom_approaches_on_one_link_are_told_apart(self):
        import copy
        from diagnostics import timewin
        from diagnostics.settings import Settings
        from tests.test_q5_delay import END, StubTomTom, site
        rules = copy.deepcopy(Settings().rules)
        period = timewin.period_ending(END, rules)

        class Source(StubTomTom):
            def tomtom_mapping(self, s):
                m = super().tomtom_mapping(s)
                m["approaches"]["B2"] = {"link": "LB", "street": "B Street", "direction": "WEST"}
                return m

            def tomtom_turn_kpi(self, s, start, end):
                return super().tomtom_turn_kpi(s, start, end) + [
                    {"approach": "B2", "exit": "X1", "field": f, "time": t, "value": v}
                    for t in self.ends for f, v in (("approach_delay", 5), ("control_delay", 5), ("sample_count", 2))]

        result = d002.run(Source(period), site(), period, rules)
        names = sorted(a["approach"] for a in result["evidence"]["approaches"] if a["link"] == "LB")
        self.assertEqual(names, ["B Street [E] (TomTom approach B)", "B Street [E] (TomTom approach B2)"])
        self.assertIn("several TomTom approaches are mapped to one link in the mapping file (for review): "
                      "LB: TomTom approaches B, B2", result["evidence"]["coverage_note"])
        self.assertEqual(result["evidence"]["comparison"]["per_approach"][0]["agreement"], d002.AGREE)


class LLMGuardReviewTests(unittest.TestCase):
    def test_made_up_link_id_is_rejected(self):
        from diagnostics import llm
        ev = {"approach": "William Street [N] (link WILLH6X4J54X)", "other": "WILLH6X4J642"}
        ok = {"road_user_impact": "William Street [N] (link WILLH6X4J54X) and link WILLH6X4J642."}
        bad = {"road_user_impact": "William Street [N] (link WILLH6X4J54XJ642) is missing."}
        ref = __import__("json").dumps(ev)
        allowed = llm.allowed_numbers(ev, {})
        self.assertEqual(llm.check(ok, ["road_user_impact"], allowed, None, ref), [])
        self.assertIn("link IDs not in the evidence: WILLH6X4J54XJ642",
                      llm.check(bad, ["road_user_impact"], allowed, None, ref))


class CodeLinesTests(unittest.TestCase):
    def test_verdict_and_coverage_lines_are_the_codes(self):
        from diagnostics import layout
        llm_text = ("Largest values: X. By approach: Y. Overall: partial agreement - reworded. "
                    "Coverage: link WRONG is missing.")
        code = "Largest values: x\nBy approach: y\nOverall: partial agreement - code\nCoverage: full 30 minutes."
        out = layout.keep_code_lines(llm_text, code, layout.D002_LABELS, ["Overall:", "Coverage:"])
        self.assertEqual(out.split("\n"), ["Largest values: X.", "By approach: Y.",
                                           "Overall: partial agreement - code", "Coverage: full 30 minutes."])


class IndependentStatsTests(unittest.TestCase):
    def test_every_check_is_counted_without_gates(self):
        from diagnostics.local import independent
        from diagnostics.local.fake import FakeSource
        from diagnostics.service import DiagnosticsService
        from diagnostics.settings import Settings
        from diagnostics.store import SQLiteStore
        s = Settings()
        svc = DiagnosticsService(FakeSource(s.rules, s.schema, "2026-10-27T08:30:00+11:00", n_sites=20), s,
                                 SQLiteStore(":memory:"))
        summary, rows = independent.run(svc, "2026-10-27T08:30")
        by = {r["site"]: r for r in rows}
        self.assertEqual(summary["sites"], 20)
        self.assertTrue(by["4318"]["detector_below_threshold"])              # Q2 FAIL ...
        self.assertIn(by["4318"]["q1"], ("NORMAL", "ABNORMAL"))              # ... and still assessed for Q1/Q3
        self.assertEqual(by["4318"]["category"], "detector_health")
        self.assertTrue(by["4327"]["approach_hasgreen_0"])
        self.assertTrue(by["4330"]["no_current_cycle_length"])
        self.assertEqual(summary["data_checks"]["detector_below_threshold"]["sites"],
                         sum(r["detector_below_threshold"] for r in rows))
        self.assertEqual(sum(summary["results_each_question_alone"]["category"].values()), 20)


class AuditTests(unittest.TestCase):
    def test_audit_classifies_and_gives_examples(self):
        from diagnostics.local import audit
        from diagnostics.local.fake import FakeSource
        from diagnostics.service import DiagnosticsService
        from diagnostics.settings import Settings
        from diagnostics.store import SQLiteStore
        s = Settings()
        svc = DiagnosticsService(FakeSource(s.rules, s.schema, "2026-10-27T08:30:00+11:00", n_sites=20), s,
                                 SQLiteStore(":memory:"))
        svc.screen("2026-10-27T08:30")
        a = audit.run(svc, "2026-10-27T08:30")
        self.assertIn("4333: DEAD4333XX, NEWL4333XX", a["q1"]["examples"]["egress_link_without_volume_history"])
        self.assertEqual(a["q2"]["low_count_detector_types"],
                         {"zero now, usually above the threshold: possible detector fault": 2})      # 4318 d3, d4
        self.assertIn("no phase information for the whole site now (empty records)", a["q3c"]["grey_no_green_approaches"])
        self.assertTrue(a["classification"]["examples"]["grey (reasons kept)"])
        self.assertIn("## 4. Q3C – phase service", audit.markdown(a))
        weeks = a["history_coverage"]["per_week"]
        self.assertEqual(len(weeks), 9)                                   # the analysis period and 8 reference weeks
        self.assertEqual(weeks[0]["kpi_sites_now"], weeks[0]["kpi_sites_before_fix"])   # on-grid fake stamps
        self.assertEqual(a["q2"]["by_group"]["Detector Health Issue (two or more)"]["sites"], 1)
        self.assertIn("share_abnormal_of_assessed_sites", a["q3c_sensitivity"])
        self.assertIn("| week | role |", audit.markdown(a))

    def test_q1_table_lists_approaches_not_assessed(self):
        from diagnostics.report import evidence_tables
        site = {"q1": {"approaches": [{"link": "A", "street": "A St", "bound": "N", "status": "INSUFFICIENT DATA",
                                       "current": None, "usual": 10.0, "p_low": 8.0, "p_high": 12.0,
                                       "pct_difference": None, "direction": None}],
                       "not_evaluated": [{"link": "B", "street": "B Rd", "reason": "no volume data in the reference weeks"}]},
                "q3": {"components": {"cycle_length": {"current": None, "status": "INSUFFICIENT DATA"},
                                      "cycle_stability": {"current": None, "status": "INSUFFICIENT DATA"},
                                      "phase_service": {"approaches": []}}}}
        rows = evidence_tables(site)[0]["rows"]
        self.assertEqual(rows[0][-1], "Not assessed: no current volume")
        self.assertEqual(rows[1], ["B Rd (link B)", "-", "-", "-", "0", "-", "Not assessed: no volume in any reference week"])


class Q5UnavailableReasonTests(unittest.TestCase):
    def test_mapped_site_without_delay_records_gives_a_reason(self):
        """Live (10 Nov 2026): a mapped site with no TomTom delay showed the fixed message without a reason."""
        from unittest import mock
        from diagnostics import timewin
        from diagnostics.settings import Settings
        rules = Settings().rules
        period = timewin.period_ending("2026-11-10T11:30", rules)
        site = {"site": "1", "q1": {"approaches": [], "not_evaluated": []},
                "q3": {"components": {"phase_service": {"approaches": []}}}}
        empty = {"approaches": [], "mapping_size": 4, "site_control_delay_s": None,
                 "queue_status": "unavailable - the site has no verified TomTom junction"}
        with mock.patch.object(d002, "measure", return_value=empty):
            r = d002.run(None, site, period, rules)
        self.assertFalse(r["evidence"]["available"])
        self.assertIn("no TomTom delay records (IntersectionTurnKpi)", r["evidence"]["coverage_note"])
        self.assertIn("Junction Analytics queue: unavailable - the site has no verified TomTom junction",
                      r["evidence"]["coverage_note"])


class Q5QueueObservedTests(unittest.TestCase):
    def test_queue_observed_without_longest_queue_disagrees(self):
        """Live, 10 Nov 2026: queue 30 of 30 minutes but delay 15 of 30 read as "no adequate TomTom coverage"."""
        row = lambda link, q: {"link": link, "approach": link, "quarters_observed": 1, "quarters_by": {},
                               "control_delay_s": 5.0, "approach_delay_s": 5.0, "delay_s": 5.0, "adequate": False,
                               "queue_adequate": True, "queue_mean_m": q}
        measured = {"approaches": [row("HAWKE", 41.1), row("ERROL", 9.0)], "queue_status": "available",
                    "delay_metric": "control_delay", "ranked_delays": ["control_delay", "approach_delay"]}
        flagged = {"HAWKE": {"approach": "Hawke St [NE]", "findings": ["Q3C abnormal_low"]},
                   "ERROL": {"approach": "Errol St [S]", "findings": ["Q1 high"]}}
        comp = d002.compare(measured, flagged)
        verdicts = {p["link"]: p["agreement"] for p in comp["per_approach"]}
        self.assertEqual(verdicts, {"HAWKE": d002.AGREE, "ERROL": d002.DISAGREE})
        self.assertEqual(comp["agreement"], d002.PARTIAL)
        errol = next(p for p in comp["per_approach"] if p["link"] == "ERROL")
        self.assertIn("does not have the longest queue", d002._per_approach_sentence(errol))


class ReportAuditTests(unittest.TestCase):
    def test_batch_writes_index_summary_and_reports(self):
        import csv
        import tempfile
        from pathlib import Path
        from diagnostics.local import report_audit
        from diagnostics.local.fake import FakeSource
        from diagnostics.service import DiagnosticsService
        from diagnostics.settings import Settings
        from diagnostics.store import SQLiteStore
        st = Settings()
        svc = DiagnosticsService(FakeSource(st.rules, st.schema, "2026-10-27T08:30:00+11:00", n_sites=20), st,
                                 SQLiteStore(":memory:"))
        periods = report_audit.parse_periods(["AM peak=2026-10-27T08:30"])
        self.assertEqual(periods, [("AM peak", "2026-10-27T08:30")])
        with tempfile.TemporaryDirectory() as out:
            batch = report_audit.run(svc, periods, out, progress=lambda *_: None)
            rows = list(csv.DictReader((batch / "index.csv").open(encoding="utf-8-sig")))
            self.assertTrue(rows and {r["category"] for r in rows} <= {"Red - Needs Attention",
                            "Amber - Traffic Abnormality", "Amber - Signal-Operation Abnormality"})
            self.assertTrue((batch / "am_peak" / "red.md").read_text(encoding="utf-8").count("## ") > 0)
            self.assertIn("Q5 (Red) verdicts", (batch / "summary.md").read_text(encoding="utf-8"))
            self.assertNotIn("83.3125", (batch / "index.csv").read_text(encoding="utf-8-sig"))
            import json
            details = [json.loads(x) for x in (batch / "details.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(details), 20)                                     # every site of the period
            red = [d for d in details if d["category"] == "red"]
            self.assertTrue(red and "code_checks" in red[0]["d001"] and "approaches" in red[0]["d002"])
            self.assertNotIn("approach", red[0]["q3"]["cycle_length"])


class FuturePeriodTests(unittest.TestCase):
    def test_a_period_whose_data_are_not_complete_is_refused(self):
        """10 Nov 2026: PM peak requested before 17:40 screened 2,501 sites Grey and was stored."""
        from datetime import datetime, timezone
        from diagnostics.service import DiagnosticsService
        from diagnostics.settings import Settings
        from diagnostics.store import SQLiteStore

        class Live:                                   # a source without the synthetic flag
            pass
        svc = DiagnosticsService(Live(), Settings(), SQLiteStore(":memory:"))
        now = datetime(2026, 11, 10, 6, 35, tzinfo=timezone.utc)            # 17:35 Melbourne
        with self.assertRaises(ValueError) as ctx:
            svc.screen("2026-11-10T17:30", now=now)
        self.assertIn("cannot be screened yet", str(ctx.exception))

