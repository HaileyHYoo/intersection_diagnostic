import json
import threading
import unittest

from diagnostics import llm as llm_mod
from diagnostics.local.fake import FakeSource
from diagnostics.service import DiagnosticsService
from diagnostics.settings import Settings
from diagnostics.store import SQLiteStore
from diagnostics.templates import catalog
from diagnostics.templates.d002 import UNAVAILABLE

END = "2026-10-27T08:30"


def service(llm=None, n_sites=20):
    s = Settings()
    source = FakeSource(s.rules, s.schema, END + ":00+11:00", n_sites=n_sites)
    return DiagnosticsService(source, s, SQLiteStore(":memory:"), llm)


class StubLLM:
    model = "stub"

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete(self, system, user):
        self.calls += 1
        return self.reply(json.loads(user)) if callable(self.reply) else self.reply


class ScreenServiceTests(unittest.TestCase):
    def test_cached_run_is_reused(self):
        svc = service()
        first = svc.screen(END)
        again = svc.screen(END)
        self.assertFalse(first["cached"])
        self.assertTrue(again["cached"])
        self.assertEqual(first["run_id"], again["run_id"])
        self.assertEqual(svc.screen(END, force=True)["cached"], False)

    def test_concurrent_requests_share_one_run(self):
        svc = service(n_sites=8)
        results = []
        threads = [threading.Thread(target=lambda: results.append(svc.screen(END))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len({r["run_id"] for r in results}), 1)

    def test_map_view_is_compact(self):
        view = service().screen(END)
        self.assertEqual(set(view["sites"][0]), {"site", "name", "lat", "lon", "category", "label", "reasons", "selectable",
                                                 "total_volume_veh_h", "notes"})
        self.assertEqual(view["errors"], {})
        self.assertEqual(view["period"]["slot"], "08:00")
        self.assertEqual(len(view["baseline"]["reference_periods"]), 8)


class DiagnoseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = service()
        cls.run_id = cls.svc.screen(END)["run_id"]

    def report(self, site):
        return self.svc.diagnose(self.run_id, site, reuse=False)

    def section(self, result, n):
        return result["report"]["sections"][n - 1]

    def test_red_click_gives_four_sections(self):
        r = self.report("4300")
        self.assertEqual(r["mode"], "report")
        self.assertEqual([s["title"][:2] for s in r["report"]["sections"]], ["1.", "2.", "3.", "4."])
        self.assertEqual(set(r["templates"]), {"D001", "D002"})
        self.assertIn("Swanston Street [N]", self.section(r, 1)["text"])

    def test_tomtom_agreement_disagreement_and_unavailable(self):
        self.assertEqual(self.report("4300")["templates"]["D002"]["answer"]["agreement"], "agreement")
        self.assertEqual(self.report("4303")["templates"]["D002"]["answer"]["agreement"], "disagreement")
        r = self.report("4306")
        self.assertEqual(self.section(r, 3)["text"], UNAVAILABLE)
        self.assertTrue(self.section(r, 1)["text"])        # D001 still runs

    def test_queue_is_part_of_the_tomtom_section(self):
        section = self.section(self.report("4300"), 3)
        self.assertIn("and the longest mean queue (", section["text"])
        self.assertIn("are all on Swanston Street [N]", section["text"])
        self.assertIn("Mean queue (m)", section["tables"][0]["columns"])

    def test_tomtom_answer_names_each_scats_approach(self):
        agree = self.section(self.report("4300"), 3)["text"]
        self.assertIn("Swanston Street [N], identified by the SCATS screening (volume above its normal range; "
                      "phase service below its normal range), "
                      "has the greatest control delay, the greatest approach delay and the longest queue.", agree)
        mismatch = self.section(self.report("4303"), 3)["text"]
        self.assertIn("has neither the greatest control delay, the greatest approach delay nor the longest queue.", mismatch)
        self.assertIn("do not confirm", mismatch)

    def test_per_approach_sentences(self):
        from diagnostics.templates import d002
        p = lambda **kw: {"approach": "A St [N]", "scats_findings": ["Q1 low"], **kw}
        s = d002._per_approach_sentence
        self.assertTrue(s(p(agreement=d002.AGREE, has_largest_delay=True, has_largest_queue=False))
                        .endswith("has the greatest delay but not the longest queue."))
        self.assertTrue(s(p(agreement=d002.AGREE, has_largest_delay=False, has_largest_queue=True))
                        .endswith("has the longest queue but not the greatest delay."))
        self.assertTrue(s(p(agreement=d002.DISAGREE, has_largest_delay=False, has_largest_queue=None))
                        .endswith("does not have the greatest delay (queue not known)."))
        self.assertEqual(s(p(agreement=d002.NO_COVERAGE, has_largest_delay=None, has_largest_queue=None)),
                         "A St [N], identified by the SCATS screening, has no adequate TomTom coverage in this period.")

    def test_other_categories_show_evidence_only(self):
        for site in ("4309", "4318", "4321", "4345"):
            r = self.svc.diagnose(self.run_id, site)
            self.assertEqual(r["mode"], "evidence")
            self.assertIn("q2", r["site"])

    def test_diagnosis_is_saved_and_reused(self):
        first = self.svc.diagnose(self.run_id, "4342")
        second = self.svc.diagnose(self.run_id, "4342")
        self.assertTrue(second["cached"])
        self.assertEqual(first["id"], second["id"])

    def test_records_carry_config_provenance_and_registry_ids(self):
        run = self.svc.store.get_run(self.run_id)["payload"]
        self.assertEqual(self.svc.store.get_config(run["config_version"])["rules"]["history"]["weeks"], 8)
        self.assertTrue(run["provenance"])
        r = self.report("4300")
        self.assertEqual(r["templates"]["D001"]["registry"]["template_id"], "ID_Q4_SCATS_INTERPRETATION")
        self.assertEqual(r["config_version"], run["config_version"])

    def test_catalog_definitions(self):
        c = catalog()
        for key in ("id", "version", "question", "allowed_parameters", "source_fields", "execution_path",
                    "output", "missing_data", "constraints"):
            self.assertIn(key, c["D001"])
            self.assertIn(key, c["D002"])


class LLMGuardTests(unittest.TestCase):
    def run_site(self, llm):
        svc = service(llm, n_sites=4)
        run_id = svc.screen(END)["run_id"]
        return svc.diagnose(run_id, "4300")

    def test_answer_using_evidence_numbers_is_accepted(self):
        def reply(payload):
            draft = payload["draft_answer"]
            return json.dumps(draft)
        llm = StubLLM(reply)
        r = self.run_site(llm)
        self.assertEqual(r["templates"]["D001"]["generated_by"], "llm:stub")
        self.assertIsNone(r["templates"]["D001"]["rejected"])

    def test_invented_numbers_are_rejected(self):
        llm = StubLLM(json.dumps({"diagnosis": "Volume is 73.9% above usual.", "supporting_evidence": [],
                                  "suggested_checks": [], "road_user_impact": "x", "agreement": "x", "coverage": "x"}))
        r = self.run_site(llm)
        d001 = r["templates"]["D001"]
        self.assertEqual(d001["generated_by"], "code")
        self.assertIn("73.9", d001["rejected"])

    def test_within_contradiction_is_rejected(self):
        from diagnostics.templates import d001
        ev = {"signal": {"cycle_length_s": {"position": "within its normal range"},
                         "cycle_stability": {"position": "above its normal range"}}}
        bad = {"diagnosis": "x", "supporting_evidence": ["Signal stability was normal, with 86.4 within its normal range."]}
        self.assertEqual(d001.contradictions(bad, ev), ["says stability is within its normal range; it is above its normal range"])
        good = {"diagnosis": "x", "supporting_evidence": ["Cycle stability was 86.4, above its normal range; only poorer "
                                                          "stability is flagged. Cycle length was within its normal range."]}
        self.assertEqual(d001.contradictions(good, ev), [])

    def test_position_explains_a_normal_value_outside_the_range(self):
        from diagnostics.templates import d001
        c = {"status": "NORMAL", "current": 86.4, "usual": 54.9, "p_low": 16.1, "p_high": 78.7, "pct_difference": 57.4,
             "direction": None}
        self.assertEqual(d001.position(c), "above its normal range")

    def test_tomtom_caveat_is_always_kept(self):
        from diagnostics.templates import d002

        class Short:
            model = "m"

            def complete(self, system, user):
                import json
                draft = json.loads(user)["draft_answer"]
                return json.dumps({**draft, "road_user_impact": draft["road_user_impact"].replace(d002.CAVEAT, "")})
        svc = service()
        svc.llm = Short()
        r = svc.diagnose(svc.screen(END)["run_id"], "4300", reuse=False)
        self.assertTrue(r["templates"]["D002"]["answer"]["road_user_impact"].endswith(d002.CAVEAT))

    def test_a_value_on_a_rounded_bound_gets_more_decimals(self):
        from diagnostics.report import _values
        self.assertEqual(_values({"current": 67.58, "usual": 73.1, "p_low": 67.62, "p_high": 73.5}),
                         ["67.58", "73.10", "67.62-73.50"])
        self.assertEqual(_values({"current": 80.0, "usual": 80.0, "p_low": 80.0, "p_high": 83.8}),
                         ["80.0", "80.0", "80.0-83.8"])                               # equal, not merely rounded
        self.assertEqual(_values({"current": 105.9, "usual": 86.5, "p_low": 77.3, "p_high": 99.7}),
                         ["105.9", "86.5", "77.3-99.7"])

    def test_d001_evidence_keeps_the_decimals_of_the_table(self):
        from diagnostics.templates import d001
        site = {"site": "1", "name": "x", "label": "Red", "q1": {"status": "ABNORMAL", "approaches": []},
                "q3": {"status": "ABNORMAL", "abnormal_count": 2, "components": {
                    "cycle_length": {"status": "NORMAL", "current": 140.5, "usual": 137.4, "p_low": 132.7, "p_high": 140.9,
                                     "pct_difference": 2.3, "direction": None},
                    "cycle_stability": {"status": "ABNORMAL", "current": 67.56, "usual": 73.1, "p_low": 67.63,
                                        "p_high": 73.46, "pct_difference": -7.6, "direction": "POORER"},
                    "phase_service": {"status": "NORMAL", "approaches": []}}}}
        ev = d001.evidence(site, {"local": "p"})
        self.assertEqual((ev["signal"]["cycle_stability"]["current"], ev["signal"]["cycle_stability"]["normal_range"]),
                         (67.56, [67.63, 73.46]))
        self.assertIn("Cycle Stability: 67.56 against a usual 73.10 (normal range 67.63-73.46) - abnormal.",
                      d001.written(ev)["supporting_evidence"])

    def test_numbers_are_compared_by_value(self):
        from diagnostics import llm
        allowed = llm.allowed_numbers({"stability": 0.0, "period": "Fri 30 Oct 2026"})
        self.assertEqual(llm.check({"a": "Stability was 0.00 (00) at 15:00"}, ["a"], allowed | {"15"}), [])
        self.assertTrue(llm.check({"a": "Stability was 7.5"}, ["a"], allowed))      # a real invented number

    def test_an_omitted_approach_is_rejected(self):
        from diagnostics import llm
        required = {"a": ["A St [N]", "B St [E]"]}
        self.assertEqual(llm.check({"a": "A St [N] agrees; B St [E] does not"}, ["a"], set(), required), [])
        problems = llm.check({"a": "A St [N] agrees"}, ["a"], set(), required)
        self.assertEqual(problems, ["'a' omits: B St [E]"])

    def test_forbidden_claims_are_rejected(self):
        problems = llm_mod.check({"diagnosis": "The detector is faulty and the delay is caused by SCATS."},
                                 ["diagnosis"], set())
        self.assertTrue(any("forbidden" in p for p in problems))

    def test_llm_failure_falls_back_to_code(self):
        class Broken:
            model = "broken"

            def complete(self, system, user):
                raise TimeoutError("slow")
        r = self.run_site(Broken())
        self.assertEqual(r["templates"]["D001"]["generated_by"], "code")
        self.assertIn("TimeoutError", r["templates"]["D001"]["rejected"])

    def test_agreement_verdict_is_never_reworded(self):
        def reply(payload):
            if "road_user_impact" in payload["draft_answer"]:
                return json.dumps({**payload["draft_answer"], "agreement": "agreement"})
            return json.dumps(payload["draft_answer"])
        svc = service(StubLLM(reply), n_sites=4)
        run_id = svc.screen(END)["run_id"]
        r = svc.diagnose(run_id, "4303")
        self.assertEqual(r["templates"]["D002"]["answer"]["agreement"], "disagreement")


if __name__ == "__main__":
    unittest.main()


class D001PointsTests(unittest.TestCase):
    """A1 phrase kept, one phase reported once, one incident check, mapping and detector caveats (12 Nov review)."""

    @staticmethod
    def site(service, traffic, tolerated=()):
        def row(label, link, cur, usual, lo, hi, d):
            return {"label": label, "link": link, "current": cur, "usual": usual, "p_low": lo, "p_high": hi,
                    "direction": d, "status": "ABNORMAL", "pct_difference": 10.0}
        normal = {"status": "NORMAL", "current": 90.0, "usual": 90.0, "p_low": 85.0, "p_high": 95.0,
                  "pct_difference": 0.0, "direction": None}
        return {"site": "1", "name": "x", "label": "Red",
                "q2": {"threshold": 10, "tolerated": list(tolerated),
                       "detectors": [{"detector": d, "count_60min": 3} for d in tolerated]},
                "q1": {"status": "ABNORMAL", "approaches": [row(*t) for t in traffic]},
                "q3": {"status": "ABNORMAL", "abnormal_count": 2, "components": {
                    "cycle_length": normal, "cycle_stability": {**normal, "direction": None},
                    "phase_service": {"status": "ABNORMAL", "approaches": [row(*s) for s in service]}}}}

    def written(self, site):
        from diagnostics.templates import d001
        ev = d001.evidence(site, {"local": "p"})
        return ev, d001.written(ev)

    def test_identical_green_share_is_one_phase(self):
        ev, w = self.written(self.site([("A St [N]", "a", 20.0, 40.0, 35.0, 45.0, "LOW"),
                                        ("A St [S]", "b", 20.0, 40.0, 35.0, 45.0, "LOW")], []))
        self.assertEqual(ev["phase_groups"], [["A St [N]", "A St [S]"]])
        self.assertEqual(sum("Phase service" in x for x in w["supporting_evidence"]), 1)
        self.assertEqual(sum(x.startswith("Check phase service") for x in w["suggested_checks"]), 1)
        self.assertIn("A St [N] and A St [S] (one phase)", w["diagnosis"])

    def test_one_incident_check_for_all_traffic_only_approaches(self):
        _, w = self.written(self.site([], [("A St [N]", "a", 150.0, 100.0, 80.0, 120.0, "HIGH"),
                                           ("B St [E]", "b", 150.0, 100.0, 80.0, 120.0, "HIGH")]))
        incident = [x for x in w["suggested_checks"] if x.startswith("Check for incidents")]
        self.assertEqual(len(incident), 1)
        self.assertIn("A St [N] and B St [E]", incident[0])

    def test_opposite_direction_phrase_must_be_kept(self):
        from diagnostics.templates import d001
        ev, w = self.written(self.site([("A St [N]", "a", 20.0, 40.0, 35.0, 45.0, "LOW")],
                                       [("A St [N]", "a", 150.0, 100.0, 80.0, 120.0, "HIGH")]))
        self.assertIn(d001.OPPOSITE, w["diagnosis"])
        self.assertEqual(d001.kept_points(w, ev), [])
        softened = {**w, "diagnosis": w["diagnosis"].replace(d001.OPPOSITE, "a possible mismatch")}
        self.assertEqual(d001.kept_points(softened, ev), [f'drops "{d001.OPPOSITE}"'])

    def test_usual_100_percent_green_is_a_mapping_check(self):
        from diagnostics.templates import d001
        ev, w = self.written(self.site([("A St [N]", "a", 57.2, 100.0, 100.0, 100.0, "LOW")], []))
        self.assertTrue(w["suggested_checks"][0].startswith("Verify the phase-to-approach assignment of A St [N]"))
        self.assertIn("mapping", w["diagnosis"])
        self.assertEqual(d001.kept_points({"diagnosis": "x"}, ev), ["drops the mapping caveat"])

    def test_tolerated_detector_may_under_count(self):
        _, w = self.written(self.site([], [("A St [N]", "a", 150.0, 100.0, 80.0, 120.0, "HIGH")], tolerated=[7]))
        self.assertIn("detector 7 counted fewer than 10 vehicles", w["diagnosis"])
        self.assertTrue(any(x.startswith("Check detector 7 (3 vehicles") for x in w["suggested_checks"]))
