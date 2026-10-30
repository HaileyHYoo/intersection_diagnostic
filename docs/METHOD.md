# Intersections Diagnostics V1 — how the code implements the methodology

Source methodology: *Intersections Diagnostics, V1 Screening and Diagnostic Methodology* (M. Sarvi, 29 Oct 2026).
The methodology is the guideline. This page lists what the code does, including the decisions agreed on top of the
methodology. Each decision is marked **(decision)** and is a switch or value in `diagnostics/config/rules.json`.

## 1. Two levels

| Level | When | Sites | Code | LLM |
|---|---|---|---|---|
| 1: Q2, then Q1 + Q3 | A screening request (layer activation or refresh) with no saved run | Whole network | `screening.py` | No |
| 2: D001 (Q4) + D002 (Q5) | A click on a Red site | One site | `templates/d001.py`, `templates/d002.py` | Wording only |

Classifications are made by deterministic code. The LLM never decides a category, writes a query or produces a number.

## 2. Time

- **Timestamps label the end of the interval (decision).** A 15-minute record stamped 01:15 covers 01:00–01:15. A 5-minute record stamped 01:05 covers 01:00–01:05.
- **Analysis period.** By default this is the latest completed 30 minutes. The period ends on a :00 or :30 boundary, `data_latency_minutes` (5) after real time. Any past period can also be selected.
- **Records used for the period.** The 30-minute period ending at T uses the 15-minute records stamped T−15 and T. The Q2 window uses the twelve 5-minute records stamped T−55 … T.
- **Time zones.** All data are stored in UTC. The region tag gives the local time zone (`rules.region_timezones`, e.g. `AU-VIC-Melbourne` → `Australia/Melbourne`), as in the chatbot.
  - Local time is used for inputs without an offset, 30-minute slots, weekdays, holidays and display.
  - Every query is sent in UTC.
- **Putting records on the grid (decision)** (`series.py`). Live feeds are written at a fixed offset from the grid (30 Oct 2026 inspection, site 4397): 5-minute detector counts at :03, :08 …, and `IntersectionPerfKpi` / `IntersectionPerfApproach` at :07, :22, :37, :52. Each record therefore goes to the interval its stamp falls in (`off_grid: "ceil"`):
  - 03:22:05 belongs to 03:15–03:30;
  - 03:28 belongs to 03:25–03:30;
  - so the 30 minutes ending 03:30 use the Q3 records 03:07 and 03:22, and Q2 uses the twelve detector records 02:33 … 03:28.
  - A stamp within `alignment.tolerance_seconds` (60 s) of a grid point is moved onto that point (a late write). If two records land on the same interval, the latest one is kept (`duplicates: "last"`).
  - A feed labelled at the interval start (`timestamp_label: "start"` in the schema) is shifted by one interval first.
  - The counts of moved, assigned and duplicate records are kept with every run.
- **Missing records.** A missing or non-numeric value is missing, never zero. A 30-minute value needs both 15-minute records, and the Q2 count needs all twelve 5-minute records.

## 3. History (baseline)

- **Reference periods.** The same weekday and the same 30-minute slot (local clock time) in each of the **8 weeks before the analysis day**. A day in May is compared with the 8 weeks before that day.
- **Excluded days (decision).** These days are left out of the history:
  - Victorian public holidays
  - The two daylight-saving change days
  - The year-end period, 24 Dec – 1 Jan

  The tables are in `vic_calendar.py` and cover 2024–2027. An excluded week is **not** replaced by an earlier week (`history.extend_beyond_weeks: false`).
- **Analysis day on an excluded day.** It is still screened, and the run carries a note.
- **Minimum history.** At least **5** valid observations. Otherwise the measure is INSUFFICIENT DATA for that entity.
- **Normal range and usual value.** The normal range is the **10th–90th percentile** (linear interpolation). The usual (reference) value is the **median** of the observations, as in the production contract (`reference_value`; `"mean"` is also supported).
- **Caching.** Values per reference period are cached (`slot_values`), so a reference day fetched once serves every later analysis day that uses it.
  - The weekly job (`python main.py baseline`) precomputes every slot of the coming days.
  - An on-demand request reads only the 8 reference periods it needs.
  - The baseline version combines the schema version with the history, percentile and alignment rules. If any of these change, the baselines and runs are recomputed.

## 4. Q2: Detector health gate

- **Detectors.** Neo4j `(Detector)-[:BELONG_TO]->(Intersection)` with `active = true` only **(decision)**.
- **Counts.** The raw counts in `scats/volume`, field `d[n]`, where n = `detector_number`. Each detector's count is the sum of its 5-minute records in the 60 minutes ending with the period (twelve when complete).
- **Negative counts (decision).** A negative 5-minute count is not a valid count: it is treated as a missing record (`q2.negative_counts: "missing"`), following the methodology's rule that missing records are not measured zeros. So 19 and −10 give 19 from the valid records, not 9; whether the detector passes then follows the rules below.
- **Each detector is judged on its own**; counts are never added across detectors.

