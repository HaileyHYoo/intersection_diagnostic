# Intersections Diagnostics V1 – review of the diagnoses and checks (four periods, November 2026)

Review of every screening result, Red report and Amber evidence page of four periods, produced by
`python main.py audit-reports` (batch `20261112_1002`, `details.jsonl`). The aim is to judge whether the diagnoses
and the suggested engineering checks are reasonable, and where the method, the data and the wording can improve.

| Period | Local time | Run | Red reports with LLM wording |
|---|---|---|---|
| AM peak | Tue 10 Nov 2026 08:00–08:30 | `1c471700a1a7` | 83 of 83 (D001) |
| Midday | Tue 10 Nov 2026 12:00–12:30 | `dd770710a459` | 113 of 114 |
| PM peak | Tue 10 Nov 2026 17:00–17:30 | `67dc5adb0f4f` | 82 of 83 |
| Weekend midday | Sun 8 Nov 2026 12:00–12:30 | `7f753b994c98` | 89 of 89 |

## 0. Summary

- **About half the network is screened in each period** (46–49 %); the rest is Grey (35–39 %) or Detector Health
  (12–19 %). Of the screened sites, 7–10 % are Red, 42–56 % Amber – traffic, 4–5 % Amber – signal, 33–48 % Normal.
- **Red is mostly transient**: 313 sites are Red at least once; 268 in one period only, 3 in all four. Persistent Red
  sites show the same phase-service change in every period and are the strongest candidates for a real change.
- **The diagnoses are reasonable and safe.** No report claims a fault or a cause; no check asks to change a setting;
  the LLM keeps the code's checks in 368 of 369 reports. The LLM keeps the key explanation of each pattern in most
  reports but softens "opposite of a demand response" in 9 of 81 cases.
- **TomTom confirmation is weak evidence as defined.** It is available for 44 % of Red sites (TomTom mapping covers
  41 % of the network), and where available a SCATS-identified approach "agrees" 47 % of the time – about what a
  randomly chosen approach would score (45 %), because three "largest" measures are ranked among about four
  approaches.
- **Three method issues shape the results**: small volumes are flagged two to four times as often as large ones;
  traffic reads higher than usual network-wide (mean +3 % to +7 %), most likely because the reference weeks include
  the September school holidays; and most values rest on the 5-week minimum because whole reference days are missing.

## 1. Statistics by period

### 1.1 Categories

| Period | Screened | Red | Amber – traffic | Amber – signal | Normal | Grey | Detector Health |
|---|---|---|---|---|---|---|---|
| AM peak | 1,224 (49 %) | 83 (6.8 %) | 508 (41.5 %) | 51 (4.2 %) | 582 (47.5 %) | 924 (37 %) | 353 (14 %) |
| Midday | 1,189 (48 %) | 114 (9.6 %) | 579 (48.7 %) | 61 (5.1 %) | 435 (36.6 %) | 923 (37 %) | 389 (16 %) |
| PM peak | 1,222 (49 %) | 83 (6.8 %) | 685 (56.1 %) | 53 (4.3 %) | 401 (32.8 %) | 967 (39 %) | 312 (12 %) |
| Weekend midday | 1,141 (46 %) | 89 (7.8 %) | 611 (53.5 %) | 43 (3.8 %) | 398 (34.9 %) | 879 (35 %) | 481 (19 %) |

Shares of Red, Amber and Normal are of the screened sites; Grey and Detector Health of all 2,501 sites.

### 1.2 What drives Red

| Q3 pattern of Red sites | AM peak | Midday | PM peak | Weekend midday |
|---|---|---|---|---|
| Poorer stability + phase service | 54 | 66 | 62 | 42 |
| Cycle length + phase service | 18 | 27 | 15 | 33 |
| Cycle length + poorer stability | 8 | 11 | 5 | 6 |
| All three | 3 | 10 | 1 | 8 |
| Q1 approaches flagged per Red site (mean) | 1.45 | 1.49 | 1.48 | 1.65 |
| Flagged Q1 approaches higher than usual (Red + Amber) | 81 % | 64 % | 74 % | 75 % |
| Abnormal cycle lengths that are longer | 27 of 29 | 36 of 48 | 18 of 21 | 33 of 47 |

