import unittest
from datetime import datetime, timezone

from diagnostics import screening, stats, timewin
from diagnostics.baseline import BaselineBuilder
from diagnostics.local.fake import FakeSource
from diagnostics.settings import Settings, load_rules
from diagnostics.sources.influx import build_flux
from diagnostics.stats import ABNORMAL, INSUFFICIENT, NORMAL
from diagnostics.store import SQLiteStore


def run(settings=None, n_sites=20, end="2026-10-27T08:30"):
    settings = settings or Settings()
    period = timewin.period_ending(end, settings.rules)
    source = FakeSource(settings.rules, settings.schema, period.end, n_sites=n_sites)
    builder = BaselineBuilder(source, settings, SQLiteStore(":memory:"))
    result = screening.screen(source, settings, builder.get(period), period)
    return source, builder, {r["site"]: r for r in result["sites"]}, result


class NetworkScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.builder, cls.sites, cls.result = run()

    def test_every_scenario_gets_its_category(self):
        expected = self.source.expected()
        got = {s: r["category"] for s, r in self.sites.items()}
        self.assertEqual(got, expected)

    def test_red_site_evidence(self):
        red = self.sites["4300"]
        self.assertEqual(red["q1"]["status"], ABNORMAL)
        self.assertEqual([a["bound"] for a in red["q1"]["approaches"] if a["status"] == ABNORMAL], ["N"])
        comps = red["q3"]["components"]
        self.assertEqual(comps["cycle_stability"]["status"], ABNORMAL)
        self.assertEqual(comps["phase_service"]["status"], ABNORMAL)
        low = [a for a in comps["phase_service"]["approaches"] if a["status"] == ABNORMAL]
        self.assertEqual([(a["bound"], a["direction"]) for a in low], [("N", "LOW")])
        self.assertEqual(red["selectable"], ["D001", "D002"])

    def test_detector_failure_is_not_grey(self):
        site = self.sites["4318"]
        self.assertEqual(site["q2"]["status"], screening.FAIL)
        self.assertEqual(site["q2"]["failed"], [3])
        self.assertIsNone(site["q1"])                  # Q1/Q3 are not run after a failed gate

    def test_inactive_detector_is_ignored(self):
        site = self.sites["4339"]
        self.assertNotIn(9, [d["detector"] for d in site["q2"]["detectors"]])

    def test_short_phase_service_history_leaves_q3_to_the_other_two(self):
        site = self.sites["4345"]
        comps = site["q3"]["components"]
        self.assertEqual(comps["phase_service"]["status"], INSUFFICIENT)
        short = [a for a in comps["phase_service"]["approaches"] if a["status"] == INSUFFICIENT]
        self.assertEqual([a["n_history"] for a in short], [1])
        self.assertEqual(site["q3"]["assessable_count"], 2)
        self.assertEqual(site["category"], "normal")

    def test_links_without_history_are_not_evaluated(self):
        site = self.sites["4333"]
        self.assertEqual(sorted(a["link"][:4] for a in site["q1"]["not_evaluated"]), ["DEAD", "NEWL"])

    def test_dirty_feed_is_cleaned(self):
        counts = self.result["alignment"]
        self.assertGreater(counts["snapped"], 0)
        self.assertGreater(counts["duplicates"], 0)
        self.assertGreater(counts["off_grid_ceiled"], 0)       # the off-grid 9999 record lost to the real one
        self.assertEqual(self.sites["4336"]["category"], "normal")

    def test_no_green_greys_the_site_and_can_be_switched_off(self):
        self.assertEqual(self.sites["4327"]["category"], "grey")
        settings = Settings(rules=load_rules(overrides={"q3c": {"grey_site_if_any_approach_without_green": False}}))
        _, _, sites, _ = run(settings)
        q3c = sites["4327"]["q3"]["components"]["phase_service"]
        self.assertFalse(q3c["grey_site"])
        self.assertEqual(q3c["status"], INSUFFICIENT)  # still not assessable as a component
        self.assertEqual(sites["4327"]["category"], "normal")   # Q3 decided by the other two measures

    def test_reference_weeks_for_a_chosen_may_day(self):
        settings = Settings()
        period = timewin.period_ending("2026-05-12T08:30", settings.rules)
        source = FakeSource(settings.rules, settings.schema, period.end, n_sites=4)
        base = BaselineBuilder(source, settings, SQLiteStore(":memory:")).get(period)
        days = [r["start"][:10] for r in base["reference_periods"]]
        self.assertEqual(len(days), 8)
        self.assertTrue(all(d < "2026-05-12" for d in days))
        self.assertEqual(base["period"]["slot"], "08:00")


