"""Categories need 5 reference weeks; the Red report also uses measures with 2-4 weeks (methodology owner, 20 Nov 2026)."""
import unittest

from diagnostics import stats
from diagnostics.contract import adapter
from diagnostics.settings import load_rules
from diagnostics.templates import d001

RULES = load_rules()


class ReportReferenceTests(unittest.TestCase):
    def test_two_weeks_give_a_report_reference_but_no_assessment(self):
        env = {"n": 2, "usual": None, "p_low": None, "p_high": None, "values": [80.0, 90.0]}
        r = stats.range_only(77.8, env)
        self.assertEqual(r["status"], stats.INSUFFICIENT)                  # decides nothing
        self.assertIsNone(r["usual"])
        self.assertEqual((r["report_usual"], r["report_p_low"], r["report_p_high"]), (85.0, 81.0, 89.0))
        one = stats.range_only(77.8, {"n": 1, "usual": None, "values": [80.0]})
        self.assertNotIn("report_usual", one)                              # one week is not a reference

    def test_five_weeks_are_screened_as_before(self):
        env = stats.envelope([10, 11, 12, 13, 14], RULES)
        r = stats.two_sided(20, {**env, "values": [10, 11, 12, 13, 14]}, 10)
        self.assertEqual(r["status"], stats.ABNORMAL)
        self.assertNotIn("report_usual", r)

    def row(self):
        """SCATS 3182 Clyde Road [N] green share, 10 Nov 2026 08:00: 2 reference weeks (values here illustrative)."""
        return {"link": "CLYD6RRX7VF3", "street": "Clyde Road", "bound": "N", "status": stats.INSUFFICIENT,
                "current": 77.839, "usual": None, "p_low": None, "p_high": None, "n_history": 2, "direction": None,
                "pct_difference": None, "reason": "only 2 valid historical observations",
                "report_usual": 85.0, "report_p_low": 81.0, "report_p_high": 89.0}

    def test_contract_round_trip_keeps_it_apart(self):
        hc = adapter.comparison(self.row())
        self.assertEqual((hc.reference, hc.p10, hc.p90, hc.n_history_obs), (85.0, 81.0, 89.0, 2))

    def test_statement(self):
        site = {"q1": {"approaches": [], "not_evaluated": []},
                "q3": {"components": {
                    "cycle_length": {"status": stats.INSUFFICIENT, "current": None, "reason": "x", "n_history": 0},
                    "cycle_stability": {"status": stats.INSUFFICIENT, "current": None, "reason": "x", "n_history": 0},
                    "phase_service": {"approaches": [self.row()]}}}}
        text = [i.statement for i in adapter.evidence_items(site, None, RULES) if i.approach_id == "CLYD6RRX7VF3"][0]
        self.assertEqual(text, "Clyde Road [N] green share: 77.8%; usual 85.0% from only 2 reference weeks (range "
                               "81.0-89.0%); 7.2 percentage points lower; not assessed for the category (at least 5 "
                               "weeks are needed), shown for reference.")


if __name__ == "__main__":
    unittest.main()