Q3 is mostly "poorer stability + phase service"; cycle-length findings are mostly longer cycles, in line with the
mostly higher volumes.

### 1.3 Persistence

| | Sites |
|---|---|
| Red in 1 / 2 / 3 / 4 periods | 268 / 37 / 5 / 3 |
| Red only in the AM peak / midday / PM peak / weekend | 61 / 88 / 58 / 61 |
| Red on a weekday but not at the weekend | 224 |
| Red or Amber in 1 / 2 / 3 / 4 periods | 261 / 375 / 379 / 203 |
| Screened in all four periods | 1,044 – of which Red or Amber in all four: 203 (19 %) |

**Red in all four periods** – each shows the same phase-service change throughout:

| SCATS | Intersection | Finding repeated in every period |
|---|---|---|
| 3101 | Bluff Road / Highett Road | Highett Road [W] green share 22–31 % against a usual 34–37 %; longer cycle in three periods |
| 3191 | Clayton Road / Dunstan Street | Clayton Road [S] green share 63–70 % against a usual 29–34 % (three periods); poorer stability in all four |
| 4445 | Albert Street / Gisborne Street | Gisborne Street [S] green share 39–41 % against 45–47 % (three periods); poorer stability in all four |

These are better candidates for an operational or mapping change than any single-period Red, and the screening has
no way to show it today (see 7.4).

## 2. TomTom coverage

- **Network**: the validated TomTom mapping file covers 1,017 of 2,501 sites (41 %).
- **Red sites**:

| Period | Red | With TomTom data | Delay adequately observed | Queue adequately observed | Both |
|---|---|---|---|---|---|
| AM peak | 83 | 30 | 29 | 30 | 29 |
| Midday | 114 | 58 | 58 | 58 | 58 |
| PM peak | 83 | 40 | 36 | 40 | 36 |
| Weekend midday | 89 | 34 | 33 | 34 | 33 |
| **All** | **369** | **162 (44 %)** | **156** | **162** | **156** |

- All 207 Red reports without TomTom data have the same reason, no TomTom approach mapping (plus 3 PM peak reports
  where an InfluxDB query failed momentarily during the run).
- **Observed minutes per mapped approach**: delay 30 of 30 minutes on 394 approaches, 15 of 30 on 145, none on 123;
  queue 30 of 30 minutes on all 662. The queue archive is complete wherever a junction is mapped; delay is the
  limiting measure.

## 3. Distributions

### 3.1 Volume (approaches of the screened sites)

| Period | Approaches | 10th / 25th / median / 75th / 90th percentile of the usual volume (veh/30 min) |
|---|---|---|
| AM peak | 4,078 | 60 / 142 / 295 / 512 / 787 |
| Midday | 3,939 | 54 / 120 / 243 / 412 / 600 |
| PM peak | 4,069 | 74 / 163 / 330 / 555 / 808 |
| Weekend midday | 3,797 | 57 / 131 / 266 / 454 / 654 |

**Share of approaches flagged by Q1, by usual volume (veh/30 min)**:

| Usual volume | < 20 | 20–50 | 50–100 | 100–200 | 200–400 | 400–800 | ≥ 800 |
|---|---|---|---|---|---|---|---|
| AM peak | 29 % | 28 % | 26 % | 25 % | 21 % | 14 % | 7 % |
| Midday | 37 % | 38 % | 35 % | 31 % | 23 % | 15 % | 7 % |
| PM peak | 31 % | 39 % | 44 % | 33 % | 31 % | 23 % | 12 % |
| Weekend midday | 41 % | 36 % | 33 % | 33 % | 26 % | 20 % | 20 % |

Small approaches are flagged two to four times as often as large ones: a few vehicles move a small count past
both the percentile and the 10 % test.

**Change against the usual value, all assessed approaches**: median +2.0 % to +3.7 %, mean +3.4 % to +7.2 %, and 57–65 %
of approaches above their usual value. The flagged approaches: median +12.5 % to +15.3 %, with 16–21 % more than
25 % above usual and 5–9 % more than 25 % below.