class BaselineCacheTests(unittest.TestCase):
    def test_reference_values_and_baselines_are_reused(self):
        settings = Settings()
        period = timewin.period_ending("2026-10-27T08:30", settings.rules)
        source = FakeSource(settings.rules, settings.schema, period.end, n_sites=4)
        store = SQLiteStore(":memory:")
        b = BaselineBuilder(source, settings, store)
        b.get(period)
        first = b.fetches
        b.get(period)
        self.assertEqual(b.fetches, first)             # baseline cached
        nxt = timewin.period_ending("2026-11-03T08:30", settings.rules)   # a week later: 7 of 8 refs cached
        b.build(nxt)
        self.assertEqual(b.fetches - first, 1)

    def test_precompute_fetches_each_reference_day_once(self):
        settings = Settings()
        source = FakeSource(settings.rules, settings.schema, "2026-10-27T08:30:00+11:00", n_sites=3)
        b = BaselineBuilder(source, settings, SQLiteStore(":memory:"))
        day = datetime(2026, 10, 27).date()
        n = b.precompute([day], slots=["08:00", "08:30", "17:00"])
        self.assertEqual(n, 3)
        self.assertEqual(b.fetches, 8)


class RuleTests(unittest.TestCase):
    rules = Settings().rules

    @staticmethod
    def t(total, records=12, negatives=0):
        return {"total": total, "records": records, "expected": 12, "negatives": negatives}

    def test_q2_observed_failure_wins_over_missing(self):
        dets = [{"detector": 1, "active": True}, {"detector": 2, "active": True}]
        t = self.t
        self.assertEqual(screening.q2_gate(dets, {1: t(3), 2: t(4, records=11)}, self.rules)["status"], screening.FAIL)
        self.assertEqual(screening.q2_gate(dets, {1: t(30), 2: t(4, records=11)}, self.rules)["status"], INSUFFICIENT)
        self.assertEqual(screening.q2_gate(dets, {1: t(30)}, self.rules)["status"], INSUFFICIENT)   # no records at all
        self.assertEqual(screening.q2_gate(dets, {1: t(30), 2: t(10)}, self.rules)["status"], screening.PASS)
        self.assertEqual(screening.q2_gate([], {}, self.rules)["status"], INSUFFICIENT)

    def test_q2_passes_on_eleven_records_when_the_count_is_reached(self):
        dets = [{"detector": 1, "active": True}]
        gate = screening.q2_gate(dets, {1: self.t(10, records=11)}, self.rules)
        self.assertEqual(gate["status"], screening.PASS)
        self.assertEqual(gate["detectors"][0]["records"], 11)
        self.assertEqual(screening.q2_gate(dets, {1: self.t(9, records=11)}, self.rules)["status"], INSUFFICIENT)
        self.assertEqual(screening.q2_gate(dets, {1: self.t(9)}, self.rules)["status"], screening.FAIL)

    def test_negative_five_minute_counts_are_missing(self):
        from datetime import timedelta
        from diagnostics.measures import Measures
        period = timewin.period_ending("2026-10-30T14:30", self.rules)

        class Source:
            def detector_counts(self, start, end, sites=None):
                ends = period.interval_ends(5, 60)
                return [{"site": "1", "detector": 1, "time": t - timedelta(minutes=2), "value": v}
                        for t, v in zip(ends, [19, -10] + [0] * 10)]
        totals = Measures(Source(), self.rules, Settings().schema).detector_totals(period, 60)["1"][1]
        self.assertEqual((totals["total"], totals["records"], totals["negatives"]), (19, 11, 1))
        gate = screening.q2_gate([{"detector": 1, "active": True}], {1: totals}, self.rules)
        self.assertEqual(gate["status"], screening.PASS)                  # 19 from 11 valid records, not 19 - 10 = 9
        low = {**totals, "total": 7}
        self.assertEqual(screening.q2_gate([{"detector": 1, "active": True}], {1: low}, self.rules)["status"],
                         INSUFFICIENT)                                    # below 10 with a record missing: Grey, not FAIL

    def comp(self, status):
        return {"status": status}

    def q3(self, a, b, c):
        q3c = {"status": c, "grey_site": False, "without_green": []}
        env = {"n": 8, "usual": 100.0, "p_low": 95.0, "p_high": 105.0}
        now = {"cycle_length": {NORMAL: 100.0, ABNORMAL: 140.0, INSUFFICIENT: None}[a],
               "cycle_stability": {NORMAL: 100.0, ABNORMAL: 50.0, INSUFFICIENT: None}[b]}
        return screening.q3_signal(now, {"cycle_length": env, "cycle_stability": env}, {}, q3c, self.rules)

    def test_q3_two_of_three(self):
        self.assertEqual(self.q3(ABNORMAL, ABNORMAL, NORMAL)["status"], ABNORMAL)
        self.assertEqual(self.q3(ABNORMAL, NORMAL, NORMAL)["status"], NORMAL)
        self.assertEqual(self.q3(ABNORMAL, INSUFFICIENT, ABNORMAL)["status"], ABNORMAL)
        self.assertEqual(self.q3(ABNORMAL, INSUFFICIENT, NORMAL)["status"], NORMAL)
        self.assertEqual(self.q3(ABNORMAL, INSUFFICIENT, INSUFFICIENT)["status"], INSUFFICIENT)

    def test_classification_matrix(self):
        q2 = {"status": screening.PASS}
        q3c = {"grey_site": False, "without_green": []}
        def cls(q1, q3):
            return screening.classify(q2, {"status": q1, "reason": "x"},
                                      {"status": q3, "components": {"phase_service": q3c}})[0]
        self.assertEqual(cls(NORMAL, NORMAL), "normal")
        self.assertEqual(cls(ABNORMAL, NORMAL), "amber_traffic")
        self.assertEqual(cls(NORMAL, ABNORMAL), "amber_signal")
        self.assertEqual(cls(ABNORMAL, ABNORMAL), "red")
        self.assertEqual(cls(INSUFFICIENT, ABNORMAL), "grey")
        self.assertEqual(cls(ABNORMAL, INSUFFICIENT), "grey")


