import unittest

from diagnostics import rank
from diagnostics.settings import load_rules

RULES = load_rules()


def row(label, cur, usual, lo, hi, d, n=8):
    return {"label": label, "current": cur, "usual": usual, "p_low": lo, "p_high": hi, "direction": d,
            "status": "ABNORMAL", "n_history": n, "pct_difference": 0}


def site(sid, cat="red", volume=(), service=(), veh_h=1000, tolerated=()):
    normal = {"status": "NORMAL"}
    return {"site": sid, "name": sid, "category": cat, "total_volume_veh_h": veh_h, "q2": {"tolerated": list(tolerated)},
            "q1": {"approaches": list(volume)},
            "q3": {"components": {"cycle_length": normal, "cycle_stability": normal,
                                  "phase_service": {"approaches": list(service)}}}}


class RankTests(unittest.TestCase):
    def test_poisson_floor_for_small_volumes(self):
        # range 9-11 gives a spread of 0.78 veh, below sqrt(10) = 3.16: z = 6 / 3.16
        f = rank.findings(site("1", volume=[row("A", 16, 10, 9, 11, "HIGH")]), RULES["rank"])
        self.assertAlmostEqual(f[0]["z"], 6 / 10 ** 0.5, places=3)

    def test_z_is_capped(self):
        f = rank.findings(site("1", volume=[row("A", 3000, 1000, 990, 1010, "HIGH")]), RULES["rank"])
        self.assertEqual(f[0]["z"], 5)

    def test_one_phase_counts_once(self):
        s = site("1", service=[row("A", 20, 40, 38, 42, "LOW"), row("B", 20, 40, 38, 42, "LOW")])
        f = rank.findings(s, RULES["rank"])
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["approach"], "A and B (one phase)")

    def test_factors(self):
        base = rank.score(site("1", volume=[row("A", 150, 100, 90, 110, "HIGH")]), RULES)
        opp = rank.score(site("1", volume=[row("A", 150, 100, 90, 110, "HIGH")],
                              service=[row("A", 20, 40, 38, 42, "LOW")]), RULES)
        self.assertEqual(opp["type_factor"], 1.25)
        thin = rank.score(site("1", volume=[row("A", 150, 100, 90, 110, "HIGH", n=5)], tolerated=[3]), RULES)
        self.assertAlmostEqual(thin["confidence"], 0.64)
        self.assertAlmostEqual(thin["score"], round(base["score"] * 0.64, 2), places=1)
        pers = rank.score(site("1", volume=[row("A", 150, 100, 90, 110, "HIGH")]), RULES, persistence=2)
        self.assertEqual(pers["persistence_factor"], 1.5)
        self.assertEqual(rank.score(site("1", volume=[row("A", 150, 100, 90, 110, "HIGH")], veh_h=1000), RULES)["impact"], 1.0)

    def test_ranks_within_category_and_sets_mapping_apart(self):
        sites = [site("1", volume=[row("A", 125, 100, 90, 110, "HIGH")]),            # z 2.5 x 1.25 < z 5
                 site("2", volume=[row("A", 300, 100, 90, 110, "HIGH")]),
                 site("3", cat="amber_traffic", volume=[row("A", 150, 100, 90, 110, "HIGH")]),
                 site("4", service=[row("A", 57, 100, 100, 100, "LOW")]),
                 site("5", cat="normal")]
        r = rank.rank(sites, RULES, previous=[{"1": "red", "3": "red"}, None])
        self.assertEqual([x["site"] for x in r["red"]], ["2", "1"])
        self.assertEqual([x["rank"] for x in r["red"]], [1, 2])
        self.assertEqual(r["red"][1]["persistence"], 1)
        self.assertEqual(r["amber_traffic"][0]["persistence"], 1)              # Red counts for an Amber site
        self.assertEqual([x["site"] for x in r["mapping_suspect"]], ["4"])
        self.assertNotIn("5", [x["site"] for c in r.values() for x in c])

    def test_no_previous_run_means_no_persistence(self):
        r = rank.rank([site("1", volume=[row("A", 150, 100, 90, 110, "HIGH")])], RULES, previous=[None, None])
        self.assertIsNone(r["red"][0]["persistence"])
        self.assertEqual(r["red"][0]["persistence_factor"], 1.0)


class RankOnContractSitesTests(unittest.TestCase):
    def test_rank_from_the_contract_screening_result(self):
        """The add-on is called on SiteScreeningResult models (README): Red and Amber sites through site_from_model."""
        from datetime import datetime, timezone
        from diagnostics import timewin
        from diagnostics.baseline import BaselineBuilder
        from diagnostics.contract import adapter
        from diagnostics.local.fake import FakeSource
        from diagnostics.service import DiagnosticsService
        from diagnostics.settings import Settings
        from diagnostics.store import SQLiteStore
        settings = Settings()
        period = timewin.period_ending(datetime(2026, 10, 27, 8, 30, tzinfo=timezone.utc), settings.rules)
        source = FakeSource(settings.rules, settings.schema, period.end, n_sites=20)
        svc = DiagnosticsService(source, settings, SQLiteStore(":memory:"), None, archive=None)
        view = svc.screen(period.end, now=period.end + timewin.timedelta(hours=1))
        payload = svc.store.get_run(view["run_id"])["payload"]
        result = adapter.screening_result(payload, settings, run=view["run_id"])
        sites = [adapter.site_from_model(s) for s in result.sites if s.category.value in rank.RANKED]
        ranked = rank.rank(sites, RULES, None)
        self.assertEqual(sum(len(ranked[c]) for c in rank.RANKED) + len(ranked["mapping_suspect"]), len(sites))
