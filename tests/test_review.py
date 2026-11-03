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
        self.assertIn("Possible explanations, not demonstrated by these data: the longer cycle with higher volume on "
                      "A St [N] may be SCATS lengthening the cycle as demand rose", a["diagnosis"])
        self.assertNotIn("%", a["diagnosis"])                          # the figures are in the supporting evidence
        self.assertTrue(a["suggested_checks"][0].startswith("Verify whether the longer cycle was SCATS's adaptive "
                                                            "response or a plan or coordination change"))
        self.assertIn("coordination (linking and offsets)", a["suggested_checks"][0])
        self.assertEqual(llm_problems(a), [])

    def test_cycle_change_without_matching_demand(self):
        ev = evidence(traffic=[("A St [N]", "LOW")], cycle=measure(ABNORMAL, "HIGH", 130.0), traffic_only=["A St [N]"])
        self.assertIn("the longer cycle is not matched by higher volume on the screened approaches, so a plan or "
                      "coordination change is a possible explanation", d001.written(ev)["diagnosis"])

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
        self.assertEqual(cov["statement"], "Coverage of the SCATS-identified approaches: A St [N]: delay in 2 of 2 "
                         "15-minute periods, queue in 30 of 30 minutes; B Rd [E]: delay in 1 of 2 15-minute periods, "
                         "queue in 12 of 30 minutes.")
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