class GreenShareNoiseTests(unittest.TestCase):
    def test_float_noise_is_not_low_against_a_constant_history(self):
        from datetime import timedelta
        from diagnostics.measures import Measures
        settings = Settings()
        period = timewin.period_ending("2026-10-30T14:30", settings.rules)

        class Source:
            def approach_perf(self, start, end, sites=None):
                rows = []
                for k, t in enumerate(period.interval_ends(15)):
                    stamp = t - timedelta(minutes=8)                       # live feeds write at :07/:22
                    share = 99.99999999999999 if k == 0 else 100.0
                    rows += [{"site": "4397", "link": "GRAT", "bound": "E", "field": "green_share", "time": stamp, "value": share},
                             {"site": "4397", "link": "GRAT", "bound": "E", "field": "has_green", "time": stamp, "value": 1.0}]
                return rows
        value = Measures(Source(), settings.rules, settings.schema).approach_green([period])[period.key]["4397"]["GRAT"]
        self.assertEqual(value["green_share"], 100.0)
        env = stats.envelope([100.0] * 8, settings.rules)
        self.assertEqual(stats.range_only(value["green_share"], env)["status"], NORMAL)


class FluxTests(unittest.TestCase):
    def test_flux_carries_region_and_filters(self):
        flux = build_flux("scats", "volume", datetime(2026, 1, 1, tzinfo=timezone.utc),
                          datetime(2026, 1, 1, 1, tzinfo=timezone.utc), region_tag="Region",
                          region="AU-VIC-Melbourne", filters={"MinutesPast": "15"}, field_regex="^d\\[[0-9]+\\]$",
                          tag_in=("SiteNo", ["S1", "S2"]))
        self.assertIn('r["Region"] == "AU-VIC-Melbourne"', flux)
        self.assertIn('r["MinutesPast"] == "15"', flux)
        self.assertIn("r._field =~ /^d\\[[0-9]+\\]$/", flux)
        self.assertIn('set: ["S1", "S2"]', flux)
        self.assertIn('time(v: "2026-01-01T01:00:00Z")', flux)


if __name__ == "__main__":
    unittest.main()
