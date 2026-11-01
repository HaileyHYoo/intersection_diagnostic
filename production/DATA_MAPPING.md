# Data mapping — Q1 to Q5

Where each question's data comes from, and how the code turns it into the value that is compared. Every bucket, measurement, field and tag name comes from `diagnostics/config/schema.json` (version `tmp-2026-10-30b`), and every threshold from `diagnostics/config/rules.json`. Changing a name there changes the query; no code change is needed.

**Common to all InfluxDB reads**
- Every query is filtered by the `Region` tag (site numbers repeat across cities).
- Times are stored in UTC and the period is converted to UTC for the query.
- A record's stamp is the **end** of its interval (01:15 covers 01:00–01:15).
- Off-grid stamps are put into the interval their stamp falls in (`alignment.off_grid: "ceil"`). For example, PerfKpi stamped 16:37 belongs to 16:30–16:45. A stamp within 60 s of a grid point is moved onto it. Of duplicates, the latest is kept.
- **Analysis period:** the latest completed 30-minute slot, 5 min after it ends (`data_latency_minutes`).
- **History:** the same weekday and slot in each of the 8 previous weeks. Public holidays, DST-change days and the year end are excluded and not replaced. At least 5 valid values are needed; the usual value is the median and the normal range is p10–p90.

## Network (Neo4j)

| Used for | Query (`schema.graph`) | Returns |
|---|---|---|
| Sites | `sites` | `(:Intersection)-[:IN]-(:Region {tag})`, signalised, with `scats_site_no` → site, lat, lon, street names of its roads (map label) |
| Q2 detectors | `detectors` | `(:Detector)-[:BELONG_TO]->(:Intersection)` → `detector_number`, `active`. Only `active = true` detectors are checked. |
| Q1 / Q3C approaches | `approaches` | `(:Intersection)-[:EGRESS]-(:Road)` → `link_id` and `street_name`. One approach per link. |

## Q2 — Detector health gate

| | |
|---|---|
| **Source** | InfluxDB `scats` / `volume` (raw, not aggregated) |
| **Site tag** | `SiteNo`, plain number (`994`) |
| **Value** | Field `d[n]` = 5-minute count of detector *n* (`n` = Neo4j `Detector.detector_number`) |
| **Window** | The 60 minutes ending with the analysis period: 12 records |
| **Calculation** | Sum of the 12 counts per active detector. A negative count is treated as a missing record (`q2.negative_counts: "missing"`). |
| **Rule** | ≥ 10 vehicles (`q2.min_vehicles`) → PASS, even if records are missing. < 10 with all 12 records → FAIL. < 10 with records missing → INSUFFICIENT. |
| **Site result** | Any FAIL → **Detector Health Issue**. Otherwise any INSUFFICIENT → **Grey**. Otherwise PASS, and the site goes on to Q1/Q3. |
| **Code** | `measures.detector_totals`, `screening.q2_gate` |

## Q1 — Traffic abnormality

| | |
|---|---|
| **Source** | InfluxDB `scats-aggregation` / `volume`, filter `MinutesPast = 15` |
| **Approach tag** | `DetectorGroupId` = Neo4j EGRESS `Road.link_id` |
| **Value** | Field `Volume` (15-minute volume) |
| **Calculation** | Sum of the two quarter-hours of the period = 30-minute volume per approach |
| **History** | The same 30-minute volume in each reference week |
| **Evaluated approaches** | EGRESS links with at least 1 history value |
| **Rule** | ABNORMAL when outside p10–p90 **and** ≥ 10 % from the usual value (`q1.min_pct_difference`), giving direction HIGH or LOW. Site ABNORMAL if any approach is. |
| **Missing** | Any evaluated approach without a current value, or with < 5 history values → Q1 INSUFFICIENT → Grey. No interpolation. |
| **Code** | `measures.link_volumes`, `screening.q1_traffic` |

## Q3 — Signal-operation abnormality

All three measures come from `scats-aggregation`, site tag `SiteNo` in `S` format (`S994`). Each uses the mean of the two quarter-hours of the period.

