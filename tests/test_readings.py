"""Readings of a Red site from the quarter-hour detail (17 Nov 2026), on SCATS 3055 Bell Street / Elm Grove,
Tue 10 Nov 2026 08:00-08:30: the values of the Red report and the kpi-check of the same period."""
import json
import unittest
from pathlib import Path

from diagnostics import subsystems
from diagnostics.templates import d001, readings

KPI = json.loads((Path(__file__).parent / "data" / "kpi_check_3055.json").read_text(encoding="utf-8"))
E, W = "BELL59C659CF", "BELL5C83599F"


def row(link, label, cur, usual, lo, hi, status, d, n=6):
    return {"link": link, "label": label, "current": cur, "usual": usual, "p_low": lo, "p_high": hi, "status": status,
            "direction": d, "n_history": n, "pct_difference": (cur - usual) / usual * 100}


SITE = {"site": "3055", "name": "Bell Street / Elm Grove", "label": "Red", "q2": {"tolerated": [], "detectors": []},
        "q1": {"status": "ABNORMAL", "approaches": [row(E, "Bell Street [E]", 645.0, 571.0, 552.5, 607.0, "ABNORMAL", "HIGH"),
                                                    row(W, "Bell Street [W]", 633.0, 651.5, 610.5, 697.5, "NORMAL", None)]},
        "q3": {"status": "ABNORMAL", "abnormal_count": 2, "components": {
            "cycle_length": row(None, None, 121.6, 120.0, 120.0, 121.0, "NORMAL", None, 5),
            "cycle_stability": row(None, None, 87.6, 100.0, 91.8, 100.0, "ABNORMAL", "POORER", 5),
            "phase_service": {"status": "ABNORMAL", "approaches": [
                row(E, "Bell Street [E]", 61.3, 75.1, 67.8, 76.7, "ABNORMAL", "LOW", 5),
                row(W, "Bell Street [W]", 100.0, 92.5, 92.3, 100.0, "NORMAL", None, 5)]}}}}


def detail():
    """The kpi-check record as detail.quarter_detail returns it."""
    p = KPI["periods"][0]
    stamps = sorted(p["kpi"])
    approaches = {}
    for name, per in p["approaches"].items():
        approaches[name.split(" ")[0]] = [per[s] for s in sorted(per)]
    vol = {link: [v["08:15"], v["08:30"]] for link, v in KPI["link_volume_15min"].items()}
    return {"quarters": ["08:00-08:15", "08:15-08:30"], "kpi": [p["kpi"][s] for s in stamps],
            "approaches": approaches, "volume": vol}


class ReadingsTests(unittest.TestCase):
    def setUp(self):
        self.ev = d001.evidence(SITE, {"local": "Tue 10 Nov 2026 08:00-08:30"}, detail(), None,
                                subsystems.context("3055", lambda no: None))
        self.w = d001.written(self.ev)

    def test_quarter_view_and_phases(self):
        v = self.ev["quarter_view"]
        self.assertEqual(v["cycle_cv_pct"], [0.0, 5.0])
        self.assertEqual(v["volume"]["Bell Street [E]"], [355.0, 290.0])
        self.assertEqual(v["phases"], {"Bell Street [E]": "A,C", "Bell Street [W]": "A,B,C,D"})
        self.assertTrue(readings.served_in_every_phase(v, "Bell Street [W]"))
        self.assertEqual(readings.onset(v, self.ev), {"signal": 1, "volume": {"Bell Street [E]": 0}})

    def test_green_moved_to_the_other_phases(self):
        sh = self.ev["phase_shifts"][0]
        self.assertEqual((sh["phases"], sh["other_phases"], sh["other_current"], sh["other_usual"]),
                         ("A,C", "B,D", 38.7, 24.9))
        self.assertEqual(sh["other_approaches"], [])            # Bell Street [W] runs in every phase

    def test_readings_table(self):
        table = {r["key"]: r for r in self.ev["readings"]}
        self.assertEqual(self.ev["readings"][0]["key"], "other_phases")       # B,D gained, serving no assessed approach
        self.assertEqual(table["other_phases"]["strength"], "Moderate")     # 5-week history caps Strong
        self.assertNotIn("demand", table)                                   # only evidence against it
        self.assertEqual(table["plan"]["strength"], "Weak")                 # the first quarter ran the usual cycle

    def test_diagnosis_and_checks(self):
        d = self.w["diagnosis"]
        self.assertIn("The signal change starts in 08:15-08:30", d)
        self.assertIn("Phases A and C, serving Bell Street [E], lost 13.8 percentage points (08:00-08:15 65.1%, "
                      "08:15-08:30 57.5%); phases B and D gained 13.8.", d)
        self.assertIn("phases B and D gained 13.8 percentage points and serve none of the assessed approaches", d)
        self.assertIn("\nMost likely reading (evidence: Moderate): A local controller response (phase extensions, skips "
                      "or pedestrian calls): phases B and D gained 13.8 percentage points", d)
        self.assertIn("Share of the cycle by phase, current (usual): phases A and C 61.3% (75.1%), phases B and D "
                      "38.7% (24.9%).", d)
        self.assertIn("Control: the site is the only site of subsystem 21 of Region PRS", d)
        self.assertIn(readings.OPPOSITE, d)
        self.assertTrue(self.w["suggested_checks"][0].startswith("In SCATS History for 08:15-08:30, find why phases B "
                                                                 "and D ran longer or more often"))
        self.assertTrue(any("during 08:00-08:15" in c for c in self.w["suggested_checks"]))
        self.assertEqual(d001.kept_points(self.w, self.ev), [])
        self.assertEqual(d001.causal(self.w), [])

    def test_llm_must_keep_the_main_reading(self):
        name = readings.CATALOGUE["other_phases"]
        swapped = {**self.w, "diagnosis": self.w["diagnosis"].replace(name[0].upper() + name[1:],
                                                                      "A subsystem decision", 1)}
        self.assertIn(f'the most likely reading is not "{name}"', d001.kept_points(swapped, self.ev))
        self.assertEqual(d001.causal({"diagnosis": "The drop was caused by a pedestrian phase."}),
                         ['states a cause ("caused")'])

    def test_without_detail_the_report_is_still_written(self):
        ev = d001.evidence(SITE, {"local": "p"}, None)
        w = d001.written(ev)
        self.assertIsNone(ev["quarter_view"])
        self.assertIn("Most likely reading (evidence:", w["diagnosis"])

    def test_usual_100_percent_served_in_every_phase_is_not_a_mapping_check(self):
        site = json.loads(json.dumps(SITE))
        w_row = site["q3"]["components"]["phase_service"]["approaches"][1]
        w_row.update(current=80.0, usual=100.0, p_low=100.0, p_high=100.0, status="ABNORMAL", direction="LOW")
        self.assertEqual(d001.evidence(site, {"local": "p"}, detail())["mapping_checks"], [])
        self.assertEqual(len(d001.evidence(site, {"local": "p"}, None)["mapping_checks"]), 1)


