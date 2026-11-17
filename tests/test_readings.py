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
        self.assertEqual(table["other_phases"]["strength"], "Moderate")     # B,D gained + opposite direction = 4
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


def status_of(site):
    """subsystem_status of 10 Nov 2026 08:00-08:30 (subsystem-check output) as status_context returns it."""
    from datetime import datetime
    from diagnostics.settings import load_rules
    from diagnostics.timewin import period_ending
    d = json.loads((Path(__file__).parent / "data" / f"subsystem_check_{site}.json").read_text(encoding="utf-8"))
    rows = [{"time": datetime.fromisoformat(t), "critical": e["tags"]["CriticalSite"], **e["fields"]}
            for t, e in d["records"].items()]
    return {"now": subsystems._summary(rows, period_ending("2026-11-10T08:30", load_rules())), "usual": {}, "weeks": 0}


class SubsystemStatusTests(unittest.TestCase):
    def test_summary(self):
        n = status_of("3055")["now"]
        self.assertEqual((n["critical_site"], n["records"], n["cl_mean"], n["cl_sd"], n["cl_above_rl"]),
                         ("3055", 15, 120.0, 0.0, 13))
        self.assertEqual([q["ds_median"] for q in n["by_quarter"]], [65.5, 93.0])
        m = status_of("4864")["now"]
        self.assertEqual((m["critical_site"], m["ds_at_least_100"], m["cl_min"], m["cl_max"]), ("4864", 10, 70.0, 90.0))
        # records stamped 20:59:58 and 21:30:27 UTC belong to the cycles before and after the period: left out, the
        # median moves from 83 to 99 (DS swings 34-159 from cycle to cycle), so the mean is compared as well
        self.assertEqual((m["records"], m["ds_median"], m["ds_mean"], m["cl_below_rl"]), (23, 99.0, 94.0, 5))

    def test_3055_held_cycle_and_local_variation(self):
        ctx = subsystems.context("3055", lambda no: None)
        ctx["status"] = status_of("3055")
        ev = d001.evidence(SITE, {"local": "p"}, detail(), None, ctx)
        top = ev["readings"][0]
        self.assertEqual(top["key"], "other_phases")
        self.assertIn("the subsystem's active cycle stayed at 120.0 s while the site's measured cycles varied", " ".join(top["for"]))
        plan = next(r for r in ev["readings"] if r["key"] == "plan")
        self.assertIn("held by a plan, coordination or a configured minimum", " ".join(plan["for"]))
        d = d001.written(ev)["diagnosis"]
        self.assertIn("Subsystem saturation median 78; active cycle constant at 120.0 s, above the required cycle "
                      "(mean 109.5 s).", d)
        self.assertNotIn("at least 3 s above it in 13", d)                  # the full statement is evidence only

    def test_4864_cycle_follows_saturation(self):
        from tests import site_4864 as s
        ctx = subsystems.context("4864", lambda no: None)
        ctx["status"] = status_of("4864")
        ev = d001.evidence(s.SITE, {"local": "p"}, s.DETAIL, None, ctx)
        demand = next(r for r in ev["readings"] if r["key"] == "demand")
        self.assertIn("the active cycle followed the required cycle, which SCATS sets from saturation, between 70 and 90 s",
                      " ".join(demand["for"]))
        w = d001.written(ev)
        self.assertIn("(critical site 4864)", w["diagnosis"])
        self.assertIn("active cycle 70-90 s, following the required cycle", w["diagnosis"])
        self.assertEqual(d001.kept_points(w, ev), [])


class CountsAgainstSaturationTests(unittest.TestCase):
    def test_volume_doubling_with_usual_saturation_is_flagged(self):
        """Volume +95-98% (SCATS 4864, 10 Nov 08:00) with a subsystem saturation mean and median near usual."""
        from tests import site_4864 as s
        ctx = subsystems.context("4864", lambda no: None)
        ctx["status"] = {**status_of("4864"), "usual": {"ds_median": 97.0, "ds_mean": 92.0, "cl_mean": 74.9,
                                                        "cl_sd": 4.8, "ds_at_least_100_share": 0.4}}
        ev = d001.evidence(s.SITE, {"local": "p"}, s.DETAIL, None, ctx)
        table = {r["key"]: r for r in ev["readings"]}
        self.assertIn("the counts and the strategic measurements disagree", " ".join(table["data"]["for"]))
        self.assertTrue(any("stayed at its usual level" in c for c in table["demand"]["against"]))

    def test_higher_saturation_is_not_read_as_usual(self):
        """The real 4864 case: within the period the saturation median was 99 against a usual 84. A median of 83
        (with two records outside the period) had read as "usual" and made a data issue the leading reading."""
        from tests import site_4864 as s
        ctx = subsystems.context("4864", lambda no: None)
        ctx["status"] = {**status_of("4864"), "usual": {"ds_median": 84.0, "ds_mean": 82.0, "cl_mean": 74.9,
                                                        "cl_sd": 4.8, "ds_at_least_100_share": 0.4}}
        ev = d001.evidence(s.SITE, {"local": "p"}, s.DETAIL, None, ctx)
        table = {r["key"]: r for r in ev["readings"]}
        self.assertNotIn("data", table)
        self.assertIn("the subsystem degree of saturation was higher than usual (mean 94 against 82)",
                      " ".join(table["demand"]["for"]))


