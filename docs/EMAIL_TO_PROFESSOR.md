**Subject:** Intersections Diagnostics V1 – response to your review of run eebc0b2964f4 (Fri 30 Oct 15:00–15:30)

Dear Prof. Sarvi,

Thank you for the detailed review. I have worked through every point; the attached note (`REVIEW_RESPONSE.md`) answers each one with the supporting figures. The final run of the same period, **5065b14ac8a7**, also includes your decision to tolerate one failing detector. It gives **Red 76, Amber 617 (556 traffic, 61 signal), Normal 515, Grey 950 and Detector Health 343**. In brief:

**Priority 1 – Screening accuracy**

1. **SCATS 976** – fixed. A code error checked "insufficient data" before "abnormal" in Q3C (and Q1). Any abnormal approach now makes the component abnormal, as in the methodology, and 976 is Red.
2. **Grey (790 in the reviewed period)** – 230 could not pass Q2, 390 had no current IntersectionPerfKpi value, 159 were Grey only because an approach had no green, and 11 were Grey because of Q1 or a combination. The no-green approaches are **recorded zeros** (HasGreen = 0, GreenShare 0), not missing data, and Q3A and Q3B remain valid in all those sites (see decision A).
3. **Detector Health (692 in the reviewed period)** – 349 sites failed on a single detector (200 at 5–9 vehicles, 77 at 1–4, 72 at 0) and 343 on several detectors. As agreed, one failing detector is now tolerated and shown as a note. The 349 sites are screened (11 Red, 98 Amber, 80 Normal, 160 Grey), and the 343 remaining Detector Health sites all have two or more failing detectors.
4. **Q3C** – 100 % is a valid value. GreenShare is the share of the cycle in which the approach has green, not a split between approaches (976: phases A and B made the whole cycle).
   - 221 approaches are at 100 %, and 379 changed by 30 percentage points or more.
   - The main limitation is history: before about 20 Oct the records hold HasGreen = 0 on every approach, so 1,234 of 1,876 screened sites cannot assess Q3C yet.
   - 707's phase-to-approach mapping looks wrong and has been raised with the data owner. A comparison with raw `site_phase` timing has not been done.
5. **Cycle Stability** – the stored values match the KPI definition, Score = (1 − CV/0.20) × 100 floored at 0.
   - 707's zero is a genuine measurement: its cycle varied by about 40 %, and every CV of 20 % or more reads 0.
   - Q3B has no minimum-difference condition, so 61 of the 284 stability abnormals lie within 2 % of the threshold.

**Priority 2 – Diagnostic reporting** (example reports for SCATS 4566, 4564 and 774 attached)

- The diagnosis separates "What the data show" from "Possible explanations (not demonstrated by these data)", recognises SCATS adaptive operation, and lists the checks in order of priority.
- Q5 gives agreement / partial agreement / disagreement / insufficient coverage, names the matching and differing approaches, and states the 30-minute coverage.
- Junction Analytics and the supplementary link speed are kept apart (774 shows its link speed). The link speed now includes a reference speed: the median of the same 30 minutes in the reference weeks, from the same feed. Please tell me if you would rather keep it unavailable.
- Names come from the validated road-link mappings, the rows outside their range are in bold in the tables, and the repetition has been removed. No number or link ID can be invented: an LLM answer that adds one is rejected, and the code wording is used instead.

**Log and snapshot.** The complete JSON screening log and the baseline snapshot are attached, for the run you reviewed and for the final run. I recomputed every result from the log and found no differences; all 14,044 baseline values quoted in the log match the snapshot.

**Independent statistics.** The attached stats files count every check for all 2,501 intersections, without the screening's gates (definitions in `STATS_DEFINITIONS.md`). For example, 596 intersections network-wide have no Signal Performance KPI at all.

**Decisions I would ask you to make**

- **(A) No-green approach:** keep "site Grey", treat the approach as not assessable, or treat a recorded HasGreen = 0 as 0 % green. I suggest the last, as it follows the Q2 rule that a recorded zero is a measurement. About 14 sites would become Red.
- **(C) Q3B:** keep the stored CycleStability as now, or change the method (use CycleCvPct, or add a minimum difference as in Q3A).
- **(D) Log sections:** should the traffic and signal abnormality sections list only Amber and Red sites, or also Grey sites with an abnormal finding (as now)?

One further point: the baseline is at its minimum. No value has more than 6 of the 7 reference weeks, and about half have exactly 5, because of gaps in the Friday afternoon data. One more gap would turn many sites Grey.

Attachments:

- `REVIEW_RESPONSE.md`
- `STATS_DEFINITIONS.md`
- `export_eebc0b2964f4/` and `export_5065b14ac8a7/` (each with `screening_log.json` and `baseline_snapshot.json`)
- `summary_5065b14ac8a7.json`
- `stats_2026-10-30T043000Z.json` and `.csv`
- `kpi_check_707.json` and `kpi_check_976.json`
- `examples_5065b14ac8a7.html`

Kind regards,
Hailey
