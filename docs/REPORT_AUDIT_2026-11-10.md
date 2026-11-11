# Report audit – four periods, 8 and 10 Nov 2026

Full review of every Red report and Amber evidence page produced by `python main.py audit-reports`
(batches `20261110_1532` and `20261112_0930`, code of 10 Nov 2026). Network: 2,501 signalised sites.

| Period | Local time | Run | Report wording |
|---|---|---|---|
| AM peak | Tue 10 Nov 08:00–08:30 | `1c471700a1a7` | LLM (gpt-5.6-luna), checked |
| Midday | Tue 10 Nov 12:00–12:30 | `dd770710a459` | LLM, checked |
| PM peak | Tue 10 Nov 17:00–17:30 | `67dc5adb0f4f` | Code only (the LLM call failed authentication; see 6) |
| Weekend midday | Sun 8 Nov 12:00–12:30 | `7f753b994c98` | LLM, checked |

## 1. Network outcome

| Period | Screened | Red | Amber – traffic | Amber – signal | Normal | Grey | Detector Health |
|---|---|---|---|---|---|---|---|
| AM peak | 1,224 (49 %) | 83 (6.8 %) | 508 (41.5 %) | 51 (4.2 %) | 582 (47.5 %) | 924 (37 %) | 353 (14 %) |
| Midday | 1,189 (48 %) | 114 (9.6 %) | 579 (48.7 %) | 61 (5.1 %) | 435 (36.6 %) | 923 (37 %) | 389 (16 %) |
| PM peak | 1,222 (49 %) | 83 (6.8 %) | 685 (56.1 %) | 53 (4.3 %) | 401 (32.8 %) | 967 (39 %) | 312 (12 %) |
| Weekend midday | 1,141 (46 %) | 89 (7.8 %) | 611 (53.5 %) | 43 (3.8 %) | 398 (34.9 %) | 879 (35 %) | 481 (19 %) |

"Screened" = sites with a Red, Amber or Normal result; the shares of Red, Amber and Normal are of these. About half of
the network is screened in each period; the rest is Grey or Detector Health.

**Persistence.** 313 sites are Red in at least one period: 268 in one period only, 37 in two, 5 in three and 3 in all
four (SCATS 3101 Bluff Road / Highett Road, 3191 Clayton Road / Dunstan Street, 4445 Albert Street / Gisborne Street).
203 sites are Red or Amber in all four periods.

## 2. What drives the categories

| | AM peak | Midday | PM peak | Weekend midday |
|---|---|---|---|---|
| **Red** – Q1 approaches flagged per site (mean) | 1.45 | 1.49 | 1.48 | 1.65 |
| Red – median Q1 difference | 17.6 % | 17.3 % | 18.2 % | 23.3 % |
| Red – Q3 pattern: stability + phase service | 54 | 66 | 62 | 42 |
| Red – Q3 pattern: cycle length + phase service | 18 | 27 | 15 | 33 |
| Red – Q3 pattern: cycle length + stability (± phase service) | 11 | 21 | 6 | 14 |
| Red – abnormal cycle length longer / shorter | 27 / 2 | 36 / 12 | 18 / 3 | 33 / 14 |
| Red – Q3C low / high, median change | 70 / 43, 12.9 pp | 78 / 72, 13.0 pp | 78 / 44, 16.1 pp | 55 / 85, 17.0 pp |
| **Red + Amber** – flagged Q1 approaches that are higher than usual | **81 %** | 64 % | 74 % | 75 % |
| **Amber – signal** – poorer stability | 46 of 51 | 50 of 61 | 45 of 53 | 28 of 43 |

- **Q3 is driven by Cycle Stability and phase service.** Poorer stability is part of the Q3 finding in most Red and
  Amber – signal sites.
- **Traffic changes are mostly increases**, most of all in the AM peak (4.2).

## 3. TomTom confirmation (Q5, Red sites)

| Period | Red | Q5 available | Agreement | Partial agreement | Disagreement | Insufficient coverage |
|---|---|---|---|---|---|---|
| AM peak | 83 | 30 (36 %) | 4 | 19 | 7 | 0 |
| Midday | 114 | 58 (51 %) | 7 | 39 | 12 | 0 |
| PM peak | 83 | 42 (51 %) | 8 | 25 | 8 | 1 |
| Weekend midday | 89 | 34 (38 %) | 5 | 21 | 7 | 1 |

- All 205 unavailable confirmations have one reason: **the site has no TomTom approach mapping**; the queue is
  unavailable at the same sites ("no verified TomTom junction"). This is the coverage of the validated mapping file.
- Where TomTom is available, partial agreement is the usual result (60 %): one SCATS-identified approach matches,
  others are not covered or differ. Full agreement is 15 %, disagreement 21 %.

## 4. Findings for the methodology owner