class LabelNormalisationTests(unittest.TestCase):
    """SCATS 4864, 17 Nov 2026: an LLM answer was rejected only because its labels were spelled differently."""

    def test_spelling_variants_are_normalised(self):
        from diagnostics.layout import d001_labels
        labels = d001_labels("Moderate")
        fixed = d001.normalise_labels({"diagnosis": "what the data show: x\nMost likely reading (Moderate evidence): y\n"
                                                    "Other Readings - z"}, labels)["diagnosis"]
        self.assertEqual(fixed, "What the data show: x\nMost likely reading (evidence: Moderate): y\nOther readings: z")

    def test_a_different_strength_is_not_rewritten(self):
        from diagnostics.layout import d001_labels
        text = "What the data show: x\nMost likely reading (evidence: Strong): y\nOther readings: z"
        self.assertEqual(d001.normalise_labels({"diagnosis": text}, d001_labels("Moderate"))["diagnosis"], text)

    def test_llm_answer_in_parts_is_accepted(self):
        import json as _json
        from diagnostics.templates.d001 import run

        class LLM:
            model = "stub"

            def complete(self, system, user):
                draft = _json.loads(user)["draft_answer"]
                # parts returned, one with a label written anyway: the code's labels are used
                return _json.dumps({**draft, "most_likely_reading": "Most likely reading (Moderate): "
                                                                    + draft["most_likely_reading"]})
        r = run(SITE, {"local": "p"}, LLM(), detail(), None, subsystems.context("3055", lambda no: None))
        self.assertEqual((r["generated_by"], r["rejected"]), ("llm:stub", None))
        self.assertIn("\nMost likely reading (evidence: Moderate): A local controller response", r["answer"]["diagnosis"])
        self.assertEqual(r["answer"]["diagnosis"].count("Most likely reading"), 1)

    def test_legacy_single_diagnosis_with_variant_labels_is_accepted(self):
        import json as _json
        from diagnostics.templates.d001 import run

        class LLM:
            model = "stub"

            def complete(self, system, user):
                d = _json.loads(user)["draft_answer"]
                text = (f"What the data show: {d['what_the_data_show']}\nmost likely reading (Moderate): "
                        f"{d['most_likely_reading']}\nOther readings - {d['other_readings']}")
                return _json.dumps({"diagnosis": text, "supporting_evidence": d["supporting_evidence"],
                                    "suggested_checks": d["suggested_checks"]})
        r = run(SITE, {"local": "p"}, LLM(), detail(), None, subsystems.context("3055", lambda no: None))
        self.assertEqual((r["generated_by"], r["rejected"]), ("llm:stub", None))

    def test_a_rejected_answer_is_kept_for_review(self):
        from diagnostics.templates.d001 import run

        class LLM:
            model = "stub"

            def complete(self, system, user):
                return '{"diagnosis": "nothing useful"}'
        r = run(SITE, {"local": "p"}, LLM(), detail(), None, None)
        self.assertEqual(r["generated_by"], "code")
        self.assertEqual(r["llm_raw"], '{"diagnosis": "nothing useful"}')


class CloseEvidenceTests(unittest.TestCase):
    def test_close_readings_are_said_to_be_close(self):
        from tests import site_4864 as s
        ctx = subsystems.context("4864", lambda no: None)
        ctx["status"] = {**status_of("4864"), "usual": {"ds_median": 84.0, "cl_mean": 74.9, "cl_sd": 4.8,
                                                        "ds_at_least_100_share": 0.4}}
        ev = d001.evidence(s.SITE, {"local": "p"}, s.DETAIL, None, ctx)
        main = d001.written(ev)["diagnosis"].split("\n")[1]
        self.assertIn(f"The evidence is close: {ev['readings'][1]['name']} is about as well supported", main)
        first = d001.written(ev)["diagnosis"].split("\n")[0]
        self.assertLess(len(first), 1300)