### 3.2 Signal measures (screened sites)

| | AM peak | Midday | PM peak | Weekend midday |
|---|---|---|---|---|
| Usual green share – median (25th–75th) | 66 % (45–90) | 65 % (45–91) | 64 % (45–90) | 64 % (46–91) |
| Flagged green change – median (10th / 90th) | −4.5 pp (−41 / +20) | −5.1 (−40 / +17) | −5.0 (−40 / +18) | +2.3 (−54 / +27) |
| Usual cycle length – median (10th / 90th) | 113 s (71 / 135) | 90 s (60 / 127) | 116 s (72 / 140) | 95 s (61 / 129) |
| Flagged cycle change – median | +13.9 % | +13.4 % | +13.8 % | +14.0 % |
| Usual Cycle Stability – median | 86 | 80 | 88 | 78 |
| Current stability when flagged – median | 66 | 57 | 74 | 54 |

A quarter of approaches have a usual green share of 90 % or more (served in almost every phase); a Low finding on
such an approach is often a phase-to-approach assignment change rather than a change in operation.

### 3.3 TomTom (Red sites, adequately observed approaches)

| Measure | 10th | 25th | Median | 75th | 90th |
|---|---|---|---|---|---|
| Control delay (s, n = 395) | 4.0 | 12.7 | 22.6 | 36.5 | 57.5 |
| Approach delay (s) | 2.6 | 10.8 | 20.6 | 32.8 | 54.0 |
| Mean queue (m, n = 681) | 0 | 18 | 45 | 73 | 117 |
| Maximum queue (m) | 0 | 42 | 77 | 119 | 214 |

### 3.4 Link speed (Red sites)

- 1,285 links with a speed; median 29 km/h (10th–90th: 14–46 km/h).
- 997 links have a reference speed. Difference from the reference: median −0.9 % (10th −17 %, 90th +15 %); 74 links
  (7 %) are more than 20 % slower than usual. Red sites do not, in general, show slower traffic on their incoming links.
- **Minutes with speed** read 20 of 30 for 53 % of links, 25 for 24 % and 30 for 22 %. With one record counted as
  5 minutes this suggests the feed delivers about four records per 30 minutes, not six; the feed's interval should be
  confirmed (`inspect` now prints the stamps) before this figure is shown as coverage.

## 4. Diagnosis types

### 4.1 Types and counts
A Red site can show several patterns. The code (D001) writes a fixed explanation for each:

| Type | Pattern | Explanation written | AM | Mid | PM | Wknd | Total |
|---|---|---|---|---|---|---|---|
| A1 | Same approach: green opposite to volume (less green, more traffic, or the reverse) | the opposite of a demand response – the finding most worth verifying | 19 | 19 | 17 | 26 | **81** |
| A2 | Same approach: green follows volume | SCATS following demand, or the counted volume following the green given | 27 | 36 | 24 | 33 | **120** |
| B1 | Cycle change in the direction of the volume change | SCATS lengthening/shortening the cycle as demand rose/fell | 24 | 26 | 17 | 39 | **106** |
| B2 | Cycle change with volume moving both ways | not clearly a demand response; a plan or coordination change possible | 2 | 10 | 3 | 4 | **19** |
| B3 | Cycle change not matched by volume | a plan or coordination change is a possible explanation | 3 | 12 | 1 | 4 | **20** |
| C | Phase-service change on an approach without a traffic finding | may follow demand on competing phases or the coordination plan | 52 | 79 | 58 | 52 | **241** |
| D | Poorer cycle stability | the cycle varied more than usual, which can happen while SCATS adapts | 65 | 87 | 68 | 56 | **276** |
| E | Traffic change on an approach without a phase-service finding | its cause is not shown by the SCATS data | 56 | 88 | 63 | 61 | **268** |

**Most frequent combination**: C + D + E (108 of 369 reports) – poorer stability and a phase-service change on one
approach, with a traffic change on another. The SCATS data relate neither finding to the other, so these reports end
with checks rather than an explanation.

