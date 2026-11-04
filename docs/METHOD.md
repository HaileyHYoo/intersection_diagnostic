# Intersections Diagnostics V1 — how the code implements the methodology

Source methodology: *Intersections Diagnostics, V1 Screening and Diagnostic Methodology* (M. Sarvi, 29 Oct 2026), with the updates on historical records (§18) and supplementary link speed (version "Speed added", 2 Nov 2026).
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
- **Analysis period.** The latest completed 30-minute period. Periods are the day's 48 clock slots (:00–:30, :30–:00), as the methodology's 30-minute time slots, the contract's `slot_index` (0–47) and "refreshed when a new completed 30-minute period becomes available" imply. The "latest two completed 15-minute intervals" of Q1 are the two quarters of that slot.
  - A period is used `data_latency_minutes` (5) after it ends, so at 16:19 the period is 15:30–16:00, and from 16:35 it is 16:00–16:30.
  - The Q2 window is the 60 minutes ending with the period (15:00–16:00 for that example).
  - The history is the same slot on the same weekday in the 8 previous weeks (15:30–16:00 on the eight previous Fridays).
  - Any past period can also be selected.
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

  The tables are in `vic_calendar.py` and cover 2024–2027. An excluded week is **not** replaced by an earlier week (`history.extend_beyond_weeks: false`). The same holds for a reference week whose data are missing: it is not replaced, so a period with fewer than 5 valid weeks is not assessable (**decision with the methodology owner, 3 Nov 2026**: keep as written).
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
- **Result (methodology 4: "If any approach satisfies the abnormality criterion, Q1 = ABNORMAL; otherwise Q1 = NORMAL, provided there is enough data").**
  - Q1 is ABNORMAL if any evaluated approach is abnormal, **even when another approach cannot be assessed** — an observed abnormality decides; a missing approach can only withhold NORMAL. (Corrected 3 Nov 2026 after the methodology owner's review; before, a missing approach made Q1 INSUFFICIENT first.)
  - Otherwise, **any evaluated approach without a complete current value, or with fewer than 5 historical values, makes Q1 INSUFFICIENT and the site Grey (decision,** `q1.grey_if_any_approach_missing`**).**
  - Otherwise Q1 is NORMAL.

## 6. Q3: Signal-operation abnormality

| Measure | Source | Rule |
|---|---|---|
| Q3A Cycle length | `IntersectionPerfKpi.AvgCycle`, mean of the two quarter-hours | Outside the 10th–90th range and ≥10% from usual |
| Q3B Cycle stability | `IntersectionPerfKpi.CycleStability`, mean of the two quarter-hours | Only poorer stability: **below the 10th percentile (higher = more stable; confirmed from the data: stability falls as CycleCvPct rises)** |
| Q3C Phase service by approach | `IntersectionPerfApproach.GreenShare` (%) per `LinkId`, mean of the two quarter-hours **(decision)** | Below the 10th percentile = LOW, above the 90th = HIGH; no percentage threshold |

- **Q3C evaluated approaches.** The site's links that had green in the reference weeks.
- **Approach without green.** `HasGreen = 0`, or no GreenShare/HasGreen record, in either quarter-hour. **Any evaluated approach without green makes the whole site Grey (decision,** `q3c.grey_site_if_any_approach_without_green`**, strictest setting).**
- **Q3C component result (methodology 8: "an abnormal phase-service finding means at least one evaluated approach is abnormal").** ABNORMAL if any approach is abnormal, **even when another approach lacks a value or history**; otherwise INSUFFICIENT if any evaluated approach lacks a value or history; otherwise NORMAL. (Corrected 3 Nov 2026: SCATS 976 on 30 Oct 15:00 had one approach outside its range and another with too little history, and was shown Amber instead of Red.) A no-green approach still makes the site Grey through the site-level rule above.
- **Q3 overall.** ABNORMAL if at least 2 of the 3 measures are ABNORMAL. Otherwise NORMAL if at least 2 measures can be assessed. Otherwise INSUFFICIENT DATA.
- **One abnormal, one normal, one not assessable.** The document's rule gives NORMAL, although the missing measure, if it were abnormal, would have made Q3 ABNORMAL. The code follows the document and marks such a site with `q3.missing_measure_could_change = true`; `python main.py summary` counts them. **Decision with the methodology owner (3 Nov 2026): keep the rule as written and show it.** The category stays as the document gives it; the site's evidence, the map tooltip and the contract's `notes` say which measure could not be assessed and what the category would have been had it been abnormal (`screening.caution_notes`). The switch `q3.undetermined_if_missing_could_change` (default `false`) would make these sites Grey instead; it is not used.
- **Fallbacks.** Only the calculated KPIs are used. The `IntersectionPerfKpi` / `IntersectionPerfApproach` KPIs exist for part of the network only (the chatbot falls back to `subsystem_status` for cycle length and saturation). The subsystem `ActiveCycleLength` fallback for Q3A is kept in code but switched off (`fallbacks.enabled: false`). It would not change the result for a site without KPIs: Q3B and Q3C have no fallback, so only one measure could be assessed and Q3 would still be INSUFFICIENT DATA (Grey).

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
- **Code-written answer (revised after the methodology owner's review, 3 Nov 2026).** Code writes a complete answer; each part has one job, so the parts do not repeat each other:
  - **Diagnosis** — the main problem and the approaches concerned, without figures: *what the data show* (which approaches' traffic differs, and which signal measures differ and in which direction), then *possible explanations, labelled as not demonstrated by the data*. It states that SCATS adapts cycle length and phase service to demand and coordination, so a value outside its range does not by itself show a signal problem. The possible explanations come only from combinations of the Q1/Q3 findings:

    | Finding | Possible explanation written |
    |---|---|
    | Longer (shorter) cycle with higher (lower) volume on an approach | may be SCATS lengthening (shortening) the cycle as demand rose (fell) |
    | Cycle change without a matching volume change | a plan or coordination change is a possible explanation |
    | More (less) green to an approach whose volume is higher (lower) | may be SCATS following its demand, or the counted volume may follow the green given (detectors count the vehicles served) |
    | Less green to an approach whose volume is higher (or the reverse) | the opposite of a demand response, the finding most worth verifying |
    | Phase-service change on an approach without a volume change | may follow demand on competing phases or the coordination plan |
    | Poorer stability | the cycle varied more than usual, which can happen while SCATS adapts |
    | Volume change without a phase-service finding on that approach | its cause is not shown by the SCATS data |
  - Findings on the same approach are connected (an association, not proof of cause); findings on different approaches are reported separately.
  - **Supporting Evidence** — the measurements behind the findings (current, usual, range, difference). A measure that is simply normal is left to the tables.
  - **Suggested Engineering Checks** — numbered in order of priority, verifying signal behaviour, phase service and coordination: (1) phase service against demand on an approach with both findings, the opposite-direction case first; (2) whether a cycle change was adaptive or a plan / coordination change (plan, subsystem cycle, linking and offsets); (3) phase service on approaches without a traffic finding; (4) cycle-by-cycle stability; (5) incidents, events or diversions for a volume change without a signal finding.
- **LLM wording.** The LLM may re-word that answer. The re-worded answer is used only when all three hold:
  - It is the requested JSON.
  - Every number in it appears in the evidence.
  - It makes no forbidden claim (fault, "caused by", timing changes).
  - Every link ID it writes is one in the evidence (an LLM once merged two IDs into "WILLH6X4J54XJ642", SCATS 4566).
  - For D002, it keeps the code's verdict as "Overall: <verdict>" and every SCATS-identified approach.

  Otherwise the code-written answer is used and the rejection is recorded.

## 9. D002 (Q5): TomTom road-user confirmation

- **Data and period.** TomTom KPIs stored in InfluxDB (`IntersectionTurnKpi`, `IntersectionKpi`) for the same 30-minute period.
- **Queue length.** The methodology (section 13) asks for approach queue length and the largest queue, from the timestamped TomTom Junction Analytics queue history. That history is only available from the Junction Analytics API (archive), not from InfluxDB.
  - The archive reader is implemented (`sources/tomtom_queue.py`), using the same endpoint and parsing as the chatbot's TomTom layer. As there, a period is split at now − 24 h: the recent part uses the recent (live) archive, the older part the historical archive, with the same settings (`TOMTOM_QUEUE_HISTORIC_PARAMS`, `TOMTOM_QUEUE_RECENT_PARAMS`, URL templates). A period older than 24 h needs the historical settings of the account.
  - It is **on by default**, as the methodology requires (`tomtom.api_enabled`), and needs `TOMTOM_API_KEY`.
  - Without a key, when the call fails, or for a site without a TomTom junction, the queue is reported as unavailable with the reason, never estimated. "Has the largest queue" is then unknown (None), not "no". The rest of Q5 and Q4 still run.
- **Metrics per approach.**
  - **Both delays are ranked (decision with the methodology owner, 3 Nov 2026,** `tomtom.ranked_delays`**).** The greatest control delay and the greatest approach delay are found separately among the adequately observed approaches, and both are reported. A SCATS-identified approach agrees when it has the greatest of either delay or the longest queue. The contract has one largest-delay field (`largest_delay_approach_id`, `ScatsComparison.has_largest_delay`): it carries control delay (`tomtom.delay_metric`) and "has the greatest of either delay"; both rankings are in the answer text and the audit record.
  - Control delay is `ControlDelaySec` of `IntersectionTurnKpi`: per approach and per movement, the plain mean of the stored 15-minute turn records. This is the same calculation as the chatbot's `tomtom/los.py`, which the methodology asks Q5 to reuse (`tomtom.delay_mean: "plain"`; `"sample_weighted"` weights by `SampleCount`).
  - Approach delay: mean `ApproachDelaySec` per approach. Each delay is adequately observed when it has records in both quarter-hours.
  - A negative delay (faster than free flow) counts as 0, as in the chatbot's `delay_policy.py` (`tomtom.negative_delay`).
  - Multi-stop rate: weighted by `SampleCount`
  - Contract: `TomTomApproachMetrics.delay_s` is the ranked delay (control delay); `control_delay_s` is also filled.
  - Movements: named left / through / right / u_turn from the mapping's travel directions (Melbourne drives on the left)
  - Queue: mean and maximum of the per-minute queue in the period
  - An approach's delay is *adequately observed* when it has records in both quarter-hours, and its queue when at least `tomtom.queue_min_minutes` (15) minutes have a value. Only adequately observed approaches are ranked.
- **Matching.** TomTom approaches are matched to EGRESS links with the chatbot's verified mapping file (`data/tomtom_neo4j_links_AU-VIC-Melbourne_final.json`), which also gives the junction UUID for the queue archive.
  - **Stub links (decision, 3 Nov 2026).** For about 11 % of approaches the mapping gives the link upstream of a short stub (`stub_hops` > 0), not the site's EGRESS link itself. Such a TomTom approach is the site's approach on the same street when exactly one approach of the site on that street has no other TomTom approach; otherwise it stays unmatched. Each such match is stated in the coverage note with the mapping's link (seen live at sites 719 and 5266).
- **Answer text (code-written).** Where the greatest delay and the longest queue are; then one sentence per SCATS-identified approach (Q1 and Q3C findings) saying whether it has the greatest delay, the longest queue, neither, or no adequate coverage; then the overall verdict with the approaches that match and those that differ; then the coverage statement — whether delay and queue are available for the full 30 minutes, or per SCATS-identified approach how many of the two 15-minute periods have delay and how many of the 30 minutes have queue. A mismatch is always stated, as methodology §13 requires. TomTom shows a road-user impact, never its cause.
- **Agreement per SCATS-identified approach (decided by code).**

  | Result | When |
  |---|---|
  | agreement | The approach has the greatest control delay, the greatest approach delay or the longest queue |
  | disagreement | The approach is observed, but none of them is on it |
  | insufficient coverage | The approach is not adequately observed |

- **Site verdict (methodology owner's review, 3 Nov 2026).** Four values, in the answer text:

  | Site verdict | When |
  |---|---|
  | agreement | Every SCATS-identified approach agrees |
  | partial agreement | At least one agrees and at least one disagrees or is not covered |
  | disagreement | None agrees and at least one is observed |
  | insufficient coverage | No SCATS-identified approach is adequately observed |

  The contract's per-approach `ScatsAgreement` keeps its three values; "partial agreement" exists only at site level (the contract has no site-level field, so it is in `Q5Output.narrative`). Partial coverage and unmapped approaches are stated.
- **Section 3 layout.** The Junction Analytics part (delay, queue, the verdict) comes first. When it is unavailable, the methodology's fixed message is shown and the link speed does not replace it. The supplementary link speed follows under its own heading, as a separate TomTom source.
- **No data.** The answer is "TomTom confirmation unavailable for this intersection or analysis period." D001 still runs.

### 9.1 Supplementary TomTom link speed (methodology update, 2 Nov 2026)

| | |
|---|---|
| **When** | Clicking an **Amber** site (traffic or signal) or a **Red** site (`link_speed.categories`). Normal, Grey and Detector Health clicks do not read it. |
| **Links** | The site's incoming links: the Neo4j EGRESS links of the screening (evaluated and not evaluated) |
| **Source** | InfluxDB `aimes` / `speed`, field `Speed` (km/h), `DetectorGroupId` = `link_id`, `Provider = TomTom`, Region tag. This is the chatbot's link-speed feed (`road_closure_analysis/closure_did.py`). It is independent of Junction Analytics. |
| **Value** | Harmonic mean of the positive samples in the same 30-minute period, [start, end), as the chatbot reads link speed (`binned_query`, `how="pace"`). A 0 km/h sample is not used. |
| **Reference speed (decision, 4 Nov 2026)** | Read from the same feed (`aimes/speed`) on the click: the speed of the same 30 minutes in the screening's reference weeks (same weekday and slot, holidays left out), one harmonic mean per week, and their median (`reference_value`, as Q1/Q3), shown when at least `history.min_observations` (5) weeks have samples, with the number of weeks. This is the contract's `LinkSpeed.reference_speed_kmh` ("historical average for the same weekday and time of day"). It is read only for the selected site, never stored, and there is no network-wide speed baseline (`link_speed.reference_from_history`; a separately configured series, `link_speed_reference`, takes precedence when enabled). |
| **Arm** | The link's intersection arm from the production backend's SCATS operational sheet (`arms.py`), reusing its own modules (`OperationalSheetClient`, `operational_sheet.build_sheet`, `LINK_CYPHER`) as its TomTom layer does: a link's lowest-position active detectors name the arm through the sheet's DetectorNo → ArmNo. A split or unmatched link has no arm. Only in the production backend; locally the arm is empty. |
| **Amber** | Shown with the saved Q1/Q3 evidence. Q4/Q5 are not run. |
| **Red** | A table in report section 3, beside the TomTom delay and queue. It is not part of D002, its LLM input or its agreement. It is kept in the diagnosis record (18.2). |
| **Missing** | A link without samples shows "unavailable"; a feed that cannot be read gives a note with the reason. Nothing else changes. |
| **Never** | Used for Q1, Q2, Q3, the Q5 agreement or the category. No network-wide speed screening. |

## 10. Report, storage and audit

The report has four fixed sections: Diagnosis, Supporting Evidence, TomTom Road-User Impact and Suggested Engineering Checks.

The SQLite store (`store.py`) keeps:
- reference values and baselines;
- screening runs, keyed by region, period, baseline version and rules version, with the complete per-site evidence and alignment counts;
- diagnoses, with template ID and version, the evidence, the answer, who wrote it (code or LLM) and any rejection.

A run that is already in progress is waited for, not started a second time.

Methodology item 18 (record what is needed to reproduce a result) is covered by:
- **Configuration snapshots** (`configs` table): the full rules and schema stored once per `rules_version`. Every run and diagnosis carries `config_version`, so its thresholds can be read back even after rules.json changes.
- **Data provenance**: every run and diagnosis carries `provenance`, the list of reads it made (source, measurement, sites, time range, record count).
- **Registry template IDs**: each diagnosis template records both our ID (D001/D002) and its version, and the production registry ID from `rules.contract.template_ids` (or from the host's `TemplateRef`).

### 10.1 Historical records (methodology 18.3–18.6, updated document)

Two separate datasets, never overwritten, kept apart from the current results in SQLite (`archive.py`). The location is `DIAGNOSTICS_ARCHIVE`: an S3 URL (`s3://bucket/prefix`, as the document asks) or a local folder (default `archive/` next to the SQLite file).

| Record | Key | Written |
|---|---|---|
| Screening JSON log (18.3) | `screening-logs/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}.json` | Once per completed run, automatically, on both the service and contract paths. A cached run viewed by more users writes nothing new (18.5). |
| Baseline snapshot (18.4) | `baselines/{region}/{baseline_version}/{weekday}/{HHMM}.json.gz` | By the weekly job for every slot, and by any screening whose slot is not yet in the snapshot |

- **Log content.** Metadata (run ID, start and completion times, region, period, completion status, baseline version and snapshot key, reference periods and skipped days, rules/schema/config versions). Then every site with its category, Normal included. Then Detector Health issues: failed detector IDs, their 60-minute counts and the threshold applied. Then traffic abnormalities (flagged approaches with current, usual, range and % difference), signal abnormalities (Q3A, Q3B and the flagged Q3C approaches) and Grey sites with their reasons. Then the summary counts, and the complete Q2/Q1/Q3 evidence of every site.
- **Baseline version (decision).** `"{ISO week of the analysis day}.{method version}"`, e.g. `2026-W44.v1.1-88ffd9d604`. A period is compared with the 8 same-weekday periods before its own date. So every analysis day of a week uses that week's baseline, which is what a weekly refresh gives. The method version changes with any rule or schema change that affects baselines, so a new snapshot is written and old ones stay as they were.
- **Snapshot content.** Per site: Q3A and Q3B usual value, 10th–90th range and observation count. Per approach (EGRESS link): the same for Q1 volume and Q3C green share. It also holds the weekday, slot, reference periods, skipped days and calculation time. No raw history values, as the document allows.
- **Storage failure.** If the archive cannot be written, the run still completes and is shown. The failure is recorded (`audits`, kind `archive_failed`), and `python main.py archive --run ID` writes the log later. An existing log is never replaced.
- **Later analysis (18.6).** `archive.site_history()` / `python main.py site-history` counts a site's categories over the periods that were actually screened. A period without a run is counted as nothing, not as Normal. When one period has several runs (e.g. after a rule change), the latest counts.
- **Scheduled screening (later extension, not V1).** `schedule.run_scheduled` (`python main.py watch`) screens each period when its data is complete (period end + 5 min). `schedule.backfill` (`python main.py backfill`) screens past periods. Both use the normal `screen()`, so periods already screened are reused, and every run writes its own log. Nothing runs on a timer unless one of these is started (or an OS scheduler calls `python main.py screen`).

A site that fails to process is recorded in the run's `errors` (site → reason) and does not stop the network screening. Each site also carries `total_volume_veh_h`: the evaluated approaches' 30-minute volume as an hourly rate, or None unless every evaluated approach has a value.

## 11. Production contract

The production team's service contract (`intersections_diagnostics_schemas.py`, Pydantic, version "speed added, Nov 2026") is copied unchanged into `diagnostics/contract/`. The Dash callbacks keep the shared run store (Redis) and the S3 records; the core functions compute:

| Function | Contract models | What it does |
|---|---|---|
| `core.run_screening` | `ScreeningInput` → `ScreeningResult` | Level 1. The input's `ScreeningConfig` overrides rules.json; every other rule comes from rules.json. With an archive, it also writes this slot's `BaselineSnapshot` (18.4) under the input's `baseline_version`. |
| `core.run_site_report` | `SiteReportRequest` + saved `ScreeningRun` → `SiteReport` | An Amber or Red click. The evidence and period come from the run. Amber: evidence + `LinkSpeedReport`. Red: also Q4/Q5 (`run_diagnosis`), and with an archive the `SiteReport` is kept as the 18.2 record. Other categories are rejected. |
| `core.run_diagnosis` | `DiagnosisInput` → `DiagnosisResult` | Q4/Q5 for a Red site, on the saved evidence, unchanged |
| `core.run_link_speed` | `SiteScreeningResult`, `AnalysisPeriod` → `LinkSpeedReport` | Supplementary link speed alone (`run_site_report` includes it) |
| `core.write_screening_log` | completed `ScreeningRun` → `ScreeningLog` | The 18.3 log, written once per run, never overwritten |

`contract/adapter.py` converts between our records and the contract:
- statuses are lower case; percentiles are 10/90;
- `approach_id` = EGRESS `link_id`, `approach_name` = "Street [bound]", and `detector_id` = n of `d[n]`;
- coordinates are (lon, lat);
- `count_60min` is rounded to an integer (the Q2 gate itself uses the unrounded total); it is None for a detector that could not be evaluated, as the contract says;
- **Grey sites** carry their reasons in `insufficient_data_reason` (required by the contract); other caveats are in `notes`;
- **no green**: `Q3CPhaseService.site_grey_no_green = true`, which the contract's `classify_site()` makes Grey;
- **unknown queue**: `ScatsComparison.has_largest_queue = None`;
- Q4 evidence is a list of `EvidenceItem` (statement written by code, values copied);
- template IDs come from `rules.contract.template_ids`, or from the input's `TemplateRef`;
- **link speed**: `LinkSpeed.arm` comes from the production operational sheet (§9.1); `LINK_SPEED_UNAVAILABLE_MESSAGE` heads the notes when no link has a speed; the reference-speed status is the last note;
- **baseline snapshot**: one `BaselineSnapshot` per weekday and slot (§10.1), metrics `q1_volume`, `q3a_cycle_length_s`, `q3b_cycle_stability`, `q3c_phase_service`.

`python main.py contract-check` passes every site of a stored run through the contract's models and validators (decision matrix, 2-of-3 rule, Grey reason) and prints any site that does not fit.

**Audit on the contract path.** The contract has no place for the configuration, provenance, who wrote a template answer, or a rejected LLM answer. `run_screening` and `run_diagnosis` therefore accept an `audit_store`. When one is given, they save an audit record (`audits` table: kind `screening`/`diagnosis`, keyed by run or diagnosis ID) that holds the config snapshot reference, provenance, alignment counts, registry template IDs, `generated_by` and any LLM rejection. The production `host.py` passes a SQLite store.

The following optional contract fields have been proposed and are not in the Nov 2026 contract. `adapter.optional()` fills each one only when the contract has it, so no code change is needed if they are added:
- `Q4Output.generated_by`, `Q4Output.llm_rejected`, `Q5Output.generated_by`, `Q5Output.llm_rejected`;
- `ScreeningResult.config_version`, `ScreeningResult.audit_ref`, `DiagnosisResult.config_version`, `DiagnosisResult.audit_ref`.


## 10a. Report layout (methodology owner's review, 3 Nov 2026)

- **Labelled lines.** The diagnosis has two lines, "What the data show:" and "Possible explanations (not demonstrated by these data):"; the TomTom part has "Largest values:", "By approach:", "Overall:" and "Coverage:". An LLM re-wording must keep the labels (`layout.py`; checked as required wording) and the line breaks are restored if it runs them together.
- **Supporting Evidence on screen** is one line saying what is outside its range, plus notes the tables cannot show (a measure outside its range but normal, a measure not assessed). The rows outside their range are in bold in the tables, which hold every measurement. The D001 sentences are kept in the answer, and the contract's `supporting_evidence` is unchanged (`evidence_items`).
- **Detail.** The TomTom movements table is folded (click to show) in the HTML views.

## 11a. Names of approaches

An approach is shown as "Street [bound]". The street comes from the site's Neo4j EGRESS road (`street_name`, else `name`); for a link without one — an EGRESS road without a name, or a Q3C `LinkId` that is not one of the site's EGRESS links — from any Neo4j `Road` with that `link_id` (`graph.link_names`), then from the validated TomTom road-link mapping file. Without a bound the link ID is added ("Main Road (link X)"), so two links of one street stay distinct. Without a reliable name the label is "Link X [bound] (no street name)". Nothing is guessed from geometry.

## 12. Open items

- **Confirm on live data** with `python main.py inspect` (see SCHEMA.md):
  - that `d[n]` numbering equals `Detector.detector_number`;
  - the `scats/volume` value types;
  - end labelling of the 5-minute data;
  - the pattern of off-grid stamps (e.g. 01:10, 04:22:05).
- **Production team (contract, Nov 2026 version).**
  - Done: `site_grey_no_green` with the `classify_site()` rule; `has_largest_queue: bool | None`; S3 records (`ScreeningLog`, `SiteReport`, `BaselineSnapshot`); link speed (`LinkSpeedReport`, `SiteReport`); the weekly refresh is ours (`BaselineSnapshot`, "written by the researchers' weekly refresh").
  - Still open:
    1. the time zone of periods, and a UTC cache key (`ScreeningCacheKey.period_end` is still a local-offset datetime, so the same instant can give two keys);
    2. a config/rules hash in the cache key or the `baseline_version` (a rule change inside a week reuses the old run and snapshot);
    3. the optional audit fields in §11, or where audit records should be kept instead;
    4. the S3 bucket and prefix (`DIAGNOSTICS_ARCHIVE`), with put/get/list rights;
    5. one `BaselineSnapshot` per weekday and slot (as written now) or one per week: a whole week is about 48 × 7 slots × ~16,000 values, too large for one object.
- **TomTom mapping.** Q5 uses the same approach ↔ link mapping file as the production TomTom layer (identical file, checked by SHA-256 on 2 Nov 2026). A site that is not in it (e.g. 177) has no TomTom confirmation in production either.
- **Methodology owner's review (3 Nov 2026), checks to run on live data** (`python main.py summary`, section REVIEW; `python main.py kpi-check`):
  - Grey: primary causes; approaches without green split into "HasGreen = 0 recorded" (with the recorded GreenShare) and "no record" (missing data); sites Grey only because of a no-green approach although Q3A and Q3B are assessable, with the category each alternative would give — (a) the no-green approach is not assessable instead of greying the site, (b) a recorded HasGreen = 0 is a measured 0 % green share. Neither alternative is applied; `q3c.grey_site_if_any_approach_without_green` stays `true` until decided.
  - Detector Health: the failure pattern (one detector at 0, 1–4 or 5–9 vehicles; several) and the category the site would have if the gate had passed (`if_detectors_passed`, analysis only, never shown as the category).
  - Q3C: current green shares of 100 %, changes of 30 percentage points or more from usual, zero-width ranges; `kpi-check` prints every stored PerfApproach / PerfKpi field per quarter-hour, with the sum of GreenShare over the approaches.
  - Cycle: Cycle Stability of 0 (e.g. SCATS 707: compare with CycleCvPct in `kpi-check`) and values within 2 % of the bound they were compared with.
- **Findings on live data, run 651303f563f6 (Fri 30 Oct 2026 15:00–15:30), after the Q1/Q3C precedence fix (SCATS 976 is now Red):**
  - **CycleStability is a clamped function of CycleCvPct:** CycleStability = max(0, 100 − 5 × CycleCvPct) (SCATS 976: CV 4.502 → 77.492, CV 2.800 → 85.998). The 0 at SCATS 707 is therefore a real measurement (CV 38.9 % and 44.5 %), but every CV of 20 % or more reads 0, so the measure cannot distinguish them. Using CycleCvPct for Q3B (higher = poorer, not clamped) is an option for the methodology owner; not changed.
  - **GreenShare is the share of the cycle in which the approach has green, not a split between approaches.** Approaches served in several phases overlap, so the sum over a site's approaches is not 100 % (SCATS 976: 200 %; 707: about 190 %). 100 % is a valid value: SCATS 976 Heatherton Road [E] runs in phases A and B, which together were the whole cycle; its usual 82 % means another phase usually took about 18 % of the cycle.
  - **Approaches without green are recorded zeros, not missing data:** all 210 have HasGreen = 0 recorded in both quarter-hours, 204 with GreenShare 0; 6 have HasGreen = 0 with a GreenShare above 0 (inconsistent records, for Zay).
  - **Q3C history is short for most sites:** 1,045 of 1,579 assessed sites cannot assess Q3C, 566 because an approach has fewer than five usable weeks (mostly 1 or 4). Before about 20 Oct 2026 the PerfApproach records have HasGreen = 0 and GreenShare 0 on every approach while the cycle runs (SCATS 707, 16 Oct; SCATS 994). Q3C becomes assessable as weeks accumulate.
  - **TomTom mapping at SCATS 4566:** two TomTom approaches (-184162762, -416649043, both "William Street North Bound") are mapped to the same link WILLH6X4J54X, and the site's other William Street [N] EGRESS link (WILLH6X4J642) has no TomTom approach. The report names each row by its TomTom approach ID and states it in the coverage note; nothing is re-assigned. For the TomTom-layer owner: the mapping file.
  - **Link mapping at SCATS 707:** Kendall Road [W] has 70–75 % green in phases A, B and D but zero volume; Ringwood–Warrandyte Road [S] never has green; link STNAHHXXJJ62 [NW] (no street name in Neo4j) carries the same phase A green as Ringwood–Warrandyte Road [N] with zero volume. Unnamed `STNA…` links also appear at SCATS 983 with the values of Abbotts Road [E]. For Zay: link-to-approach mapping.
- **Q3C history (live data).** At site 994 every reference week before 23 Oct 2026 has `HasGreen = 0` on every approach while the cycle runs normally, so Q3C has one usable week. `inspect --history` now shows the GreenShare stored with `HasGreen = 0`, to tell whether HasGreen was not filled before that date (a data-pipeline question for Zay) or whether the records are empty.
- **Link speed.** The reference speed is read from the same feed's reference weeks (§9.1); if the production team has a dedicated historical series, `link_speed_reference` can point to it instead.
- **Decided with the methodology owner (3 Nov 2026):** Q5 ranks both control and approach delay (§9); reference weeks with missing data are not replaced (§3); the Q3 one-abnormal/one-normal/one-not-assessable case keeps the document's rule and is shown as a note (§6).
- **Template IDs.** D002's registry ID (`ID_Q5_TOMTOM_CONFIRMATION`) is a placeholder until confirmed.
- **Outside this repository:** the chatbot's `tomtom/engine.py::scats_volume_hours()` groups 15-minute records by their stamp's clock hour. With end labelling, this shifts every hour by 15 minutes (00:45–01:45 instead of 01:00–02:00). It should be fixed in the Chatbot repository.
