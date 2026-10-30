import unittest
from datetime import date, datetime, timedelta, timezone

from diagnostics import ids, stats, timewin
from diagnostics.series import Aligner, grid_point, window_values
from diagnostics.settings import Settings, load_rules

UTC = timezone.utc
RULES = load_rules()


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class PeriodTests(unittest.TestCase):
    def test_latest_period_is_latest_completed_after_latency(self):
        # 14:07 local (AEDT, UTC+11) minus 5 min latency -> 14:02 -> period 13:30-14:00
        now = utc(2026, 10, 30, 3, 7)
        p = timewin.latest_period(RULES, now)
        self.assertEqual(p.local_start.strftime("%H:%M"), "13:30")
        self.assertEqual(p.local_end.strftime("%H:%M"), "14:00")

    def test_latency_can_step_back_a_period(self):
        p = timewin.latest_period(RULES, utc(2026, 10, 30, 3, 3))   # 14:03 local -> 13:58
        self.assertEqual(p.slot, "13:00")

    def test_end_labelled_quarters(self):
        p = timewin.period_ending("2026-10-30T14:00:00+11:00", RULES)
        ends = [e.astimezone(timewin.zone(RULES)).strftime("%H:%M") for e in p.interval_ends(15)]
        self.assertEqual(ends, ["13:45", "14:00"])
        five = p.interval_ends(5, 60)
        self.assertEqual(len(five), 12)
        self.assertEqual(five[0].astimezone(timewin.zone(RULES)).strftime("%H:%M"), "13:05")
        self.assertEqual(five[-1], p.end)

    def test_period_must_be_on_boundary(self):
        with self.assertRaises(ValueError):
            timewin.period_ending("2026-10-30T14:15:00+11:00", RULES)

    def test_naive_period_end_is_local(self):
        p = timewin.period_ending("2026-05-12T08:30", RULES)
        self.assertEqual(p.end, utc(2026, 5, 11, 22, 30))          # AEST, UTC+10
        self.assertEqual(p.slot, "08:00")

    def test_midnight_period_belongs_to_previous_day(self):
        p = timewin.period_ending("2026-05-13T00:00", RULES)
        self.assertEqual(p.day, date(2026, 5, 12))
        self.assertEqual(p.slot, "23:30")

    def test_reference_periods_go_back_eight_weeks_from_the_chosen_day(self):
        p = timewin.period_ending("2026-05-12T08:30", RULES)       # Tuesday in May
        used, skipped = timewin.reference_periods(p, RULES)
        days = [r.day for r in used] + [date.fromisoformat(d) for d in skipped]
        self.assertEqual(sorted(days), [date(2026, 5, 12) - timedelta(weeks=k) for k in range(8, 0, -1)])
        self.assertTrue(all(r.slot == "08:00" and r.weekday == 1 for r in used))
        self.assertTrue(all(r.day < p.day for r in used))

    def test_reference_periods_keep_local_clock_across_dst(self):
        p = timewin.period_ending("2026-04-14T08:30", RULES)       # after DST ended on 5 Apr
        used, _ = timewin.reference_periods(p, RULES)
        self.assertTrue(all(r.local_start.strftime("%H:%M") == "08:00" for r in used))
        offsets = {r.local_start.utcoffset() for r in used}
        self.assertEqual(len(offsets), 2)                          # AEDT and AEST weeks

    def test_holiday_and_dst_weeks_are_skipped_not_replaced(self):
        p = timewin.period_ending("2026-04-12T10:00", RULES)       # Sunday; 5 Apr = Easter Sunday and DST day
        used, skipped = timewin.reference_periods(p, RULES)
        self.assertIn("2026-04-05", skipped)
        self.assertEqual(len(used) + len(skipped), 8)

    def test_year_end_is_excluded(self):
        p = timewin.period_ending("2026-01-07T10:00", RULES)       # Wednesday; 31 Dec is year-end
        _, skipped = timewin.reference_periods(p, RULES)
        self.assertTrue(skipped["2025-12-31"].startswith("year-end"))