| | Q3A Cycle length | Q3B Cycle stability | Q3C Phase service |
|---|---|---|---|
| **Measurement** | `IntersectionPerfKpi` (`MinutesPast = 15`) | `IntersectionPerfKpi` (`MinutesPast = 15`) | `IntersectionPerfApproach` |
| **Field** | `AvgCycle` (s) | `CycleStability` (higher = more stable) | `GreenShare` (%) and `HasGreen`, per `LinkId` (= EGRESS link), with `Bound` |
| **Level** | Site | Site | Approach |
| **Rule** | Outside p10–p90 **and** ≥ 10 % from usual (both directions) | Below p10 only (poorer stability) | Outside p10–p90 (LOW / HIGH), no % threshold |
| **Not assessable** | No current value, or < 5 history values | Same | Any approach without a current value or with < 5 history values. Any approach with `HasGreen = 0` or no record now → **site Grey** (`q3c.grey_site_if_any_approach_without_green`). |

- **Valid green share:** usable only when both quarter-hours have `HasGreen = 1` and a `GreenShare`. It is rounded to 3 decimals so float noise does not fall outside a zero-width range.
- **Q3 overall:** ABNORMAL if ≥ 2 of 3 are ABNORMAL. Otherwise NORMAL if ≥ 2 can be assessed (flagged `missing_measure_could_change` when the third could have made it ABNORMAL). Otherwise INSUFFICIENT → Grey.
- **No fallback:** the subsystem `ActiveCycleLength` fallback for Q3A exists but is off (`fallbacks.enabled: false`).
- **Code:** `measures.site_kpi`, `measures.approach_green`, `screening.q3_signal`.

## Classification

| Q2 | Q1 | Q3 | Category |
|---|---|---|---|
| FAIL | – | – | Detector Health Issue |
| INSUFFICIENT | – | – | Grey |
| PASS | INSUFFICIENT (either one), or an approach without green | | Grey |
| PASS | ABNORMAL | ABNORMAL | **Red** |
| PASS | ABNORMAL | NORMAL | Amber (traffic) |
| PASS | NORMAL | ABNORMAL | Amber (signal) |
| PASS | NORMAL | NORMAL | Normal |

## Q4 — SCATS diagnostic interpretation (template D001)

| | |
|---|---|
| **Source** | **No new data.** The Red site's saved Q1 and Q3 evidence from the screening run. |
| **Uses** | Q1 flagged approaches (current, usual, range, % difference, direction). Q3A/Q3B values and status. Q3C flagged approaches. |
| **Output** | Diagnosis, supporting evidence and suggested engineering checks, written by code. The LLM may only reword them, and is rejected if it adds numbers or claims not in the evidence. |
| **Code** | `templates/d001.py` |

## Q5 — TomTom road-user confirmation (template D002)

| Data | Source | Used for |
|---|---|---|
| Approach ↔ link mapping | File `data/tomtom_neo4j_links_AU-VIC-Melbourne_final.json` (from the chatbot) | TomTom `ApproachId` → Neo4j EGRESS `link_id`, junction UUID, travel directions of approaches and exits |
| Approach delay | `scats-aggregation` / `IntersectionTurnKpi`, filter `MinutesPast = 15`, `Provider = TomTom`; tags `SiteNo` (`S…`), `ApproachId`, `ExitId` | `ApproachDelaySec`: mean per approach over the period → **largest-delay approach** |
| Movement delay, stops | same | `ControlDelaySec`, `MultiStopRate`, weighted by `SampleCount`, per movement (left / through / right from the mapping directions) |
| Coverage | same | Quarter-hours observed per approach; ≥ 2 (`tomtom.adequate_quarters`) = adequate |
| Site delay | `scats-aggregation` / `IntersectionKpi`, `Provider = TomTom` | `ControlDelaySec` for the whole junction (context) |
| Queue length | TomTom Junction Analytics archive API (`.../archive/{junction_uuid}/data/flat/daily`, `TOMTOM_API_KEY`, stamps in UTC) | Per-minute `queueLengthMeters` per approach within the period: mean and max; ≥ 15 minutes (`tomtom.queue_min_minutes`) = adequate → **longest-queue approach** |

- **Comparison with SCATS:** each approach flagged by Q1 or Q3C gets one verdict.
  - **agree** if it has the largest delay or the longest queue;
  - **disagree** if it is observed but has neither;
  - **insufficient coverage** if TomTom did not observe it adequately.
- **Site verdict:** agree if any approach agrees, otherwise disagree if any disagrees, otherwise insufficient coverage.
- **No TomTom data for the period:** the fixed "TomTom unavailable" message.
- **Read but not used in the result:** `TurnRatioPct` (IntersectionTurnKpi), and `AvgStopsPerCar` and `AvgSpeedkmh` (IntersectionKpi).
- **Code:** `templates/d002.py`, `sources/tomtom_queue.py`, `tomtom_map.py`.
