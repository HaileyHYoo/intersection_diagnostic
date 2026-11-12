# Intersections Diagnostics V1 – review of the diagnoses

Review of every screening result, Red report and Amber evidence page of four periods. The aim is to judge whether the
diagnoses and the suggested engineering checks are reasonable, and where the method, the data and the wording can
improve.

The screening (Q2, then Q1 and Q3A/B/C) classifies every site. A click on a Red site adds the diagnosis of the SCATS
evidence (Q4) and the TomTom check of road-user impact (Q5).

| Period | Local time | Run | Reports (Red) |
|---|---|---|---|
| AM peak | Tue 10 Nov 2026 08:00–08:30 | `1c471700a1a7` | 83 |
| Midday | Tue 10 Nov 2026 12:00–12:30 | `dd770710a459` | 114 |
| PM peak | Tue 10 Nov 2026 17:00–17:30 | `67dc5adb0f4f` | 83 |
| Weekend midday | Sun 8 Nov 2026 12:00–12:30 | `7f753b994c98` | 89 |

## 1. Summary

- **About half the network is assessed in each period** (46–49 %); the rest is Grey (35–39 %) or Detector Health
  (12–19 %). Of the assessed sites, 7–10 % are Red, 42–56 % Amber – traffic, 4–5 % Amber – signal and 33–48 % Normal.
- **Red is mostly transient**: 313 sites are Red at least once; 268 in one period only, 3 in all four. Persistent Red
  sites show the same phase-service change in every period.
- **TomTom data cover only 44 % of Red sites** (the TomTom mapping covers 41 % of the network).
- **Three method issues shape the results:**
  - small volumes are flagged two to four times as often as large ones;
  - each approach is compared only with its own recent weeks, so network-wide trends are not separated from site
    changes: traffic reads 3–7 % higher than usual across the network, most likely because the reference weeks
    include the September school holidays;
  - most values rest on the 5-week minimum because whole reference days are missing.

### 1.1 Statistics by period

| Period | Assessed (Red, Amber or Normal) | Red | Amber – traffic | Amber – signal | Normal | Grey | Detector Health |
|---|---|---|---|---|---|---|---|
| AM peak | 1,224 (49 %) | 83 (6.8 %) | 508 (41.5 %) | 51 (4.2 %) | 582 (47.5 %) | 924 (37 %) | 353 (14 %) |
| Midday | 1,189 (48 %) | 114 (9.6 %) | 579 (48.7 %) | 61 (5.1 %) | 435 (36.6 %) | 923 (37 %) | 389 (16 %) |
| PM peak | 1,222 (49 %) | 83 (6.8 %) | 685 (56.1 %) | 53 (4.3 %) | 401 (32.8 %) | 967 (39 %) | 312 (12 %) |
| Weekend midday | 1,141 (46 %) | 89 (7.8 %) | 611 (53.5 %) | 43 (3.8 %) | 398 (34.9 %) | 879 (35 %) | 481 (19 %) |

Shares of Red, Amber and Normal are of the assessed sites; Grey and Detector Health are of all 2,501 sites.

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
| Assessed in all four periods | 1,044 – of which Red or Amber in all four: 203 (19 %) |

**Red in all four periods** – each shows the same phase-service change throughout:

| SCATS | Intersection | Finding repeated in every period |
|---|---|---|
| 3101 | Bluff Road / Highett Road | Highett Road [W] green share 22–31 % against a usual 34–37 %; longer cycle in three periods |
| 3191 | Clayton Road / Dunstan Street | Clayton Road [S] green share 63–70 % against a usual 29–34 % (three periods); poorer stability in all four |
| 4445 | Albert Street / Gisborne Street | Gisborne Street [S] green share 39–41 % against 45–47 % (three periods); poorer stability in all four |

These are better candidates for an operational or mapping change than any single-period Red.

## 2. TomTom coverage

**Network**: the validated TomTom mapping file covers 1,017 of 2,501 sites (41 %).

**Red sites**:

| Period | Red | TomTom junction data | Delay | Queue | Both |
|---|---|---|---|---|---|
| AM peak | 83 | 30 | 29 | 30 | 29 |
| Midday | 114 | 58 | 58 | 58 | 58 |
| PM peak | 83 | 40 | 36 | 40 | 36 |
| Weekend midday | 89 | 34 | 33 | 34 | 33 |
| **All** | **369** | **162 (44 %)** | **156** | **162** | **156** |

- Where a junction is mapped, the queue (Junction Analytics API) covers the full 30 minutes on every approach; the
  delay (InfluxDB) covers 15 of 30 minutes on 145 approaches and none on 123.

## 3. Distributions

### 3.1 Volume (approaches of the assessed sites)

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

Small approaches are flagged two to four times as often as large ones: a few vehicles move a small count past both
the percentile and the 10 % test.

**Change against the usual value, all assessed approaches**: median +2.0 % to +3.7 %, mean +3.4 % to +7.2 %, and
57–65 % of approaches above their usual value. The flagged approaches: median +12.5 % to +15.3 %, with 16–21 % more
than 25 % above usual and 5–9 % more than 25 % below.

### 3.2 Green share, cycle length and stability (assessed sites)

| | AM peak | Midday | PM peak | Weekend midday |
|---|---|---|---|---|
| Usual green share – median (25th–75th) | 66 % (45–90) | 65 % (45–91) | 64 % (45–90) | 64 % (46–91) |
| Flagged green change – median (10th / 90th) | −4.5 pp (−41 / +20) | −5.1 (−40 / +17) | −5.0 (−40 / +18) | +2.3 (−54 / +27) |
| Usual cycle length – median (10th / 90th) | 113 s (71 / 135) | 90 s (60 / 127) | 116 s (72 / 140) | 95 s (61 / 129) |
| Flagged cycle change – median | +13.9 % | +13.4 % | +13.8 % | +14.0 % |
| Usual Cycle Stability – median | 86 | 80 | 88 | 78 |
| Current stability when flagged – median | 66 | 57 | 74 | 54 |