| Detector result | When |
|---|---|
| PASS | Its count is at least 10 (`q2.min_vehicles`), **even if some 5-minute records are missing** — the missing ones could only add to it |
| FAIL | Its count is below 10 and all twelve records are present |
| INSUFFICIENT | Its count is below 10 and records are missing or negative (a missing record is not a zero), or it has no valid records |

| Site result | When |
|---|---|
| FAIL → Detector Health Issue | Any active detector FAILs. An observed low count takes precedence over insufficient detectors elsewhere. |
| INSUFFICIENT → Grey | No detector FAILs, but at least one is INSUFFICIENT, or the site has no active detector |
| PASS | Every active detector PASSes |

Q1 and Q3 run only after a PASS.

## 5. Q1: Traffic abnormality

- **Volume.** The existing 15-minute link volumes (`scats-aggregation/volume`, `DetectorGroupId` = Neo4j `Road.link_id`). The current value is the sum of the two quarter-hours.
- **Approaches.** The site's Neo4j `EGRESS` links.
- **Evaluated approaches (decision).** EGRESS links that had volume in the reference weeks (`q1.approach_history_min_presence`: 1). Links that never had data are listed as not evaluated.
- **Abnormal approach.** The current value is outside the 10th–90th range **and** differs from the usual value by at least 10%.
- **Result.**
  - **Any evaluated approach without a complete current value, or with fewer than 5 historical values, makes Q1 INSUFFICIENT and the site Grey (decision,** `q1.grey_if_any_approach_missing`**).**
  - Otherwise Q1 is ABNORMAL if any approach is abnormal, and NORMAL if none is.

## 6. Q3: Signal-operation abnormality

| Measure | Source | Rule |
|---|---|---|
| Q3A Cycle length | `IntersectionPerfKpi.AvgCycle`, mean of the two quarter-hours | Outside the 10th–90th range and ≥10% from usual |
| Q3B Cycle stability | `IntersectionPerfKpi.CycleStability`, mean of the two quarter-hours | Only poorer stability: **below the 10th percentile (higher = more stable; confirmed from the data: stability falls as CycleCvPct rises)** |
| Q3C Phase service by approach | `IntersectionPerfApproach.GreenShare` (%) per `LinkId`, mean of the two quarter-hours **(decision)** | Below the 10th percentile = LOW, above the 90th = HIGH; no percentage threshold |

- **Q3C evaluated approaches.** The site's links that had green in the reference weeks.
- **Approach without green.** `HasGreen = 0`, or no GreenShare/HasGreen record, in either quarter-hour. **Any evaluated approach without green makes the whole site Grey (decision,** `q3c.grey_site_if_any_approach_without_green`**, strictest setting).**
- **Q3C component result.** ABNORMAL if any approach is abnormal. INSUFFICIENT if any evaluated approach lacks a value or history.
- **Q3 overall.** ABNORMAL if at least 2 of the 3 measures are ABNORMAL. Otherwise NORMAL if at least 2 measures can be assessed. Otherwise INSUFFICIENT DATA.
- **Fallbacks.** The subsystem `ActiveCycleLength` fallback for Q3A is kept in code but switched off (`fallbacks.enabled: false`).

DemandShare, SignedGap, DemandPressure, GreenGapBusiest, RiskBusiest and the other KPIs are **not** used for screening.

## 7. Classification

| Q2 | Q1 | Q3 | Category |
|---|---|---|---|
| FAIL | – | – | Detector Health Issue |
| INSUFFICIENT | – | – | Grey |
| PASS | any | any, with an evaluated approach without green | Grey |
| PASS | INSUFFICIENT | any | Grey |
| PASS | any | INSUFFICIENT | Grey |
| PASS | NORMAL | NORMAL | Normal |
| PASS | ABNORMAL | NORMAL | Amber – Traffic Abnormality |
| PASS | NORMAL | ABNORMAL | Amber – Signal-Operation Abnormality |
| PASS | ABNORMAL | ABNORMAL | Red – Needs Attention |

Every category is returned to the host, and the UI decides what to draw. A click runs `rules.click[category]`:
- Red runs D001 + D002.
- Every other category shows the saved evidence (no LLM). This can be extended in the rules file.

## 8. D001 (Q4): SCATS diagnostic interpretation

- **Inputs.** The saved Q1/Q3 results of the run only. No data is retrieved.
- **Code-written answer.** Code writes a complete answer: diagnosis, supporting evidence and suggested checks.
  - Findings on the same approach are connected.
  - Findings on different approaches are reported separately.
  - The answer states that association is not causation.
- **LLM wording.** The LLM may re-word that answer. The re-worded answer is used only when all three hold:
  - It is the requested JSON.
  - Every number in it appears in the evidence.
  - It makes no forbidden claim (fault, "caused by", timing changes).

  Otherwise the code-written answer is used and the rejection is recorded.

## 9. D002 (Q5): TomTom road-user confirmation

