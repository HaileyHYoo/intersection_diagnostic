# Intersections Diagnostics V1 – response to the review of run eebc0b2964f4

Period reviewed: **Fri 30 Oct 2026 15:00–15:30 (Melbourne)**, region AU-VIC-Melbourne, 2,501 signalised sites.
Re-run after the changes: **b77b122afab4** (same period, same data, same baseline).

| | Red | Amber traffic | Amber signal | Normal | Grey | Detector Health |
|---|---|---|---|---|---|---|
| b77b122afab4 (after the changes) | 65 | 467 | 52 | 435 | 790 | 692 |

Two re-runs (651303f563f6, b77b122afab4) gave identical counts; the screening is reproducible.

## 1. Attachments

| File | What it is | Notes |
|---|---|---|
| `export_eebc0b2964f4/screening_log.json` | The complete JSON screening log of the run you reviewed (methodology §18.3) | As originally produced, before the changes below |
| `export_eebc0b2964f4/baseline_snapshot.json` | The historical baseline used by that run (§18.4): reference value, 10th/90th percentiles and number of observations per site, approach and measure | Friday 15:00 slot, weeks 2026-W44; identical file for both runs |
| `export_b77b122afab4/screening_log.json`, `baseline_snapshot.json` | The same after the changes | Use this one for the figures in this note |
| `summary_b77b122afab4.json` | Breakdown of every category; section `review` answers the questions below | |
| `kpi_check_707.json`, `kpi_check_976.json` | Every stored IntersectionPerfKpi / IntersectionPerfApproach field per quarter-hour (976: analysis period; 707: analysis period and three reference weeks) | Raw values behind items 4 and 5 |
| `examples_b77b122afab4.html` (and `.md`) | Example outputs per category; full Red reports for SCATS 4566, 4564 and 774 | Shows the new report layout |

**Independent check of the log and the snapshot.** Every Q2, Q1, Q3A, Q3B, Q3C result, the two-of-three rule and every category were recomputed from the values stored in the log: 0 differences in 2,501 sites. All 11,759 baseline values quoted in the log equal the snapshot (reference, 10th and 90th percentiles, number of observations); none is missing, none is NaN.

## 2. Priority 1 – Screening accuracy

**1. SCATS 976 (Amber, should be Red) – fixed.** A code error: an approach without enough history made Q3C (and, in the same way, Q1) "insufficient data" before an abnormal approach was considered. As written in the methodology (§4 for Q1, §8 for Q3C), any abnormal approach now makes the component abnormal; a missing approach only withholds "normal". 976 is Red. Its Heatherton Road [E] green share of 100 % is a valid value: that approach runs in phases A and B, which together took the whole cycle (usually 82 %: another phase normally takes about 18 %).

**2. Grey (790).**

| Cause | Sites |
|---|---|
| Q2 not assessable: a detector missing records (mostly 1 of N) / no records / no active detector | 200 / 20 / 10 |
| No current IntersectionPerfKpi value, so none of Q3A, Q3B, Q3C can be assessed | 390 |
| Only because an approach has no green | 159 |
| Q1 (an approach without volume history) | 10 |
| Approach without green together with fewer than two Q3 measures | 1 |

*Missing data versus a legitimate zero green.* All 210 approaches without green have HasGreen = 0 **recorded** in both quarter-hours, 204 with GreenShare 0; they are recorded zeros, not missing records. Six have HasGreen = 0 with GreenShare above 0 (inconsistent records). In all 159 "no green only" sites, Q3A and Q3B are assessable. Under the alternatives in decision (A) below, the 160 Grey sites with an approach without green (159 for that reason alone, one also lacking Q3 measures) would become: (a) Normal 83, Amber 64, Red 12, Grey 1; (b) Normal 82, Amber 65, Red 12, Grey 1.

**3. Detector Health (692).** 349 sites fail on a single detector (200 at 5–9 vehicles in 60 minutes, 77 at 1–4, 72 at 0); 304 on several detectors with some counts above 0; 39 on several detectors all at 0. Had the gate passed: Red 34, Amber 248, Normal 169, Grey 241. Of the 239 sites failing only on one detector with 1–9 vehicles while every other detector passed: Red 10, Amber 83, Normal 65, Grey 81. A threshold of 5 vehicles would let 365 sites through (22 Red); a threshold of 1 (only zero counts fail) 516 (29 Red). The gate does exclude otherwise assessable intersections.

**4. Q3C green share.** GreenShare is the share of the cycle in which the approach has green, not a split of the cycle between approaches: approaches served in several phases overlap, so the sum over a site's approaches is not 100 % (976: 200 %; 707: about 190 %). 185 approaches are at 100 % (60 abnormal, 13 normal, 112 without enough history); 318 changed by 30 percentage points or more, all but three abnormal; no approach has a zero-width range. Two data limitations: (i) before about 20 Oct 2026 the records have HasGreen = 0 and GreenShare 0 on every approach while the cycle runs (707 on 16 Oct; 994), so 4,719 of 7,302 phase-service reference values cannot be formed yet and 1,045 of 1,579 assessed sites cannot assess Q3C; (ii) at 707 the phase-to-approach mapping looks wrong (Kendall Road [W] 70–75 % green with zero volume; Ringwood–Warrandyte Road [S] never green; an unnamed link identical to Ringwood–Warrandyte Road [N]). The comparison with raw SCATS phase timing (`site_phase`) has not been done.

