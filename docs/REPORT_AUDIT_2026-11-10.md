# Report audit – Tue 10 Nov and Sun 8 Nov 2026

Full review of every Red report and Amber evidence page produced by `python main.py audit-reports` (batch
`20261110_1532`, LLM wording `gpt-5.6-luna`, code version of 10 Nov 2026). Network: 2,501 signalised sites.

| Period | Local time | Run |
|---|---|---|
| AM peak | Tue 10 Nov 08:00–08:30 | `1c471700a1a7` |
| Midday | Tue 10 Nov 12:00–12:30 | `dd770710a459` |
| PM peak | Tue 10 Nov 17:00–17:30 | `b945a002995f` – **not usable** (see 6.1) |
| Weekend midday | Sun 8 Nov 12:00–12:30 | `7f753b994c98` |

## 1. Network outcome

| Period | Screened (Q2 pass, enough data) | Red | Amber – traffic | Amber – signal | Normal | Grey | Detector Health |
|---|---|---|---|---|---|---|---|
| AM peak | 1,224 (49 %) | 83 (6.8 %) | 508 (41.5 %) | 51 (4.2 %) | 582 (47.5 %) | 924 | 353 |
| Midday | 1,189 (48 %) | 114 (9.6 %) | 579 (48.7 %) | 61 (5.1 %) | 435 (36.6 %) | 923 | 389 |
| Weekend midday | 1,141 (46 %) | 89 (7.8 %) | 611 (53.5 %) | 43 (3.8 %) | 398 (34.9 %) | 879 | 481 |

Percentages of Red, Amber and Normal are of the screened sites. About half of the network is screened in each period;
the rest is Grey (35–37 %) or Detector Health (14–19 %).

**Persistence.** Of the 255 sites Red in at least one of the three periods, 228 are Red in one period only, 23 in two
and 4 in all three (SCATS 3101, 3191, 3439, 4445). 275 sites are Red or Amber in all three periods.

## 2. What drives the categories

| | AM peak | Midday | Weekend midday |
|---|---|---|---|
| **Red** – Q1 approaches flagged per site (mean) | 1.45 | 1.49 | 1.65 |
| Red – Q1 directions (high / low) | 89 / 31 | 112 / 58 | 104 / 43 |
| Red – median Q1 difference | 17.6 % | 17.3 % | 23.3 % |
| Red – Q3 pattern: stability + phase service | 54 | 66 | 42 |
| Red – Q3 pattern: cycle length + phase service | 18 | 27 | 33 |
| Red – Q3 pattern: cycle length + stability (± phase service) | 11 | 21 | 14 |
| Red – abnormal cycle length longer / shorter | 27 / 2 | 36 / 12 | 33 / 14 |
| Red – Q3C directions (low / high), median change | 70 / 43, 12.9 pp | 78 / 72, 13.0 pp | 55 / 85, 17.0 pp |
| **Amber – traffic** – Q1 directions (high / low) | 546 / 119 | 500 / 281 | 641 / 209 |
| **Amber – signal** – poorer stability | 46 of 51 | 50 of 61 | 28 of 43 |

- **Q3 is driven by Cycle Stability and phase service.** Poorer stability is part of the Q3 finding in most Red sites
  (65 of 83 in the AM peak).
- **Traffic changes are mostly increases** (82 % of flagged approaches in the AM peak Amber sites), and abnormal cycle
  lengths are mostly longer. See 4.2.

## 3. TomTom confirmation (Q5, Red sites)

| Period | Red | Q5 available | Agreement | Partial agreement | Disagreement | Insufficient coverage |
|---|---|---|---|---|---|---|
| AM peak | 83 | 30 (36 %) | 4 | 19 | 7 | 0 |
| Midday | 114 | 58 (51 %) | 7 | 39 | 12 | 0 |
| Weekend midday | 89 | 34 (38 %) | 5 | 21 | 7 | 1 |

- Every unavailable confirmation (164 reports) has the same reason: **the site has no TomTom approach mapping**; the
  queue is unavailable at the same sites ("no verified TomTom junction"). This is the coverage of the validated mapping
  file, not a code issue.
- Where TomTom is available, partial agreement is the usual result: one SCATS-identified approach matches, others are
  not covered or differ.

## 4. Findings for the methodology owner

### 4.1 Amber – traffic is common, not exceptional
Between 41 % and 54 % of the screened sites are Amber – traffic in each period, and only 35–48 % are Normal. With the
normal range at the 10th–90th percentile, each approach is outside its range in about one period in five by
construction; a site with three or four approaches therefore has a high chance that one is outside, and the 10 %
minimum difference removes only part of these. With 5–7 reference weeks, the 10th and 90th percentiles sit close to
the lowest and highest weekly values, which narrows the range further. The category is working as specified, but it
should be read as "one approach differs from its recent weeks", not as an exceptional event.

