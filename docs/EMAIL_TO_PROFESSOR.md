**Subject:** Intersections Diagnostics V1 – response to your review of run eebc0b2964f4 (Fri 30 Oct 15:00–15:30)

Dear Professor,

Thank you for the detailed review. I have worked through every point, and the attached note (`REVIEW_RESPONSE.md`) gives the answer to each one with the supporting figures. In brief:

**Screening accuracy**

1. **SCATS 976** – you were right. A code error checked "insufficient data" before "abnormal" in Q3C (and Q1). It now follows the methodology: any abnormal approach makes the component abnormal. 976 is Red. The period re-run as **b77b122afab4** gives Red 65, Amber 519, Normal 435, Grey 790 and Detector Health 692.
2. **Grey (790)** – 230 cannot pass Q2 (detector records missing), 390 have no current IntersectionPerfKpi value, 159 are Grey only because an approach has no green, and 11 for Q1 or a combination. The no-green approaches are **recorded zeros** (HasGreen = 0, GreenShare 0), not missing data. In all 159 of those sites Q3A and Q3B can be assessed.
3. **Detector Health (692)** – 349 sites fail on a single detector, 200 of them at 5–9 vehicles. Had the gate passed, 34 would be Red and 248 Amber. So the gate does exclude otherwise assessable intersections. The note gives the effect of thresholds 5 and 1.
4. **Q3C** – GreenShare is the share of the cycle in which the approach has green, not a split between approaches, so 100 % is valid (976: phases A and B were the whole cycle). The main limitation is history: before about 20 Oct the records hold HasGreen = 0 on every approach, so most sites cannot assess Q3C yet. 707's phase-to-approach mapping also looks wrong and has been raised with the data owner. I have not yet compared Q3C with the raw `site_phase` timing.
5. **Cycle Stability** – the stored value is max(0, 100 − 5 × CycleCvPct). 707's 0 is genuine (CV around 40 %), but every CV above 20 % reads 0. Q3B also has no minimum difference: 38 of the 236 abnormals are less than 5 % below usual.

**Reporting**

- The diagnosis now separates "What the data show" from "Possible explanations (not demonstrated by these data)". It states that SCATS adapts cycle length and phase service to demand and coordination, and orders the checks by priority.
- Q5 gives agreement / partial agreement / disagreement / insufficient coverage. It names the matching and differing approaches and states the 30-minute coverage. Junction Analytics and the supplementary link speed are kept apart (see 774).
- Names come from the validated road-link mappings. The rows outside their range are in bold in the tables, so the text no longer repeats them. No number or link ID can be invented: an LLM answer that adds one is rejected, and the code wording is used instead.

**Log and snapshot.** As requested, the complete JSON screening log and the baseline snapshot are attached, for the run you reviewed and for the re-run. I recomputed every result from the log and found no differences. All 11,759 baseline values quoted in the log match the snapshot.

**Decisions I would ask you to make**

- **(A) No-green approach:** keep "site Grey", treat the approach as not assessable, or treat a recorded HasGreen = 0 as 0 % green. I suggest the last, as it follows the Q2 rule that a recorded zero is a measurement. About 12 sites would become Red.
- **(B) Detector gate:** keep 10 vehicles per detector, lower it, or judge each detector against its own history.
- **(C) Q3B:** keep CycleStability, or use CycleCvPct (not clamped), possibly with a minimum difference as in Q3A.
- **(D) Log sections:** should the traffic and signal abnormality sections list only Amber and Red sites, or also Grey sites with an abnormal finding (as now)?

One further point: the baseline is at its minimum. No value has more than 6 of the 7 reference weeks, and about half have exactly 5, because of gaps in the Friday afternoon data. One more gap would turn many sites Grey.

Attachments:

- `REVIEW_RESPONSE.md`
- `export_eebc0b2964f4/` and `export_b77b122afab4/` (each with `screening_log.json` and `baseline_snapshot.json`)
- `summary_b77b122afab4.json`
- `kpi_check_707.json` and `kpi_check_976.json`
- `examples_b77b122afab4.html`

Once you have decided (A)–(D), I will apply them and re-run the period.

Kind regards,
Hailey