class SubsystemTests(unittest.TestCase):
    """SCATS 4864: demand up on every approach, splits that differ across the reference weeks, a subsystem neighbour."""

    def setUp(self):
        from tests import site_4864 as s
        self.s = s
        self.ev = d001.evidence(s.SITE, {"local": "p"}, s.DETAIL, None, subsystems.context("4864", {"2318": s.MATE}.get))
        self.w = d001.written(self.ev)

    def test_membership(self):
        self.assertEqual(subsystems.membership("4864")["members"], ["2318", "4864"])
        self.assertTrue(subsystems.context("3055", lambda no: None)["single_site"])

    def test_phase_shares_now_but_no_usual_when_the_splits_differ(self):
        shares = {x["phases"]: x for x in self.ev["phase_shares"]}
        self.assertEqual({k: v["current"] for k, v in shares.items()}, {"A": 46.0, "B": 28.4, "C": 25.6})
        self.assertTrue(readings.mixed_splits(self.ev["phase_shares"]))
        self.assertIn("the reference weeks ran different splits", self.w["diagnosis"])

    def test_subsystem_decision_leads(self):
        self.assertEqual(self.ev["readings"][0]["key"], "plan")
        self.assertIn("it runs the same cycle as 2318 Bay Road / Jack Road in subsystem MEN-22", self.w["diagnosis"])
        self.assertIn("Control: subsystem 22 of Region MEN, shared with 2318", self.w["diagnosis"])
        self.assertTrue(self.w["suggested_checks"][0].startswith("Check subsystem MEN-22 for the period"))
        self.assertIn("(with 2318)", self.w["suggested_checks"][0])
        self.assertEqual(d001.kept_points(self.w, self.ev), [])

    def test_consistent_splits_give_the_phase_that_lost_green(self):
        site = json.loads(json.dumps(self.s.SITE))
        for a in site["q3"]["components"]["phase_service"]["approaches"]:     # usual shares of one split
            a["usual"] = {"Bay Road [E]": 83.0, "Bay Road [W]": 55.3, "Reserve Road [N]": 61.7}[a["label"]]
        ev = d001.evidence(site, {"local": "p"}, self.s.DETAIL, None, None)
        shares = {x["phases"]: x for x in ev["phase_shares"]}
        self.assertEqual((shares["C"]["usual"], shares["C"]["change"]), (44.7, -19.1))
        w = d001.written(ev)
        self.assertIn("Phase C, serving Bay Road [E] and Reserve Road [N], lost 19.1 percentage points", w["diagnosis"])
        self.assertIn("where volume is higher", " ".join(r for x in ev["readings"] for r in x["for"]))


if __name__ == "__main__":
    unittest.main()


class EvidencePositionTests(unittest.TestCase):
    def test_normal_value_outside_its_range_is_not_called_within(self):
        from diagnostics.contract.adapter import _position
        cycle = {"status": "NORMAL", "current": 121.6, "p_low": 120.0, "p_high": 121.0}   # SCATS 3055, 10 Nov 08:00
        self.assertEqual(_position(cycle), "outside its normal range but less than 10% from usual, so not flagged")
        self.assertEqual(_position({**cycle, "current": 120.5}), "within its normal range")
        stab = {"status": "NORMAL", "current": 95.5, "p_low": 62.5, "p_high": 80.3}
        self.assertIn("more stable than usual", _position(stab, poorer=True))
