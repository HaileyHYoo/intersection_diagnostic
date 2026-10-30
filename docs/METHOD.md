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
- **Putting records on the grid (decision)** (`series.py`):
  - A stamp within `alignment.tolerance_seconds` (60 s) of a grid point is moved onto that point.
  - A stamp further off the grid is dropped (`off_grid: "drop"`). It is never moved into the neighbouring interval.
  - If two records land on the same point, the latest one is kept (`duplicates: "last"`).
  - The counts of moved, dropped and duplicate records are kept with every run.
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
- **Normal range and usual value.** The normal range is the **10th–90th percentile** (linear interpolation). The usual (reference) value is the **mean** of the observations, as in the chatbot's operating-envelope checks (`reference_value`).
- **Caching.** Values per reference period are cached (`slot_values`), so a reference day fetched once serves every later analysis day that uses it.
  - The weekly job (`python main.py baseline`) precomputes every slot of the coming days.
  - An on-demand request reads only the 8 reference periods it needs.
  - The baseline version combines the schema version with the history, percentile and alignment rules. If any of these change, the baselines and runs are recomputed.

## 4. Q2: Detector health gate

- **Detectors.** Neo4j `(Detector)-[:BELONG_TO]->(Intersection)` with `active = true` only **(decision)**.
- **Counts.** The raw counts in `scats/volume`, field `d[n]`, where n = `detector_number`. Each detector's count is the sum over the last 60 minutes (the twelve 5-minute records).

| Result | When |
|---|---|
| FAIL → Detector Health Issue | Any active detector counted fewer than 10 vehicles (`q2.min_vehicles`). An observed low count takes precedence over missing records elsewhere. |
| INSUFFICIENT → Grey | No low count, but some detector lacks a complete 60-minute record **(decision: all 12 required)**, or the site has no active detector |
| PASS | Every active detector counted at least 10 vehicles |

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

- **Data and period.** TomTom KPIs stored in InfluxDB (`IntersectionTurnKpi`, `IntersectionKpi`) for the same 30-minute period. **The TomTom API is off (decision).** The queue length is therefore reported as unavailable, not estimated.
- **Metrics per approach.**
  - Approach delay: mean `ApproachDelaySec`
  - Control delay and multi-stop rate: weighted by `SampleCount`
  - Movements: listed separately
  - An approach is *adequately observed* when it has records in both quarter-hours.
- **Matching.** TomTom approaches are matched to EGRESS links with the chatbot's verified mapping file (`data/tomtom_neo4j_links_AU-VIC-Melbourne_final.json`).
- **Agreement (decided by code).**

  | Result | When |
  |---|---|
  | agreement | The greatest delay is on a SCATS-identified approach |
  | disagreement | A SCATS-identified approach is observed, but the greatest delay is elsewhere |
  | insufficient coverage | No SCATS-identified approach is adequately observed |

  Partial coverage and unmapped approaches are stated.
- **No data.** The answer is "TomTom confirmation unavailable for this intersection or analysis period." D001 still runs.

## 10. Report, storage and audit

The report has four fixed sections: Diagnosis, Supporting Evidence, TomTom Road-User Impact and Suggested Engineering Checks.

The SQLite store (`store.py`) keeps:
- reference values and baselines;
- screening runs, keyed by region, period, baseline version and rules version, with the complete per-site evidence and alignment counts;
- diagnoses, with template ID and version, the evidence, the answer, who wrote it (code or LLM) and any rejection.

A run that is already in progress is waited for, not started a second time.

## 11. Open items

- **Confirm on live data** with `python main.py inspect` (see SCHEMA.md):
  - that `d[n]` numbering equals `Detector.detector_number`;
  - the `scats/volume` value types;
  - end labelling of the 5-minute data;
  - the pattern of off-grid stamps (e.g. 01:10, 04:22:05).
- **From the production team:** the final schema, the store/database, the host call pattern and the map display.
- **Outside this repository:** the chatbot's `tomtom/engine.py::scats_volume_hours()` groups 15-minute records by their stamp's clock hour. With end labelling, this shifts every hour by 15 minutes (00:45–01:45 instead of 01:00–02:00). It should be fixed in the Chatbot repository.