### 4.1 Amber – traffic is common, not exceptional
42–56 % of the screened sites are Amber – traffic and only 33–48 % are Normal. With the normal range at the 10th–90th
percentile, each approach is outside its range in about one period in five by construction; a site with three or four
approaches therefore often has one outside, and the 10 % minimum difference removes only part of these. With 5–7
reference weeks the percentiles sit close to the lowest and highest weekly values, which narrows the range further.
The category works as specified but reads as "one approach differs from its recent weeks", not as an exceptional event.

### 4.2 Increases dominate – likely the school holidays in the reference weeks (to verify)
Between 64 % and 81 % of the flagged approaches are higher than usual. The share is highest in the AM peak (81 %, the
school run) and lowest at midday (64 %). The reference weeks include the Victorian Term 3 school holidays (about
19 Sep – 4 Oct 2026): Tue 22 and 29 Sep for the Tuesday periods, Sun 20 and 27 Sep for the Sunday period. Holiday
weeks lower the usual value, so an ordinary school-term period reads "higher than usual". The methodology excludes
public holidays, daylight-saving change days and the year end, but not school holidays. Verify with
`python main.py inspect --site <n> --end <period> --history` (values per reference week) on a few sites.

### 4.3 The history is at its minimum, network-wide
The number of reference weeks behind the flagged values is the same at almost every site:

| Period | Q1 | Q3C | Cycle length / stability |
|---|---|---|---|
| AM peak | 6 weeks | **5** | **5** |
| Midday | 6 | 6 | 6 |
| PM peak | **5** | **5** | **5** |
| Weekend midday | **5** | **5** | 7 |

Seven reference weeks are usable in each period, so whole reference days are missing across the network (e.g. two
Tuesdays at 17:00 for every feed). Most results rest on the 5-week minimum; one more missing day would make them not
assessable. `python main.py audit --end <period>` (section 7) lists the weeks.

### 4.4 Small numbers and mapping cases (sites per period, Red / Amber)

| Flag | AM peak | Midday | PM peak | Weekend midday |
|---|---|---|---|---|
| Flagged approach with usual volume below 20 veh/30 min | 4 / 19 | 7 / 23 | 1 / 17 | 7 / 25 |
| Q1 change of 50 % or more | 10 / 45 | 12 / 42 | 5 / 49 | 16 / 45 |
| Q3C change of 30 percentage points or more | 19 / 92 | 28 / 112 | 25 / 116 | 27 / 145 |
| Usual green share 100 % with a Low finding | 7 / 34 | 11 / 31 | 13 / 48 | 4 / 16 |
| Usual value of 0 (Q1 or Q3C) | 1 / 3 | 1 / 4 | 0 / 4 | 0 / 3 |
| One failing detector tolerated | 14 / 132 | 22 / 121 | 15 / 119 | 18 / 138 |

Examples: low volume 9 against 5.5 veh/30 min (+63.6 %); usual 0 at SCATS 4562 Flinders Street [SW] (312 against 0);
usual green 100 % at SCATS 1037 Queensberry Street [E] (57.2 % against 100 %); large change at 4020 Glenlyon Road [W]
(+206 %). The usual-zero and usual-100 % cases follow the link or phase-to-approach assignment and are mapping checks.

## 5. Wording of the reports (369 Red reports)

| Check | Result |
|---|---|
| LLM wording used | 284 of 286 in AM, midday and weekend (2 answers rejected by the checks and replaced by the code's wording); none in the PM peak (authentication failure) |
| Required labels present | All reports |
| Causal or fault claims | None |
| Numbers in the Diagnosis | 13 LLM reports, all restating the rule ("less than 10 % from usual"); no measured value |
| Delay of approaches not adequately observed | Stated as "not established"; no value cited |
| Caveat on historically abnormal delay repeated | 5 LLM reports |
| Link IDs | Only in the technical coverage notes (mapping links of stub approaches), not in the findings |

The Diagnosis states what the data show and keeps explanations separate and hedged. The code wording (PM peak) is
complete and correct but plainer. Remaining LLM issues are stylistic (a repeated caveat, an occasional redundant
clause).

## 6. Issues in the runs and their status

1. The first PM peak run was made before its data were complete (2,501 Grey). Fixed: such a period is now refused;
   the PM peak was rerun.
2. PM peak: every LLM call failed authentication, so all 83 reports use the code's wording. Fix the `OPENAI_API_KEY`
   seen by the terminal and rerun the PM peak without `--resume` to get the LLM wording (classification unchanged).
3. Flag names and usual-zero flags corrected in the second batch; the first batch was recounted for this report.

## 7. Recommendations

1. Verify 4.2 on a few sites; if confirmed, run a sensitivity screening with the school-holiday weeks left out, and
   propose the exclusion for weekday periods to the methodology owner.
2. List the missing reference days (4.3) and send them to the data owner.
3. Report 4.1 and 4.4 to the methodology owner as interpretation notes for V1; a minimum volume or materiality
   threshold would be a methodology change.
4. Send the usual-zero and usual-100 % cases to the data owner as mapping checks.
5. Report the TomTom mapping coverage (Q5 available at 36–51 % of Red sites) as a known limitation of Q5.
