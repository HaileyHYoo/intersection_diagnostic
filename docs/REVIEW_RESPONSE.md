# Response to the methodology review of run eebc0b2964f4 (Fri 30 Oct 2026 15:00–15:30)

Re-run after the changes: **b77b122afab4** (same period, same data). Counts: Red 65, Amber traffic 467, Amber signal 52,
Normal 435, Grey 790, Detector Health 692 (2,501 sites). Run 651303f563f6 gave identical counts; the run is reproducible.

Attached: the screening log and baseline snapshot of both runs (`export_eebc0b2964f4/`, `export_b77b122afab4/`,
uncompressed JSON), `summary_b77b122afab4.json` (section `review`), `kpi_check_707.json`, `kpi_check_976.json`, and the
example reports for SCATS 4566, 4564 and 774.

## Priority 1 – Screening accuracy

| # | Question | Finding | Status |
|---|---|---|---|
| 1 | SCATS 976 Amber, should be Red | Code error: an approach without enough history made Q3C (and Q1) INSUFFICIENT before an abnormal approach was considered. Now, as in the methodology (§4, §8), any abnormal approach makes the component ABNORMAL; a missing one only withholds NORMAL. **976 is Red.** | Fixed |
| 2 | 790 Grey sites | Q2 not assessable: 230 (200 a detector missing records, mostly 1 of N; 20 no records; 10 no active detector). No current IntersectionPerfKpi value, so all three Q3 measures fail: 390 (KPI feed coverage). Only an approach without green: 159, all with Q3A and Q3B assessable. Q1: 10. **No-green is not missing data**: all 210 such approaches have HasGreen = 0 recorded in both quarter-hours, 204 with GreenShare 0 (6 have GreenShare > 0, inconsistent records). | Analysed – decision needed (A) |
| 3 | 692 Detector Health | 349 sites fail on one detector (200 at 5–9 vehicles, 77 at 1–4, 72 at 0). Had the gate passed: Red 34, Amber 248, Normal 169, Grey 241. A threshold of 5 would pass 365 sites (22 Red); a threshold of 1 (only zero counts fail) 516 (29 Red). | Analysed – decision needed (B) |
| 4 | Q3C green share | GreenShare is the share of the cycle in which the approach has green, not a split between approaches; approaches served in several phases overlap (sum per site 200 % at 976). 100 % is valid: 976 Heatherton Road [E] runs in phases A and B, which together made the whole cycle (usual 82 %: another phase usually took ~18 %). 185 approaches at 100 %, 318 with a change ≥ 30 pp, no zero-width range. **Q3C history is short**: before ~20 Oct the records have HasGreen = 0 on every approach, so 1,045 of 1,579 sites cannot yet assess Q3C. 707's mapping looks wrong (Kendall Road [W] 70–75 % green with zero volume; Ringwood–Warrandyte Road [S] never green). | Checked internally; raw phase-timing (site_phase) comparison not done |
| 5 | Cycle Stability | CycleStability = max(0, 100 − 5 × CycleCvPct) (matches 976 to 3 decimals). 707's 0 is a real measurement (CV 39–44 %), but every CV ≥ 20 % reads 0. Four sites at 0. 54 of 236 stability abnormals lie within 2 % of the 10th percentile; 15 cycle-length abnormals differ by only 10–12 %. | Analysed – decision needed (C) |

## Priority 2 – Diagnostic reporting

| # | Request | Change |
|---|---|---|
| 6 | Q4 wording | Diagnosis = what the data show (approaches and direction, no figures), then possible explanations labelled "not demonstrated by these data", with the statement that SCATS adapts cycle length and phase service to demand and coordination. Explanations come only from combinations of Q1/Q3 findings (e.g. longer cycle with higher volume may be adaptive; less green to a busier approach is the opposite of a demand response; same-direction green and volume: SCATS following demand, or volume following the green given). Supporting Evidence = measurements; Checks = numbered by priority (phase service vs demand, adaptive vs plan/coordination, stability, external causes). |
| 7 | Q5 verdict and coverage | Site verdict: agreement / partial agreement / disagreement / insufficient coverage, naming matching and differing approaches. Coverage stated explicitly (full 30 minutes, or 15-min periods and queue minutes per approach). Section 3: Junction Analytics first (fixed "unavailable" message kept, e.g. 774), supplementary link speed under its own heading. TomTom is never stated as cause. |
| 8 | Readability | Names from Neo4j roads, then the validated TomTom road-link mapping; link ID kept only where no reliable name exists or two links share a name (4566 William Street [N]). Repeated bullets removed. |

## Decisions needed

- **(A) Approach without green.** Current rule: the site is Grey. Alternatives, for the 159 sites affected:
  (a) the approach is "not assessable", the site is not Grey → Normal 83, Amber 64, Red 12, Grey 1;
  (b) a recorded HasGreen = 0 is a measured 0 % green share → Normal 82, Amber 65, Red 12, Grey 1.
  Recommendation: (b), consistent with the rule already used in Q2 (a missing record is not a zero; a recorded zero is a measurement).
- **(B) Detector gate threshold** (now 10 vehicles in 60 minutes per detector): keep, lower to 5, or judge each detector against its own history.
- **(C) Q3B measure:** keep CycleStability (clamped at 0) or use CycleCvPct (higher = poorer, not clamped).

## Data issues to raise

- IntersectionPerfKpi has no current value at ~391 Q2-passing sites (coverage).
- IntersectionPerfApproach before ~20 Oct: HasGreen = 0 and GreenShare 0 on every approach; 6 records with HasGreen = 0 but GreenShare > 0.
- SCATS 707 link-to-approach mapping; unnamed `STNA…` links in Neo4j (707, 983).
- TomTom mapping file at SCATS 4566: two TomTom approaches mapped to one link (WILLH6X4J54X); the other William Street [N] link has none.
