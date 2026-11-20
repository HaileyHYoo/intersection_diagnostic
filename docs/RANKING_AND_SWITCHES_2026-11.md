# Ranking, baseline switches, persistence and insights – direction (13 Nov 2026)

Follows the four-period review (`REPORT_DIAGNOSTICS_REVIEW_2026-11.md`). Section 1 is implemented; sections 2–3 are
implemented as switches that are off by default; sections 4–6 are proposals.

## 1. Report wording fixes (implemented, no methodology change)

| Change | Where | Effect on the 369 Red reports of the review |
|---|---|---|
| "the opposite of a demand response" must be kept by the LLM, or its answer is replaced by the code's | `d001.kept_points` | 81 reports with an opposite-direction finding |
| Approaches with identical green share are reported as one phase | `d001.phase_groups` | 51 reports |
| A usual green share of 100 % or a usual volume of 0 gives a mapping caveat and a first check | `d001.mapping_checks` | 35 reports |
| A tolerated detector gives an under-count caveat and a detector check | `d001.evidence` | 69 reports |
| One incident check for all approaches with a traffic finding only | `d001.written` | – |

## 2. Baseline switches (implemented, off by default)

| Switch | Off (methodology as written) | On |
|---|---|---|
| `history.school_holidays` | `"include"` | `"match"`: term weekdays against term days, school-holiday weekdays against school-holiday days |
| `history.extend_beyond_weeks` | `false`: a left-out or missing week is not replaced | `true`: replaced by an earlier week, up to `max_lookback_weeks` (12) |
| `q1.min_count_noise_sd` | `0` | `2`: the difference must also be at least 2√usual vehicles |

The baseline version is unchanged while the switches are off (`v1.1-f6389e86dc`). "match" for a school-holiday day
needs `extend_beyond_weeks`, as the eight weeks before it hold only one or two holiday days.

## 3. Small approaches: why 2√usual

Volume counts behave approximately as Poisson counts, whose standard deviation is √usual. A fixed 10 % difference is
about 0.5 standard deviation at 20 veh/30 min but 3 at 900 veh/30 min, so small approaches are flagged far more often.
Requiring the difference to be at least 2√usual (about 2 standard deviations) removes that dependence on size without
an arbitrary minimum volume. Applied to all assessed approaches of the four periods:

| Usual volume (veh/30 min) | Approaches | Flagged now | With 2√usual | With 3√usual |
|---|---|---|---|---|
| 0–20 | 329 | 35 % | 11 % | 4 % |
| 20–50 | 877 | 35 % | 12 % | 3 % |
| 50–100 | 1,612 | 34 % | 15 % | 6 % |
| 100–200 | 2,966 | 31 % | 17 % | 8 % |
| 200–400 | 4,739 | 25 % | 20 % | 10 % |
| 400–800 | 4,280 | 18 % | 18 % | 12 % |
| 800+ | 1,080 | 11 % | 11 % | 11 % |

With 2√usual the flag rate is 11–20 % at every size and large approaches are unchanged. 3√usual makes small
approaches rarer than large ones (over-correction). A fixed minimum (e.g. 50 veh/30 min) would hide every change on
small approaches. Cost of 2√usual: the Q1 finding disappears at 76 Red and 606 Amber – traffic site-periods.
**Recommendation:** propose 2 to the methodology owner, after a sensitivity run.

## 4. Ranking within Red and within Amber (implemented for local review, 16 Nov 2026)

`diagnostics/rank.py`, parameters in `rules.json` `rank`. Sites are ordered within Red, Amber – traffic and Amber –
signal; a rank never moves a site between categories. Not called by production yet.

**score = severity × impact × type × confidence × persistence**

| Component | Definition | Why |
|---|---|---|
| Severity | Per abnormal finding a robust z-score, abs(current − usual) / spread; spread = (90th − 10th percentile) / c(n), where c(n) is the expected 10th–90th percentile width of n normal values and n the number of reference weeks (1.79 for 5 weeks, 1.91 for 6, 1.99 for 7, 2.05 for 8; 2.563 for a large sample), never below a floor (volume √usual veh, cycle length 2 s, Cycle Stability 1 point, green share 1 pp); each z capped at 5; the three largest combined as √(Σz²) | Puts the four measures on one scale (how unusual against the site's own history); the Poisson floor stops small counts and very narrow ranges from producing huge z; the cap and the top 3 stop one extreme value or many small findings from dominating |
| Impact | log10(1 + site veh/h) / log10(1 001): 1.0 at 1,000 veh/h, 0.67 at 100 veh/h | Busier intersections first, without volume deciding alone |
| Type | × 1.25 when phase service moves opposite to the volume on the same approach | The most actionable diagnosis type |
| Confidence | × 0.8 when a finding rests on the 5-week minimum; × 0.8 with a tolerated detector | Less certain usual values or counts |
| Persistence | × (1 + 0.25 k), k = previous 4 same-weekday, same-slot periods with the same category (Red; Red or Amber for Amber) | Counters regression to the mean |

Approaches with identical green-share values are one phase and count once. Sites with a usual green share of 100 % or
a usual volume of 0 behind a finding are listed apart (mapping-suspect), unranked.

Basis: network screening in the Highway Safety Manual (AASHTO 2010, part B, ch. 4) ranks sites by a performance
measure corrected for regression to the mean (Empirical Bayes; Hauer 1997). Here the robust z-score is the excess over
the site's own expected range, the Poisson floor accounts for random variation of counts, and persistence counters
regression to the mean.

Check on the four review periods (from the audit data):
- z reaches the cap for 3–5 % of the findings (cycle length 11–22 %).
- Red severity has a 10th–90th percentile of about 3.3–7.0, so the order is not set by volume alone.
- The top of the list is led by sites with large changes on busy approaches, often with an opposite-direction finding.

Local review (screening only, no LLM):

```bash
python main.py rank --end "AM peak=2026-11-10T08:30" "Midday=2026-11-10T12:30" "PM peak=2026-11-10T17:30" "Weekend midday=2026-11-08T12:30"
```

This writes `out/rank/<time>/summary.md|html`, with the categories, the rule and checks of the ranking:
- component correlations;
- the make-up of the top 20;
- the overlap with a naive order.

Per period it also writes `ranked.csv` (every site) and `ranked.md|html` (the top 20 per category and the
mapping-suspect list). The previous 4 weeks are screened for persistence; `--no-persistence` skips them.

## 5. Persistence (proposal)

From the archived screening logs (`screening-logs/…`): for the same weekday and slot in the previous 4 weeks, and for
the same day's previous runs, count the runs in which the site was Red or Amber and which finding repeated. Display:
"Red in 3 of the last 4 Tuesdays at 08:00; repeated finding: less green to X [N]". Needs no new data, only reading the
logs that are already written; the first weeks show "history building".

## 6. Insights (V2 pilot, proposal)

The code computes further signals – persistence, the same finding at neighbouring sites of the subsystem, detector and
mapping flags, calendar context – and the LLM writes an "Additional considerations (not verified)" section from them,
each point citing its signal, under the same checks as now (numbers from the evidence only, no causes stated as facts).
Run offline on archived Red sites and reviewed before any production use.

## 7. Suggested order

1. Now: section 1 (done); review the ranking with `python main.py rank` (section 4).
2. Sensitivity runs of the three switches on the four review periods; results to the methodology owner for decisions.
3. Persistence once four weeks of screening logs exist; then the insights pilot.