### 4.2 Increases dominate – check the reference weeks
In every period most flagged approaches are higher than usual. One likely contributor, to be verified: the reference
weeks include the Victorian school holidays (Term 3 holidays, about 19 Sep – 4 Oct 2026). For Tue 10 Nov the reference
weeks include Tue 22 and 29 Sep; for Sun 8 Nov, Sun 20 and 27 Sep. Holiday weeks lower the usual value and make an
ordinary school-term period read "higher than usual". The methodology excludes public holidays, daylight-saving change
days and the year end, but not school holidays. Check with `python main.py inspect --site <n> --end <period> --history`
(values per reference week) before deciding.

### 4.3 The history is at its minimum, network-wide
The number of reference weeks behind the flagged values is the same at almost every site:

| Period | Q1 | Q3C | Cycle length / stability |
|---|---|---|---|
| AM peak | 6 weeks | **5 weeks** | **5 weeks** |
| Midday | 6 | 6 | 6 |
| Weekend midday | **5 weeks** | **5 weeks** | 7 |

Seven reference weeks are usable in each period, so whole reference days are missing network-wide (e.g. two Sundays
of volume at 12:00). Many results rest on the 5-week minimum; one more missing day would make them not assessable.
`python main.py audit --end <period>` (section 7) lists the weeks.

### 4.4 Small numbers
- **Low volume:** 4–7 Red and 19–25 Amber sites per period are flagged on an approach whose usual volume is below
  20 veh/30 min (e.g. 9 against 5.5, +63.6 %; 3 against 6, −50 %). There is no minimum volume in the method.
- **Usual value of 0:** 2 Q1 cases (SCATS 4562 Flinders Street [SW], 312 against 0 veh/30 min) and 11 Q3C cases
  (e.g. 4524, 803, 786) have a usual value of 0 – a mapping or data change rather than traffic.
- **Usual green share 100 %:** 30–40 Red and Amber sites per period have a Low phase-service finding on an approach
  whose usual green share is 100 % (served in every phase), e.g. SCATS 1037 Queensberry Street [E] 57.2 % against
  100 %. These follow the phase-to-approach assignment and should be checked as mapping cases.
- **Large changes:** about 55 sites per period with a Q1 change of 50 % or more (e.g. 4020 Glenlyon Road [W] +206 %)
  and 100–150 with a Q3C change of 30 percentage points or more.

## 5. Wording of the reports (286 Red reports)

| Check | Result |
|---|---|
| LLM wording used | 284 of 286; 2 answers rejected by the checks and replaced by the code's wording (SCATS 1120: missing "Overall:" line; 2887: missing "Possible explanations" label) |
| Required labels present | All reports |
| Causal or fault claims | None found |
| Numbers in the Diagnosis | 13 reports, all restating the rule ("less than 10 % from usual"); no measured value |
| Interpretive words | 10 reports with "does not prove that one caused the other" (intended caution); 1 "despite" (SCATS 2500) |
| Delay of approaches not adequately observed | Stated as "not established" (14 reports); no value cited |
| Caveat on historically abnormal delay repeated | 5 reports |
| Link IDs | Only in the technical coverage notes of section 3 (mapping links of stub approaches), not in the findings |

The Diagnosis states what the data show and keeps explanations separate and hedged. Remaining issues are stylistic
(a repeated caveat, an occasional redundant clause such as "not flagged because … so it is not flagged").

## 6. Issues found in the run and their status

1. **PM peak screened before its data were complete** (2,501 Grey). Fixed: a period is now refused until the data
   latency has passed; rerun with `audit-reports --rescreen --end "PM peak=2026-11-10T17:30"`.
2. Flag names with spaces split in the summary; flags for usual values of 0 added. Fixed.
3. Earlier fixes already in this run: Q5 verdict for approaches observed by queue only, link-speed minutes,
   approach delay and control delay passed separately, reason when TomTom is unavailable.

## 7. Recommendations

1. Rerun the PM peak.
2. Verify 4.2 (school holidays in the reference weeks) on a few sites; if confirmed, propose excluding school holiday
   weeks for weekday periods (a methodology decision).
3. List the missing reference days (4.3) and send them to the data owner.
4. Report 4.1 and 4.4 to the methodology owner as interpretation notes for V1; a minimum volume or a materiality
   threshold would be a methodology change, not part of V1.
5. Send the usual-zero and usual-100 % cases (4.4) to the data owner as mapping checks.
