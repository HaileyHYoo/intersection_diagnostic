# `python main.py stats` – definitions of the checks

`stats` counts **every check on its own, for every site** (2,501 in Melbourne). The screening is sequential: Q1 and Q3 run only after a Q2 (detector) PASS, and any missing input makes the site Grey. Here no check depends on another. For example, "no current KPI value" also counts sites that failed Q2 and were classified Detector Health.

Common conventions:
- **Analysis period.** The same 30 minutes as the screening (e.g. Fri 15:00–15:30), made of two quarter-hours. **A current value exists only when both quarter-hours have a value**; if either is missing, it counts as missing.
- **Reference weeks.** As in the screening: the same weekday and 30 minutes in each of the previous 8 weeks, without excluded days such as public holidays (e.g. 7 weeks).
- **Short history.** Fewer than 5 reference weeks with a valid value (`history.min_observations`).
- **Evaluated approaches.**
  - Q1: EGRESS links that had a volume in at least one reference week.
  - Q3C: links that had a green share in at least one reference week.
- Every data column is **1 when the site has the problem, 0 otherwise**. A site can have several problems at once.

## 1. Data checks (1 = problem)

### Detectors (Q2 input: `scats/volume` fields `d[n]`, Neo4j `Detector`)

| Column | Definition |
|---|---|
| `no_active_detector` | No detector with `active = true` linked to the site by `BELONG_TO` in Neo4j |
| `detector_records_missing` | At least one active detector has a **60-minute count below 10** with some of its twelve 5-minute records missing or negative (Q2 result INSUFFICIENT DATA). A detector with records missing but a count of 10 or more passes and is not counted |
| `all_detector_records_missing` | The site has active detectors, but none has a valid 5-minute record in the 60 minutes |
| `detector_below_threshold` | At least one active detector has all twelve 5-minute records and a 60-minute count below 10 (Q2 result FAIL, i.e. Detector Health Issue) |

### Volume (Q1 input: `scats-aggregation/volume`, `DetectorGroupId` = EGRESS `link_id`)

| Column | Definition |
|---|---|
| `no_egress_link` | No `EGRESS` road with a `link_id` for the site in Neo4j |
| `link_without_volume_history` | At least one EGRESS link has no 30-minute volume in any reference week, so it is left out of Q1 |
| `link_without_current_volume` | At least one evaluated link has no volume in the analysis period (either quarter-hour missing) |
| `link_short_volume_history` | At least one evaluated link has a current volume but fewer than 5 reference weeks with a volume |

### Cycle KPIs (Q3A/Q3B input: `IntersectionPerfKpi`)

| Column | Definition |
|---|---|
| `no_current_cycle_length` | No `AvgCycle` in the analysis period (either quarter-hour missing) |
| `no_current_cycle_stability` | No `CycleStability` in the analysis period |
| `short_kpi_history` | Cycle length or Cycle Stability has a **current value** but fewer than 5 reference weeks with a value. A site without a current value is counted in the two columns above, not here |

### Phase service (Q3C input: `IntersectionPerfApproach` fields `GreenShare`, `HasGreen`)

| Column | Definition |
|---|---|
| `no_perf_approach_now` | No `IntersectionPerfApproach` record for any link of the site in the analysis period |
| `no_phase_service_history` | No link of the site had a valid green share (HasGreen = 1) in any reference week, so Q3C has no evaluated approach |
| `approach_hasgreen_0` | At least one evaluated approach has records in both quarter-hours but `HasGreen = 0` in at least one of them: a **recorded** "no green" |
| `approach_no_green_record` | At least one evaluated approach has no `GreenShare`/`HasGreen` record in at least one quarter-hour: **missing data** |
| `approach_short_green_history` | At least one evaluated approach has a current green share but fewer than 5 reference weeks with a green share |

### TomTom

| Column | Definition |
|---|---|
| `no_tomtom_mapping` | The site has no approach in the validated TomTom approach ↔ link mapping file. Q5 cannot run; the screening category is not affected |

**`sites_without_any_screening_data_problem`** is the number of sites with none of the 16 data problems above. The TomTom mapping is not counted.

## 2. Each question on its own (all sites)

Every question applied to every site, independently of the others, with the screening's rules (METHOD.md).

| Column | Values and definition |
|---|---|
| `q2` | PASS / FAIL / INSUFFICIENT DATA: the detector gate (see Detectors above) |
| `q1` | NORMAL / ABNORMAL / INSUFFICIENT DATA. ABNORMAL if any evaluated link is outside its 10th–90th percentile range **and** at least 10 % from its usual value; INSUFFICIENT DATA if none is abnormal but a link lacks a value or history |
| `q3a_cycle_length` | ABNORMAL if the cycle length is outside its range and at least 10 % from usual |
| `q3b_cycle_stability` | ABNORMAL if Cycle Stability is below its 10th percentile (only poorer stability) |
| `q3c_phase_service` | ABNORMAL if any evaluated approach's green share is outside its range; INSUFFICIENT DATA if none is abnormal but an approach lacks a value or history |
| `q3` | ABNORMAL if at least 2 of the 3 measures are abnormal; NORMAL if at least 2 can be assessed; otherwise INSUFFICIENT DATA |
| `category_without_q2_gate` | The category the site would have if Q2 had passed; all other rules apply as they are (e.g. an approach without green still makes the site Grey) |
| `category` | The actual screening category |

`abnormal_each_question_alone` and `normal_each_question_alone` count the sites that are ABNORMAL, or NORMAL, for each question.

## 3. Overlaps and combinations

- **`overlap_of_data_checks`** – the number of sites with **both** of two data problems (e.g. `no_current_cycle_length & detector_records_missing`). A site appears in every pair it belongs to.
- **`most_common_combinations`** – for each site, all of its data problems joined together, counted by combination (top 15). **Each site is counted once**, so the counts over all combinations add up to the number of sites. `(no data problem)` is a site with none of them.

## 4. Reading the results

- A site can have several problems, so the column counts add up to more than the number of sites.
- A recorded "no green" (`approach_hasgreen_0`) is a measured zero; a missing record (`approach_no_green_record`) is missing data.
- `stats` is analysis only: categories, logs and snapshots are not changed.