**5. Cycle Stability.** The data show CycleStability = max(0, 100 − 5 × CycleCvPct) (976: CV 4.502 → 77.492, CV 2.800 → 85.998). The 0 at 707 is a genuine measurement (CV 38.9 % and 44.5 %), but every CV of 20 % or more reads 0. Four sites read 0. Of the 236 stability abnormals, 54 are within 2 % of the 10th percentile, 38 are less than 5 % below usual and 25 have a usual value of 100 (Q3B has no minimum-difference condition, unlike Q3A's 10 %). Fifteen cycle-length abnormals differ from usual by only 10–12 %. Of the 65 Red sites, 50 are Red through Cycle Stability and phase service together.

## 3. Priority 2 – Diagnostic reporting

**6. Q4 wording.** The diagnosis now has two labelled lines. "What the data show" names the approaches and the direction of each finding, without figures. "Possible explanations (not demonstrated by these data)" states that SCATS adapts cycle length and phase service to demand and coordination, so an abnormal value does not by itself show a signal problem, and reads only combinations of the Q1/Q3 findings: a longer cycle with higher volume may be adaptive; a cycle change without a matching volume change points to plan or coordination; less green to a busier approach is the opposite of a demand response and the first thing to verify; for green and volume moving together, SCATS may be following demand, or the counted volume may follow the green given. The suggested checks are numbered by priority and verify phase service against demand, adaptive response against plan or coordination, and cycle-by-cycle stability.

**7. Q5.** Site verdict: agreement / partial agreement / disagreement / insufficient coverage, naming the approaches that match and those that differ. Coverage is stated explicitly (delay and queue for the full 30 minutes, or how many 15-minute periods and queue minutes per approach). Section 3 shows the Junction Analytics result first; when it is unavailable the fixed message is kept and the reason given (774: no TomTom approach mapping); the supplementary link speed follows under its own heading and never replaces it. TomTom is described as road-user impact, never as cause.

**Link speed – reference speed.** The supplementary link-speed table now shows a reference speed. For each incoming link it is the median TomTom speed of the same 30 minutes in the screening's reference weeks (same weekday, holidays left out, at least five weeks with samples), read from the same `aimes/speed` feed when the site is selected, with the number of weeks. It fills the contract's `reference_speed_kmh` ("historical average for the same weekday and time of day"). Nothing is stored, no network-wide speed baseline is built, and it never affects any result.

**8. Readability.** Names come from the Neo4j roads, then the validated TomTom road-link mapping; a link ID is kept only where no reliable name exists or two links share a name (4566 William Street [N]). Supporting Evidence is now one line saying what is outside its range, with those rows in bold in the tables (which hold every measurement); the TomTom part is four labelled lines (Largest values, By approach, Overall, Coverage); the movements table is folded. Numbers are never invented: an LLM re-wording is rejected if it contains a number or a link ID not in the evidence, drops an approach, a label or the verdict, or calls a measure "within" its range when it is not (the code wording is then used).

## 4. Decisions requested

- **(A) Approach without green.** Keep "site Grey", or (a) treat the approach as not assessable, or (b) treat a recorded HasGreen = 0 as a measured 0 % green share. We suggest (b): it follows the rule already used in Q2 (a missing record is not a zero; a recorded zero is a measurement).
- **(B) Detector gate.** Keep 10 vehicles in 60 minutes per detector, lower it (5), or judge each detector against its own history.
- **(C) Q3B.** Keep CycleStability (clamped at 0, no minimum difference) or use CycleCvPct (higher = poorer, not clamped), possibly with a minimum difference as in Q3A.
- **(D) Log sections.** `traffic_abnormalities` and `signal_abnormalities` also list Grey sites with an abnormal finding (247 and 16), each marked with its category. Keep, or list Amber and Red only?

## 5. Other observations

- **History is at the minimum.** The baseline uses 7 reference weeks (2026-09-25 excluded as a public holiday), but no value has more than 6 observations: 9,843 of 20,115 values have exactly 5, the minimum, and 4,806 fewer. Gaps in the Friday afternoon records (e.g. 2 and 9 Oct) are not replaced, as agreed, so one more gap would make many sites Grey.
- **Low-volume approaches.** Of 1,058 abnormal approach volumes, 34 have a usual value below 20 vehicles in 30 minutes and 22 differ from usual by fewer than 5 vehicles.
- **Reference speed coverage.** Some links have a current speed but too few reference weeks with speed samples, so their reference is shown as "-" with the number of weeks (e.g. SCATS 4566: no TomTom speed record for any of its links on Fri 23 Oct 15:00–15:30; two links have none in any reference week). This is a gap in the speed feed, not an estimate.
- **Snapshot scope.** The snapshot also holds cycle values for 891 sites with KPI data that are not in the screened network; they are not used.

## 6. Data issues raised with the data owners

- IntersectionPerfKpi has no current value at about 390 sites that passed Q2 (coverage).
- IntersectionPerfApproach before about 20 Oct: HasGreen = 0 and GreenShare 0 on every approach; six records with HasGreen = 0 and GreenShare > 0.
- Link-to-approach mapping at 707; unnamed `STNA…` links in Neo4j (e.g. 707, 983); site 4705 has no name.
- TomTom mapping file at 4566: two TomTom approaches mapped to the same link (WILLH6X4J54X); the other William Street [N] link has none.

## 7. Next steps

Apply decisions (A)–(D); re-run the period and the following weeks; repeat the Q3C checks in late November, when five weeks of valid green-share history exist; compare Q3C with raw `site_phase` timing if required.