- **Data and period.** TomTom KPIs stored in InfluxDB (`IntersectionTurnKpi`, `IntersectionKpi`) for the same 30-minute period.
- **Queue length.** The methodology (section 13) asks for approach queue length and the largest queue, from the timestamped TomTom Junction Analytics queue history. That history is only available from the Junction Analytics API (archive), not from InfluxDB.
  - The archive reader is implemented (`sources/tomtom_queue.py`), using the same endpoint and parsing as the chatbot's TomTom layer.
  - It is **on by default**, as the methodology requires (`tomtom.api_enabled`), and needs `TOMTOM_API_KEY`.
  - Without a key, when the call fails, or for a site without a TomTom junction, the queue is reported as unavailable with the reason, never estimated. "Has the largest queue" is then unknown (None), not "no". The rest of Q5 and Q4 still run.
- **Metrics per approach.**
  - Approach delay: mean `ApproachDelaySec`
  - Control delay and multi-stop rate: weighted by `SampleCount`
  - Movements: named left / through / right / u_turn from the mapping's travel directions (Melbourne drives on the left)
  - Queue: mean and maximum of the per-minute queue in the period
  - An approach's delay is *adequately observed* when it has records in both quarter-hours, and its queue when at least `tomtom.queue_min_minutes` (15) minutes have a value. Only adequately observed approaches are ranked.
- **Matching.** TomTom approaches are matched to EGRESS links with the chatbot's verified mapping file (`data/tomtom_neo4j_links_AU-VIC-Melbourne_final.json`), which also gives the junction UUID for the queue archive.
- **Agreement per SCATS-identified approach (decided by code).**

  | Result | When |
  |---|---|
  | agreement | The approach has the greatest delay or the longest queue |
  | disagreement | The approach is observed, but neither is on it |
  | insufficient coverage | The approach is not adequately observed |

  Overall, the site agrees if any flagged approach agrees, and disagrees if any is observed without agreeing. Partial coverage and unmapped approaches are stated.
- **No data.** The answer is "TomTom confirmation unavailable for this intersection or analysis period." D001 still runs.

## 10. Report, storage and audit

The report has four fixed sections: Diagnosis, Supporting Evidence, TomTom Road-User Impact and Suggested Engineering Checks.

The SQLite store (`store.py`) keeps:
- reference values and baselines;
- screening runs, keyed by region, period, baseline version and rules version, with the complete per-site evidence and alignment counts;
- diagnoses, with template ID and version, the evidence, the answer, who wrote it (code or LLM) and any rejection.

A run that is already in progress is waited for, not started a second time.

A site that fails to process is recorded in the run's `errors` (site → reason) and does not stop the network screening. Each site also carries `total_volume_veh_h`: the evaluated approaches' 30-minute volume as an hourly rate, or None unless every evaluated approach has a value.

## 11. Production contract

The production team's service contract (`intersections_diagnostics_schemas.py`, Pydantic) is copied unchanged into `diagnostics/contract/`. The Dash callbacks keep the shared run store; the core functions only compute:

- `contract.core.run_screening(ScreeningInput) -> ScreeningResult`. The input's `ScreeningConfig` thresholds override rules.json, and every other rule comes from rules.json. If the input lists sites (with detector IDs and approaches), only those are screened.
- `contract.core.run_diagnosis(DiagnosisInput) -> DiagnosisResult`. Only Red sites are accepted. D001/D002 run on the saved evidence, unchanged.

`contract/adapter.py` converts between our records and the contract:
- statuses are lower case; percentiles are 10/90;
- `approach_id` = EGRESS `link_id`, and `detector_id` = n of `d[n]`;
- coordinates are (lon, lat);
- `count_60min` is rounded to an integer (the Q2 gate itself uses the unrounded total);
- Q4 evidence is a list of `EvidenceItem` (statement written by code, values copied);
- template IDs come from `rules.contract.template_ids`, or from the input's `TemplateRef`.

Two agreed behaviours need contract changes that were asked of the production team. The adapter uses them as soon as the contract has them:

- **Grey for an approach without green.** This needs `Q3CPhaseService.site_grey_no_green` and the matching rule in `classify_site()`. Until then, such a site is reported in `ScreeningResult.errors`, not dropped silently.
- **Unknown queue.** This needs `ScatsComparison.has_largest_queue: bool | None`. Until then, False is written.


## 12. Open items

- **Confirm on live data** with `python main.py inspect` (see SCHEMA.md):
  - that `d[n]` numbering equals `Detector.detector_number`;
  - the `scats/volume` value types;
  - end labelling of the 5-minute data;
  - the pattern of off-grid stamps (e.g. 01:10, 04:22:05).
- **Asked of the production team (contract):**
  1. `site_grey_no_green` on `Q3CPhaseService` and in `classify_site()`;
  2. where the 8-week baselines are stored, who runs the weekly refresh, and the `baseline_version` of a past period;
  3. the time zone of periods, and a UTC cache key (today the same instant gives two keys);
  4. a config/rules hash in the cache key;
  5. `has_largest_queue: bool | None`.
- **Template IDs.** D002's registry ID (`ID_Q5_TOMTOM_CONFIRMATION`) is a placeholder until confirmed.
- **Outside this repository:** the chatbot's `tomtom/engine.py::scats_volume_hours()` groups 15-minute records by their stamp's clock hour. With end labelling, this shifts every hour by 15 minutes (00:45–01:45 instead of 01:00–02:00). It should be fixed in the Chatbot repository.
