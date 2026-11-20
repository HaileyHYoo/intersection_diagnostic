"""TomTom values per approach: movements pooled by vehicles, stops per vehicle, usual values (20 Nov 2026)."""
import copy
import unittest
from datetime import timedelta

from diagnostics import timewin
from diagnostics.settings import Settings
from diagnostics.sources.base import DataUnavailable
from diagnostics.templates import d002

END = "2026-11-10T08:30"

# SCATS 4397, Tue 10 Nov 2026 08:00-08:30, Rathdowne Street northbound (TomTom approach 930123994), from
# `tomtom-check --dump`: (exit, quarter, ApproachDelaySec, ControlDelaySec, AvgStopsPerCar, StopRate, SampleCount)
RATHDOWNE_N = [("left", 0, 31.89, 33.60, 1.0, 1.0, 1), ("left", 1, 34.80, 35.25, 1.0, 1.0, 1),
               ("through", 0, 11.06, 7.56, 1.0, 0.75, 4), ("through", 1, 12.34, 12.43, 0.5, 0.5, 2)]
FIELDS = ("approach_delay", "control_delay", "stops", "stop_rate", "sample_count")


class Source:
    """The 4397 records now; in each reference week the same records with every delay scaled by `scale[week]`."""

    def __init__(self, period, scale=None, missing_weeks=()):
        self.period, self.scale, self.missing = period, scale or {}, set(missing_weeks)

    def _week(self, start):
        return round((self.period.start - start) / timedelta(days=7))

    def tomtom_mapping(self, site):
        return {"uuid": "u", "approaches": {"930123994": {"link": "RATHX97VX9HW", "street": "Rathdowne Street",
                                                          "direction": "NORTH"}},
                "exits": {"left": {"direction": "WEST"}, "through": {"direction": "NORTH"}}}

    def tomtom_turn_kpi(self, site, start, end):
        week = self._week(start)
        if week in self.missing:
            return []
        k = self.scale.get(week, 1.0)
        ends = [end - timedelta(minutes=15), end]
        rows = []
        for exit_id, q, ad, cd, stops, rate, n in RATHDOWNE_N:
            t = ends[q]
            for field, v in zip(FIELDS, (ad * k, cd * k, stops, rate, n)):
                rows.append({"approach": "930123994", "exit": exit_id, "field": field, "time": t, "value": v})
        return rows

    def tomtom_site_kpi(self, site, start, end):
        return []

    def tomtom_queue(self, site, start, end):
        raise DataUnavailable("no queue in this test")


def site():
    return {"site": "4397", "q1": {"approaches": [{"link": "RATHX97VX9HW", "street": "Rathdowne Street", "bound": "N",
                                                  "status": "ABNORMAL", "direction": "HIGH"}]},
            "q3": {"components": {"phase_service": {"approaches": []}}}}


class PooledTests(unittest.TestCase):
    def setUp(self):
        self.rules = copy.deepcopy(Settings().rules)
        self.period = timewin.period_ending(END, self.rules)

    def row(self, source):
        return d002.measure(source, site(), self.period, self.rules)["approaches"][0]

    def test_4397_rathdowne_north_is_pooled_by_vehicles(self):
        r = self.row(Source(self.period))
        # plain mean of the four records was 22.2 s control and 22.5 s approach delay (the report of 17 Nov)
        self.assertEqual((r["control_delay_s"], r["approach_delay_s"]), (15.5, 17.0))
        self.assertEqual((r["stops_per_vehicle"], r["vehicles"]), (0.88, 8))
        through = next(m for m in r["movements"] if m["exit"] == "through")
        self.assertEqual((through["control_delay_s"], through["vehicles"]), (9.2, 6))

    def test_usual_is_the_median_of_the_reference_weeks(self):
        # 7 reference weeks (Melbourne Cup left out); delays doubled in two of them
        r = self.row(Source(self.period, scale={1: 2.0, 3: 2.0}))
        self.assertEqual(r["usual"]["control_delay_s"], 15.5)
        self.assertEqual(r["usual_weeks"]["control_delay_s"], 7)
        self.assertEqual(r["usual"]["stops_per_vehicle"], 0.88)
        self.assertIsNone(r["usual"]["queue_mean_m"])

    def test_two_weeks_are_enough_one_is_not(self):
        weeks = range(1, 9)                           # week 1 (3 Nov, Melbourne Cup) is left out anyway
        r = self.row(Source(self.period, missing_weeks=[w for w in weeks if w not in (2, 3)]))
        self.assertEqual((r["usual"]["control_delay_s"], r["usual_weeks"]["control_delay_s"]), (15.5, 2))
        r = self.row(Source(self.period, missing_weeks=[w for w in weeks if w != 2]))
        self.assertEqual((r["usual"]["control_delay_s"], r["usual_weeks"]["control_delay_s"]), (None, 1))


if __name__ == "__main__":
    unittest.main()
