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
                                                 "total_volume_veh_h"})
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
        self.assertIn("longest mean queue is on Swanston Street [N]", section["text"])
        self.assertIn("Mean queue (m)", section["tables"][0]["columns"])

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