class AlignmentTests(unittest.TestCase):
    def test_on_grid_snapped_and_dropped(self):
        a = Aligner(RULES["alignment"])
        points = [(utc(2026, 1, 1, 1, 15), 10), (utc(2026, 1, 1, 1, 30, 40), 11),
                  (utc(2026, 1, 1, 1, 40), 99), (utc(2026, 1, 1, 1, 45), "12")]
        series = a.align(points, 15)
        self.assertEqual(series, {utc(2026, 1, 1, 1, 15): 10, utc(2026, 1, 1, 1, 30): 11, utc(2026, 1, 1, 1, 45): 12})
        self.assertEqual(a.stats["off_grid_dropped"], 1)
        self.assertEqual(a.stats["snapped"], 1)

    def test_record_is_never_moved_into_the_next_interval(self):
        # 01:10 is 5 minutes before 01:15: not snapped, dropped (does not become the 01:15 record)
        self.assertIsNone(grid_point(utc(2026, 1, 1, 1, 10), 15, 60, "drop"))
        self.assertEqual(grid_point(utc(2026, 1, 1, 1, 10), 15, 60, "ceil"), utc(2026, 1, 1, 1, 15))

    def test_duplicates_keep_latest(self):
        a = Aligner(RULES["alignment"])
        series = a.align([(utc(2026, 1, 1, 1, 14, 30), 1), (utc(2026, 1, 1, 1, 15, 20), 2)], 15)
        self.assertEqual(series[utc(2026, 1, 1, 1, 15)], 2)
        self.assertEqual(a.stats["duplicates"], 1)

    def test_missing_is_not_zero(self):
        a = Aligner(RULES["alignment"])
        series = a.align([(utc(2026, 1, 1, 1, 15), None), (utc(2026, 1, 1, 1, 30), "n/a")], 15)
        self.assertEqual(series, {})
        self.assertIsNone(window_values(series, [utc(2026, 1, 1, 1, 15), utc(2026, 1, 1, 1, 30)]))
        self.assertEqual(a.stats["invalid_values"], 2)


class IdTests(unittest.TestCase):
    def test_sites(self):
        self.assertEqual(ids.site("S4397"), "4397")
        self.assertEqual(ids.site(4397), "4397")
        self.assertEqual(ids.site_tag("4397", "S"), "S4397")
        self.assertEqual(ids.site_tag("S4397", "plain"), "4397")

    def test_links_strip_only_the_ends(self):
        self.assertEqual(ids.link("'MSMJ835J8C7"), "MSMJ835J8C7")
        self.assertEqual(ids.link(" ‘LONSQ9R9Q9XR’ "), "LONSQ9R9Q9XR")
        self.assertEqual(ids.link("'BW`82W283W5"), "BW`82W283W5")
        self.assertIsNone(ids.link("''"))


class CompareTests(unittest.TestCase):
    hist = [100, 102, 98, 101, 99, 100, 103, 97]

    def env(self, values=None):
        return stats.envelope(self.hist if values is None else values, RULES)

    def test_envelope_needs_five(self):
        self.assertIsNone(self.env([1, 2, 3, 4])["usual"])
        self.assertEqual(self.env([1, 2, 3, 4, 5])["usual"], 3)

    def test_two_sided_needs_range_and_percentage(self):
        self.assertEqual(stats.two_sided(130, self.env(), 10)["status"], stats.ABNORMAL)
        self.assertEqual(stats.two_sided(130, self.env(), 10)["direction"], "HIGH")
        self.assertEqual(stats.two_sided(105, self.env(), 10)["status"], stats.NORMAL)   # outside, < 10%
        self.assertEqual(stats.two_sided(None, self.env(), 10)["status"], stats.INSUFFICIENT)

    def test_poorer_only(self):
        e = self.env()
        self.assertEqual(stats.poorer_only(80, e, True)["status"], stats.ABNORMAL)
        self.assertEqual(stats.poorer_only(120, e, True)["status"], stats.NORMAL)       # better is not flagged
        self.assertEqual(stats.poorer_only(120, e, False)["status"], stats.ABNORMAL)

    def test_range_only_has_no_percentage(self):
        e = self.env()
        self.assertEqual(stats.range_only(96.5, e)["direction"], "LOW")
        self.assertEqual(stats.range_only(104, e)["direction"], "HIGH")
        self.assertEqual(stats.range_only(100, e)["status"], stats.NORMAL)


class SettingsTests(unittest.TestCase):
    def test_baseline_version_changes_with_rules(self):
        a = Settings()
        b = Settings(rules=load_rules(overrides={"history": {"weeks": 6}}))
        self.assertNotEqual(a.baseline_version, b.baseline_version)
        c = Settings(rules=load_rules(overrides={"q2": {"min_vehicles": 20}}))
        self.assertEqual(a.baseline_version, c.baseline_version)


if __name__ == "__main__":
    unittest.main()