class WeightTests(unittest.TestCase):
    """Calibration on the AM peak of 10 Nov 2026: discriminating points weigh 2, restated findings 1."""

    def test_weights(self):
        self.assertEqual(readings.weight("phases B and D gained 13.8 percentage points and serve none of the assessed"), 2)
        self.assertEqual(readings.weight("volume is higher on 3 approaches"), 1)
        self.assertEqual(readings.weight("the volume change on X has no phase-service finding"), 1)

    def test_3055_with_subsystem_is_strong_and_4864_is_close(self):
        from tests import site_4864 as s
        ctx = subsystems.context("3055", lambda no: None)
        ctx["status"] = status_of("3055")
        top = d001.evidence(SITE, {"local": "p"}, detail(), None, ctx)["readings"][0]
        self.assertEqual((top["key"], top["strength"], top["score"]), ("other_phases", "Strong", 6))
        ctx = subsystems.context("4864", lambda no: None)
        ctx["status"] = {**status_of("4864"), "usual": {"ds_median": 97.0, "ds_mean": 92.0, "cl_mean": 74.9,
                                                        "cl_sd": 4.8, "ds_at_least_100_share": 0.4}}
        table = d001.evidence(s.SITE, {"local": "p"}, s.DETAIL, None, ctx)["readings"]
        self.assertEqual([(r["key"], r["strength"]) for r in table[:2]], [("data", "Moderate"), ("other_phases", "Moderate")])
        self.assertEqual(next(r for r in table if r["key"] == "event")["strength"], "Weak")

    def test_negated_cause_and_undercount_spelling_are_accepted(self):
        self.assertEqual(d001.causal({"diagnosis": "This is an association and does not prove that one caused the other."}), [])
        self.assertEqual(d001.causal({"diagnosis": "The longer cycle caused the queue."}), ['states a cause ("caused")'])


class PersistenceTests(unittest.TestCase):
    """Recurrence at the same weekday and time, and earlier the same day, from archived screening logs."""

    def setUp(self):
        import tempfile
        from diagnostics.archive import open_archive
        from diagnostics.settings import load_rules
        from diagnostics.timewin import period_ending
        self.archive = open_archive(tempfile.mkdtemp())
        self.period = period_ending("2026-11-10T08:30", load_rules())

    def log(self, end_local, categories):
        from diagnostics.settings import load_rules
        from diagnostics.timewin import period_ending
        p = period_ending(end_local, load_rules())
        key = f"screening-logs/AU-VIC-Melbourne/{p.day:%Y/%m/%d}/{p.slot.replace(':', '')}_r.json"
        self.archive.put_new(key, json.dumps({"metadata": {"period": {"end_local": end_local}},
                                              "intersections": [{"site": k, "category": v}
                                                                for k, v in categories.items()]}).encode())

    def test_recurring_red_counts_against_a_one_off_event(self):
        from diagnostics import persistence
        for day, cat in (("2026-11-03", "red"), ("2026-10-27", "amber_traffic"), ("2026-10-20", "normal")):
            self.log(f"{day}T08:30", {"3055": cat})
        self.log("2026-11-10T08:00", {"3055": "amber_signal"})
        h = persistence.site_persistence(self.archive, "AU-VIC-Melbourne", "3055", self.period)
        self.assertEqual((h["weeks_screened"], h["weeks_flagged"], h["weeks_red"]), (3, 2, 1))
        self.assertEqual(persistence.sentence(h), "History: Red or Amber at this time in 2 of the previous 3 screened "
                         "weeks (Red in 1); earlier today: 07:30-08:00 Amber - signal, 07:00-07:30 not screened.")
        ev = d001.evidence(SITE, {"local": "p"}, detail(), None, None, h)
        event = next(r for r in ev["readings"] if r["key"] == "event")
        self.assertIn("so the condition recurs", " ".join(event["against"]))
        self.assertIn("History: Red or Amber at this time in 2 of the previous 3", d001.written(ev)["diagnosis"])

    def test_without_archive_nothing_changes(self):
        from diagnostics import persistence
        self.assertIsNone(persistence.site_persistence(None, "AU-VIC-Melbourne", "3055", self.period))