### 3.3 TomTom (Red sites)

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
- **Minutes with speed** read 20 of 30 for 53 % of links, 25 for 24 % and 30 for 22 % (one record counted as
  5 minutes; the feed's interval is to be confirmed).

## 4. Diagnosis types

### 4.1 Types and counts

A Red site can show several patterns.

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
| A1 | Sound and the most useful: more green with less traffic (or the reverse) is not what demand-responsive control does, and it is put first. 3 of 91 such approach pairs rest on a usual volume below 20 veh/30 min, where the "opposite" may be noise. The LLM wording softened this explanation in 9 of 81 reports (e.g. "may be an adaptive response"). |
| A2 | Sound; stating both readings (SCATS follows demand, or the detectors count only what the green lets through) is correct for SCATS strategic detectors. |
| B1 | Sound as a possibility; a longer cycle with higher volume is the expected adaptive response. It is hedged ("may be"). |
| B2, B3 | Sound; a cycle change that volume does not explain points to the plan or coordination. |
| C | Reasonable but weak: "may follow demand on competing phases" is generic. 15 % of sites with a Q3C finding have two or more flagged approaches with identical values – approaches served by the same phases – so one phase change is reported as several findings (557 flagged approaches at Red sites are 496 distinct changes). |
| D | Reasonable; poorer stability is common (276 of 369) and its explanation is generic. |
| E | Correct and honest ("its cause is not shown by the SCATS data"). |

## 5. Suggested engineering checks

### 5.1 The checks and their frequency (369 Red reports)

| Check | Wording in the report | Written when | Reports |
|---|---|---|---|
| Phase service against demand | Verify phase service on X against its demand: green time and phase calls cycle by cycle with the detector counts | traffic and phase-service findings on the same approach (A1, A2) | 225 |
| Cycle change: adaptive or plan | Verify whether the longer/shorter cycle was SCATS's adaptive response or a plan or coordination change: plan, subsystem cycle length, linking and offsets | abnormal cycle length (B) | 145 |
| Phase service on other approaches | Check phase service to X: phase calls, skipped or extended phases, demand on the competing phases | phase-service finding without a traffic finding (C) | 332 |
| Cycle stability | Review cycle-by-cycle cycle lengths in Signal Performance to confirm the poorer stability | poorer stability (D) | 276 |
| Incidents and events | Check for incidents, events, roadworks or diversions that could explain the unusual volume on X, and monitor whether it persists | traffic finding without a phase-service finding (E) | 344 |

Checks per report: 2 (30), 3 (162), 4 (116), 5 (54), 6 (7).

### 5.2 Are the checks reasonable?

- Each check names the approach and the data to look at (Signal Performance, phase calls, detector counts, plan and
  linking), and stays within "review, verify, investigate". The order follows the strength of the evidence. The LLM
  keeps the checks: the same number in 368 of 369 reports, with no instruction to adjust or retime.
- **What is missing or could be better:**
  1. **Repeated checks.** The incidents-and-events check is written once per approach (up to four times in one report, e.g. SCATS 3072); one check
     naming the approaches would be clearer.
  2. **Mapping (usual green share of 100 % or usual value of 0).** Check the phase-to-approach (or link) assignment
     before any operational check.
  3. **Detectors.** When the site was screened with one failing detector tolerated, the report should say that the
     counted volume on that approach may be lower than the actual volume.
  4. **Persistence.** Add an analysis of whether the same finding recurs in other periods (e.g. SCATS 3101, 3191,
     4445); a recurring finding deserves more attention than a single one.
  5. **Low volume.** Below a certain volume a few vehicles make a large percentage change. The test could be relaxed
     for small approaches, for example by also requiring a minimum change in vehicles, or by judging the change against
     what is expected for a count of that size.

## 6. TomTom check (Q5) against the SCATS diagnosis

**Site verdict by primary type** (Red sites):

| Primary type | Agreement | Partial | Disagreement | Insufficient coverage | Unavailable |
|---|---|---|---|---|---|
| A1 (green opposite to volume) | 8 | 24 | 9 | 0 | 40 |
| A2 (green follows volume) | 6 | 29 | 7 | 1 | 55 |
| B1 (adaptive cycle) | 4 | 11 | 4 | 0 | 34 |
| B2, B3 (cycle not explained by volume) | 1 | 6 | 1 | 0 | 21 |
| C (phase service elsewhere) | 3 | 34 | 13 | 1 | 57 |

## 7. Overall assessment and improvements

### 7.1 Assessment

- The **classification** follows the methodology exactly; the **diagnoses** are factual, hedged and complete; the
  **checks** are appropriate review steps in a sensible order.
- The **weakest links** are the evidence behind the findings (small volumes, school holidays and missing days in the
  history) and the large share of generic C + D + E reports.

### 7.2 Method

1. **School holidays in the history.** If the reference weeks include school-holiday weeks, their lower traffic is not
   taken into account and the diagnosis may be less accurate (e.g. traffic reads higher than usual). Excluding
   school-holiday weeks from the reference weeks of weekday periods should be considered (public holidays are
   already excluded).
2. **Small volumes.** Q1 flags small approaches two to four times as often as large ones. Judge the change according
   to the volume, for example by also requiring a minimum change in vehicles, or by comparing the change with what is
   expected for a count of that size.
3. **History at its minimum.** Many values rest on the 5-week minimum; backfilling the missing reference days should be
   considered.
4. **Persistence.** Show how many of the recent periods a site was Red or Amber, and the repeated finding.

### 7.3 Data and mapping

1. Missing reference days network-wide.
2. Usual values of 0 and usual green shares of 100 % with Low findings: phase-to-approach and link assignment.

### 7.4 Wording and checks

1. Require the A1 explanation ("the opposite of a demand response") in the LLM answer, as the required labels are.
2. Merge the incident checks of one report into one check naming the approaches.
3. Group approaches with identical green-share values as one phase in the diagnosis and checks.
4. Add a mapping check for Low findings on usual-100 % approaches and usual values of 0.
5. Add to the wording that one failing detector was tolerated, so the counted volume on that approach may be lower
   than the actual volume.