**Primary type** (in the order the checks are prioritised): C 108, A2 98, A1 81, B1 53, B3 17, B2 12.

### 4.2 Are the explanations reasonable?

| Type | Assessment |
|---|---|
| A1 | Sound and the most useful: more green with less traffic (or the reverse) is not what demand-responsive control does, and it is put first. 3 of 91 such approach pairs rest on a usual volume below 20 veh/30 min, where the "opposite" may be noise. |
| A2 | Sound; stating both readings (SCATS follows demand, or the detectors count only what the green lets through) is correct for SCATS strategic detectors. |
| B1 | Sound as a possibility; a longer cycle with higher volume is the expected adaptive response. It is hedged ("may be"). |
| B2, B3 | Sound; a cycle change that volume does not explain points to the plan or coordination. |
| C | Reasonable but weak: "may follow demand on competing phases" is generic. 15 % of sites with a Q3C finding have two or more flagged approaches with identical values – approaches served by the same phases – so one phase change is reported as several findings (557 flagged approaches at Red sites are 496 distinct changes). |
| D | Reasonable; poorer stability is common (276 of 369) and its explanation is generic. |
| E | Correct and honest ("its cause is not shown by the SCATS data"). |

**LLM wording against the code's explanation** (367 LLM-worded diagnoses):

| Type | LLM keeps the explanation | Note |
|---|---|---|
| A1 | 72 of 81 | 9 soften it, e.g. "may be an adaptive response or may warrant verification" (SCATS 4498) – which reads more green with less traffic as possibly adaptive, the opposite of the code's point |
| A2 | 118 of 120 | |
| B1 | 106 of 106 | |
| B2 | 14 of 19 | 5 write "may be an adaptive response or a plan change" instead of "not clearly a demand response" – acceptable |
| B3, C, D | all | |

No LLM diagnosis claims a fault or a cause, mentions TomTom, or quotes a measured value (13 restate the "less than
10 % from usual" rule). Three answers were rejected by the checks and replaced by the code's wording (missing
"Overall:" line; missing "Possible explanations" label; one false "made-up link ID" for the words "link them",
since corrected).

## 5. Suggested engineering checks

### 5.1 The checks and their frequency (369 Red reports)

| Check | Written when | Reports | Usually listed |
|---|---|---|---|
| K1 Verify phase service on X against its demand: green time and phase calls cycle by cycle with the detector counts | traffic and phase-service findings on the same approach (A1, A2) | 225 | first (188) |
| K2 Verify whether the longer/shorter cycle was SCATS's adaptive response or a plan or coordination change: plan, subsystem cycle length, linking and offsets | abnormal cycle length (B) | 145 | first or second |
| K3 Check phase service to X: phase calls, skipped or extended phases, demand on the competing phases | phase-service finding without a traffic finding (C) | 332 | second |
| K4 Review cycle-by-cycle cycle lengths in Signal Performance to confirm the poorer stability | poorer stability (D) | 276 | second or third |
| K5 Check for incidents, events, roadworks or diversions that could explain the unusual volume on X, and monitor whether it persists | traffic finding without a phase-service finding (E) | 344 | last |

Checks per report: 2 (30), 3 (162), 4 (116), 5 (54), 6 (7).

### 5.2 Are the checks reasonable?
- **Yes, as review steps.** Each check names the approach, the data to look at (Signal Performance, phase calls,
  detector counts, plan and linking) and stays within "review, verify, investigate"; none asks to change a setting.
  The order follows the strength of the evidence (A1 first, incidents last). The LLM keeps the checks: the same number
  in 368 of 369 reports, with no instruction to adjust or retime.
- **What is missing or could be better:**
  1. **Repeated checks.** K5 is written once per approach (up to four times in one report, e.g. SCATS 3072); one check
     naming the approaches would be clearer.
  2. **Mapping checks.** A Low finding on an approach whose usual green share is 100 % (30–60 sites per period) or a
     usual value of 0 should prompt "check the phase-to-approach (or link) assignment" before any operational check.
  3. **Detector checks.** When a site was screened with one failing detector tolerated (15–22 Red sites per period),
     K1's comparison "with the detector counts" should name the low detector.
  4. **Duplicated phase changes.** Approaches with identical green-share values should be checked once, as one phase.
  5. **Persistence.** A finding repeated in other periods (e.g. SCATS 3101, 3191, 4445) deserves a stronger check than
     "monitor whether it persists".
  6. **Low volume.** A1 based on a usual volume under 20 veh/30 min should be marked as low-volume.