class SwitchOverrideTests(unittest.TestCase):
    def test_switches(self):
        from diagnostics.settings import switch_overrides
        self.assertEqual(switch_overrides("none"), {})
        self.assertEqual(switch_overrides("all"), {"history": {"extend_beyond_weeks": True, "school_holidays": "match"},
                                                   "q1": {"min_count_noise_sd": 2}})
        with self.assertRaises(ValueError):
            switch_overrides("nope")

    def test_lookback_is_12_weeks_and_version_unchanged(self):
        from diagnostics.settings import Settings, load_rules
        self.assertEqual(load_rules()["history"]["max_lookback_weeks"], 12)
        self.assertEqual(Settings().baseline_version, "v1.1-f6389e86dc")


class PhaseListTests(unittest.TestCase):
    """Rank run of 10 Nov 2026 08:00-08:30 (switches on)."""

    @staticmethod
    def _3426():
        """SCATS 3426: every approach lost 8-9.5 pp of green; Barkly [N] (phase C) and Carlisle [W] (every other listed
        phase) share no phase, yet their green shares add up to 76.9%, so unlisted phases took about 23%."""
        phases = {"N": "C", "S": "C,D1,E1", "W": "A,B,D1,D2,D3,E1,E2", "E": "A,B,D2,D3,E2"}
        cur = {"N": 37.592, "S": 37.592, "W": 39.303, "E": 39.303}
        usual = {"N": 45.599, "S": 47.068, "W": 48.329, "E": 48.329}
        view = {"phases": phases, "quarters": ["08:00-08:15", "08:15-08:30"],
                "green_share": {"N": [41.9, 33.2], "S": [41.9, 33.2], "W": [42.8, 35.8], "E": [42.8, 35.8]}}
        ev = {"phase_service_all": [{"approach": k, "current": cur[k], "usual": usual[k], "normal_range": [38.0, 49.0]}
                                    for k in phases],
              "signal": {"phase_service": {"abnormal_approaches": [
                  {"approach": k, "direction": "LOW", "current_green_share_pct": cur[k],
                   "usual_green_share_pct": usual[k], "normal_range": [38.0, 49.0]} for k in phases]}}}
        return ev, view

    def test_unlisted_phases_are_solved_and_shifts_dropped(self):
        ev, view = self._3426()
        self.assertFalse(readings.phases_cover_cycle(ev, view))
        self.assertEqual(readings.phase_shifts(ev, view), [])        # "100 minus the share" would be wrong here
        shares = {x["phases"]: x for x in readings.phase_shares(ev, view)}
        self.assertEqual(shares["unlisted"]["current"], 23.1)
        self.assertGreaterEqual(shares["unlisted"]["change"], 15)
        text = " ".join(readings.phase_share_sentences(list(shares.values()), view["quarters"]))
        self.assertIn("the phases not listed for any assessed approach 23.1%", text)

    def test_wide_reference_gives_no_usual_share(self):
        """SCATS 3182: Reserve Street [NW] green share usual 91.6% within a 18.6-92.4% range; the solve gave phases
        A, B and D a usual 8.4% on the main road. A range this wide is not one operation: no usual by phase."""
        view = {"phases": {"R": "C", "N": "A,B,D"}, "quarters": ["q1", "q2"], "green_share": {}}
        ev = {"phase_service_all": [{"approach": "R", "current": 14.6, "usual": 91.6, "normal_range": [18.6, 92.4]}],
              "signal": {"phase_service": {"abnormal_approaches": [
                  {"approach": "R", "direction": "LOW", "current_green_share_pct": 14.6, "usual_green_share_pct": 91.6,
                   "normal_range": [18.6, 92.4]}]}}}
        shares = readings.phase_shares(ev, view)
        self.assertTrue(shares and all(x["usual"] is None for x in shares))
        self.assertIn("varies widely", readings.phase_share_sentences(shares)[0])
        self.assertEqual(readings.phase_shifts(ev, view), [])

    def test_an_approach_that_lost_green_did_not_gain_it(self):
        ev, view = self._3426()
        view = {**view, "phases": {"N": "C", "S": "C,D1,E1", "W": "A,B,D1,D2,D3,E1,E2"}}
        ev["phase_service_all"] = [x for x in ev["phase_service_all"] if x["approach"] != "E"]
        ev["phase_service_all"][2]["current"] = 62.4                 # now the lists fill the cycle
        sh = readings.phase_shifts(ev, view)
        n = next(x for x in sh if x["approaches"] == ["N"])
        self.assertIn("S", n["other_approaches"])
