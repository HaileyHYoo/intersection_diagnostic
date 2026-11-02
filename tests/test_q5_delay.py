import copy
import unittest

from diagnostics import timewin
from diagnostics.settings import Settings
from diagnostics.sources.base import DataUnavailable
from diagnostics.templates import d002

END = "2026-10-27T08:30"


class StubTomTom:
    """Two approaches where approach delay and control delay rank them differently.

    A (link LA): approach delay 50 s, control delay 10 s and -5 s (negative = faster than free flow)
    B (link LB): approach delay 20 s, control delay 70 s (1 sample) and 10 s (9 samples) per quarter
    """

    def __init__(self, period):
        self.ends = period.interval_ends(15)

    def tomtom_mapping(self, site):
        return {"uuid": "u", "approaches": {"A": {"link": "LA", "street": "A Street", "direction": "SOUTH"},
                                            "B": {"link": "LB", "street": "B Street", "direction": "WEST"}},
                "exits": {"X1": {"direction": "SOUTH"}, "X2": {"direction": "EAST"}}}

    def tomtom_turn_kpi(self, site, start, end):
        rows = []
        for t in self.ends:
            for approach, exit_id, field, value in [
                    ("A", "X1", "approach_delay", 50), ("A", "X1", "control_delay", 10), ("A", "X1", "sample_count", 5),
                    ("A", "X2", "approach_delay", 50), ("A", "X2", "control_delay", -5), ("A", "X2", "sample_count", 5),
                    ("B", "X1", "approach_delay", 20), ("B", "X1", "control_delay", 70), ("B", "X1", "sample_count", 1),
                    ("B", "X2", "approach_delay", 20), ("B", "X2", "control_delay", 10), ("B", "X2", "sample_count", 9)]:
                rows.append({"approach": approach, "exit": exit_id, "field": field, "time": t, "value": value})
        return rows

    def tomtom_queue(self, site, start, end):
        raise DataUnavailable("no queue in this test")

    def tomtom_site_kpi(self, site, start, end):
        return [{"field": "control_delay", "time": t, "value": -3.0} for t in self.ends]


def site():
    approach = lambda link, street, bound, status: {"link": link, "street": street, "bound": bound, "status": status,
                                                    "direction": "HIGH" if status == "ABNORMAL" else None}
    return {"site": "1", "q1": {"approaches": [approach("LA", "A Street", "N", "NORMAL"),
                                               approach("LB", "B Street", "E", "ABNORMAL")]},
            "q3": {"components": {"phase_service": {"approaches": []}}}}


class ControlDelayTests(unittest.TestCase):
    def setUp(self):
        self.rules = copy.deepcopy(Settings().rules)
        self.period = timewin.period_ending(END, self.rules)
        self.source = StubTomTom(self.period)

    def measure(self):
        m = d002.measure(self.source, site(), self.period, self.rules)
        return m, {a["link"]: a for a in m["approaches"]}

    def test_ranked_by_control_delay_by_default(self):
        m, by = self.measure()
        self.assertEqual(m["delay_metric"], "control_delay")
        self.assertEqual((by["LA"]["delay_s"], by["LB"]["delay_s"]), (5.0, 40.0))
        self.assertEqual((by["LA"]["approach_delay_s"], by["LB"]["approach_delay_s"]), (50.0, 20.0))   # still reported
        comp = d002.compare(m, d002.scats_approaches(site()))
        self.assertEqual(comp["greatest_delay"]["link"], "LB")
        self.assertEqual(comp["agreement"], d002.AGREE)
        text = d002.written({"available": True, "comparison": comp, "scats_approaches": d002.scats_approaches(site()),
                             "queue": "unavailable", "coverage_note": ""})["road_user_impact"]
        self.assertIn("greatest TomTom control delay", text)

    def test_negative_delay_counts_as_zero(self):
        m, by = self.measure()
        x2 = next(mv for mv in by["LA"]["movements"] if mv["exit"] == "X2")
        self.assertEqual(x2["control_delay_s"], 0.0)
        self.assertEqual(m["site_control_delay_s"], 0.0)
        self.rules["tomtom"]["negative_delay"] = "keep"
        _, by = self.measure()
        self.assertEqual(by["LA"]["control_delay_s"], 2.5)

    def test_plain_mean_like_the_chatbot_or_sample_weighted(self):
        _, by = self.measure()
        self.assertEqual(by["LB"]["control_delay_s"], 40.0)                 # (70 + 10) / 2
        self.rules["tomtom"]["delay_mean"] = "sample_weighted"
        _, by = self.measure()
        self.assertEqual(by["LB"]["control_delay_s"], 16.0)                 # (70*1 + 10*9) / 10

    def test_approach_delay_option(self):
        self.rules["tomtom"]["delay_metric"] = "approach_delay"
        m, _ = self.measure()
        comp = d002.compare(m, d002.scats_approaches(site()))
        self.assertEqual(comp["greatest_delay"]["link"], "LA")
        self.assertEqual(comp["agreement"], d002.DISAGREE)


if __name__ == "__main__":
    unittest.main()