## 6. TomTom against the SCATS diagnosis

**Site verdict by primary type** (Red sites):

| Primary type | Agreement | Partial | Disagreement | Insufficient coverage | Unavailable |
|---|---|---|---|---|---|
| A1 (green opposite to volume) | 8 | 24 | 9 | 0 | 40 |
| A2 (green follows volume) | 6 | 29 | 7 | 1 | 55 |
| B1 (adaptive cycle) | 4 | 11 | 4 | 0 | 34 |
| B2, B3 (cycle not explained by volume) | 1 | 6 | 1 | 0 | 21 |
| C (phase service elsewhere) | 3 | 34 | 13 | 1 | 57 |

**Per SCATS-identified approach**: agreement 43–48 % for every kind of finding (Q1 only 42 %, Q3C only 48 %, both 43 %).

**Against chance.** At the 162 Red sites with TomTom data, an approach chosen at random among the observed ones would
have the greatest control delay, the greatest approach delay or the longest queue 45 % of the time; the
SCATS-identified approaches do so 47 % of the time. With three "largest" measures among about four observed
approaches, "agreement" is close to what any approach would get, and it does not distinguish diagnosis types. Q5 as
defined shows where road users wait most, but it does not confirm the SCATS finding.

## 7. Overall assessment and improvements

### 7.1 Assessment
- The **classification** follows the methodology exactly; the **diagnoses** are factual, hedged and complete; the
  **checks** are appropriate review steps in a sensible order. Nothing in the reports would mislead an engineer into
  a wrong action.
- The **weakest links** are the evidence behind the findings (small volumes, school holidays and missing days in the
  history), the large share of generic C + D + E reports, and a TomTom confirmation that cannot discriminate.

### 7.2 Method (decisions for the methodology owner)
1. **School holidays in the history.** Exclude Victorian school-holiday weeks from the reference weeks of weekday
   periods (the history already excludes public holidays). Expected: fewer "higher than usual" findings, especially in
   the AM peak. Validate with a run on Wed 2 Dec and Sat 5 Dec 2026, whose reference weeks contain no school or
   public holiday, and with a sensitivity run on the November periods.
2. **Minimum volume.** Do not flag an approach whose usual volume is below a minimum (e.g. 20–50 veh/30 min), or show
   it as low-volume. Q1 flags small approaches two to four times as often as large ones.
3. **History at its minimum.** Most values rest on 5 weeks. Keep the 5-week minimum for V1, but list the missing
   reference days and ask the data owner to backfill them.
4. **Q5 confirmation.** Compare each approach's TomTom delay with its own history (as Q1 and Q3 do), or rank on one
   primary measure with a margin, so that "agreement" means more than being among the top of three rankings.
5. **Persistence.** Show how many of the recent periods a site was Red or Amber, and the repeated finding.

### 7.3 Data and mapping (for the data owner)
1. Missing reference days network-wide (5 weeks in the AM peak for Q3, all PM peak measures, the weekend Q1/Q3C).
2. Usual values of 0 and usual green shares of 100 % with Low findings: phase-to-approach and link assignment.
3. TomTom mapping covers 41 % of sites; extending it is the only way to raise Q5 availability.
4. The link-speed feed's interval (about four records per 30 minutes observed).

### 7.4 Wording and checks (code, no methodology change)
1. Require the A1 explanation ("the opposite of a demand response") in the LLM answer, as the required labels are.
2. Merge the incident checks of one report into one check naming the approaches.
3. Group approaches with identical green-share values as one phase in the diagnosis and checks.
4. Add a mapping check for Low findings on usual-100 % approaches and usual values of 0.
5. Name a tolerated failing detector in K1.
6. Mark low-volume findings in the diagnosis.
