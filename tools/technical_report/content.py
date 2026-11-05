import json, sys

H1 = lambda t: {"h1": t}
H2 = lambda t: {"h2": t}
H3 = lambda t: {"h3": t}
P = lambda t: {"p": t}
B = lambda *t: {"bullets": list(t)}
N = lambda *t: {"numbers": list(t)}
def T(head, rows, widths, caption=None):
    return {"table": {"head": head, "rows": rows, "widths": widths, "caption": caption}}

body = []
add = body.extend

# ---------------------------------------------------------------- 1
add([H1("1. Purpose and Scope"),
P("This document specifies the design and implementation of **Intersections Diagnostics V1**, the intersection screening and diagnosis layer of the Platform for the Melbourne SCATS network (2,501 signalised intersections). It describes the code as of 5 November 2026, after the methodology owner's reviews of 3–5 November, and is intended as the reference for the methodology owner, the team integrating it into the production backend, and the team extending it."),
P("The methodology is *Intersections Diagnostics, V1 Screening and Diagnostic Methodology* (M. Sarvi, 29 October 2026), with the updates on historical records (§18) and supplementary link speed (\"Speed added\", 2 November 2026). The methodology is the guideline. Where it leaves a choice open, the code records a **decision**, which is a value or switch in `diagnostics/config/rules.json`."),
P("V1 works at two levels:"),
B("**Level 1 – network screening.** For the latest completed 30-minute period, every intersection is classified from four questions: **Q2** detector health (gate), **Q1** traffic abnormality, **Q3** signal-operation abnormality (Q3A cycle length, Q3B cycle stability, Q3C phase service by approach). The result is one of Red – Needs Attention, Amber – Traffic Abnormality, Amber – Signal-Operation Abnormality, Normal, Grey – Insufficient Data, and Detector Health Issue.",
  "**Level 2 – on demand.** Clicking a Red intersection produces a four-section report from **Q4** (D001, SCATS diagnostic interpretation of the saved Q1/Q3 evidence) and **Q5** (D002, TomTom road-user impact for the same 30 minutes), plus the supplementary TomTom link speed. Amber clicks show the saved evidence and the link speed."),
P("The central design principle is the same as in the SCATS QA Bot: **code computes every number and every classification**. An LLM, when configured, may only re-word an answer the code has already written, and its wording is rejected unless it keeps every number, link ID, approach name, label and verdict (Section 6)."),
H2("1.1 Changes after the methodology owner's reviews (3–5 Nov 2026)"),
T(["Date", "Change", "Type"], [
  ["3 Nov", "Q1 and Q3C: an observed abnormal approach decides even when another approach cannot be assessed (methodology §4, §8). Before, a missing approach made the component \"insufficient data\" first.", "Implementation fix"],
  ["3 Nov", "Q5 ranks both control delay and approach delay; a SCATS-identified approach agrees when it has the greatest of either, or the longest queue.", "Decision"],
  ["3 Nov", "Q3 with one measure abnormal, one normal and one not assessable stays NORMAL as written, and is shown with a note.", "Decision"],
  ["3 Nov", "Reference weeks with missing data are not replaced by earlier weeks.", "Decision"],
  ["3 Nov", "Q4 wording: what the data show vs possible explanations; SCATS adaptive operation; checks in order of priority. Q5: agreement / partial agreement / disagreement / insufficient coverage, explicit 30-minute coverage, Junction Analytics kept apart from link speed.", "Reporting"],
  ["3 Nov", "Approach names from Neo4j roads and the validated road-link mapping; link ID kept only where no reliable name exists or two links share a name.", "Reporting"],
  ["4 Nov", "Reference link speed from the same `aimes/speed` feed (median of the reference weeks), read on the click, not stored.", "Decision"],
  ["5 Nov", "Q2: one failing detector is tolerated; two or more remain a Detector Health Issue. Threshold kept at 10 vehicles.", "Decision"],
  ["5 Nov", "Baseline snapshot covers every site's approaches, whatever its category.", "Implementation fix"],
  ["5 Nov", "IntersectionPerfKpi / IntersectionPerfApproach records describe the quarter-hour **before** their stamp (15:07 = 14:45–15:00, confirmed with the data owner); data latency 10 minutes.", "Implementation fix"],
  ["5 Nov", "LLM checks: link IDs must be in the evidence; the verdict and coverage lines are always the code's; required labels.", "Implementation fix"],
  ["5 Nov", "Q1 table lists approaches not assessed, with the reason; Q3C labelled as derived from phase durations.", "Reporting"],
], [1, 7, 1.6]),
H2("1.2 Data map"),
{"image": "datamap.png", "width": 640, "height": 231, "alt": "Data map",
 "caption": "Figure 1. Data sources, the two levels and the outputs. Level 1 is deterministic code; Level 2 adds the optional LLM wording, which can only re-word the code's answer."},
])

# ---------------------------------------------------------------- 2
add([H1("2. System Architecture Overview"),
P("The system is a Python package (`diagnostics/`) with a command-line tool (`main.py`) for local runs and a generated production package (`production/dash_backend/ai_brains/intersections/diagnostics/`, built by `tools/build_production.py`) for the Platform backend. Each module has one narrow responsibility so that the classification path stays small and auditable."),
H2("2.1 Code modules"),
T(["File", "Role"], [
  ["screening.py", "Level 1: the Q2 gate, Q1, Q3A/B/C, Q3 and the classification for every site; caution notes; one bad site never stops the network screening"],
  ["measures.py, series.py", "From raw records to one value per entity and period: grid alignment (end labelling, records written after their interval), two quarter-hours per period, missing never zero"],
  ["baseline.py, stats.py", "Reference periods, per-period value cache, the historical envelope (median, 10th–90th percentile, ≥ 5 observations) and the three comparison rules"],
  ["timewin.py, vic_calendar.py", "Periods (48 local clock slots), reference weeks, Melbourne time and daylight saving, Victorian public holidays"],
  ["templates/d001.py, d002.py", "Level 2: Q4 SCATS interpretation and Q5 TomTom confirmation; evidence, code-written answer, LLM prompt and checks"],
  ["llm.py, layout.py", "The LLM guard (numbers, link IDs, required names and labels, forbidden claims) and the labelled-line layout"],
  ["link_speed.py, arms.py", "Supplementary TomTom link speed and reference speed; arm numbers from the production operational sheet"],
  ["names.py, tomtom_map.py", "Approach labels unique within a site; the TomTom approach ↔ link mapping file and stub-link resolution"],
  ["report.py", "The four-section report (Markdown/HTML/contract), tables with abnormal rows marked"],
  ["service.py, store.py", "The local service: cached runs and diagnoses (SQLite), config snapshots, provenance, audit records"],
  ["archive.py", "Screening JSON logs and baseline snapshots (S3 or a folder), never overwritten; site history"],
  ["contract/adapter.py, core.py", "The production contract path (Pydantic models of the production team), Level 1 and Level 2 entry points"],
  ["host.py", "Functions the backend calls: run_screening, run_site_report, log_screening, run_link_speed, weekly_baseline_job"],
  ["sources/live.py, influx.py, graph.py, tomtom_queue.py", "InfluxDB (Flux, pushed-down filters), Neo4j (Cypher from the schema), TomTom Junction Analytics queue archive"],
  ["local/summary.py, independent.py, audit.py, inspect_data.py", "Analysis tools: category breakdown, independent checks, input audit, feed inspection (read only)"],
  ["local/examples.py, viewer.py, fake.py", "Example outputs, the local map viewer, and a synthetic network for tests"],
], [2.6, 7]),
H2("2.2 Configuration and data files"),
T(["File", "Role"], [
  ["config/rules.json", "Every threshold, decision and switch (Section 11). Its hash is the rules version kept with each run."],
  ["config/schema.json", "Feed names (bucket, measurement, fields, tags, intervals) and the Cypher queries. Replaced by the production schema without code change."],
  ["templates/catalog.json", "D001/D002 definitions: question, parameters, source fields, execution path, output, missing-data rule, constraints"],
  ["data/tomtom_neo4j_links_AU-VIC-Melbourne_final.json", "The TomTom approach ↔ link mapping, identical to the production TomTom layer's file (checked by SHA-256)"],
  ["contract/intersections_diagnostics_schemas.py", "The production team's contract, vendored unchanged"],
], [3.2, 6.4]),
H2("2.3 Two levels and what a click runs"),
T(["Level", "When", "Sites", "LLM"], [
  ["1: Q2, then Q1 + Q3", "A screening request with no saved run for the period (layer activation or refresh)", "Whole network", "No"],
  ["2: D001 (Q4) + D002 (Q5) + link speed", "A click on a Red site", "One", "Wording only"],
  ["Evidence + link speed", "A click on an Amber site", "One", "No"],
  ["Saved evidence", "A click on Normal, Grey or Detector Health", "One", "No"],
], [2.6, 4, 1.4, 1.4]),
])

# ---------------------------------------------------------------- 3
add([H1("3. Data Model"),
H2("3.1 Neo4j – network structure"),
T(["Query", "Pattern", "Used for"], [
  ["sites", "`(:Intersection)-[:IN]-(:Region {tag})`, signalised, with `scats_site_no`; street names of its roads", "The network, map labels"],
  ["detectors", "`(:Detector)-[:BELONG_TO]->(:Intersection)`, `detector_number`, `active`", "Q2 (active detectors only)"],
  ["approaches", "`(:Intersection)-[:EGRESS]-(:Road)`, `link_id`, `coalesce(street_name, name)`", "Q1 approaches, Q3C names, link speed"],
  ["link_names", "`(:Road)` by `link_id`", "Names of links that are not a site's EGRESS road"],
], [1.3, 5, 2.4]),
H2("3.2 InfluxDB – time series"),
T(["Feed", "Bucket / measurement", "Fields", "Key", "Question"], [
  ["Detector counts", "scats / volume", "d[n] (5 min)", "SiteNo, n = detector_number", "Q2"],
  ["Link volume", "scats-aggregation / volume", "Volume (15 min, MinutesPast 15)", "DetectorGroupId = link_id", "Q1"],
  ["Site KPIs", "scats-aggregation / IntersectionPerfKpi", "AvgCycle, CycleStability (15 min)", "SiteNo (S + number)", "Q3A, Q3B"],
  ["Approach KPIs", "scats-aggregation / IntersectionPerfApproach", "GreenShare (%), HasGreen, Phases", "SiteNo, LinkId, Bound", "Q3C"],
  ["TomTom turns", "scats-aggregation / IntersectionTurnKpi", "ControlDelaySec, ApproachDelaySec, MultiStopRate, SampleCount", "SiteNo, ApproachId, ExitId", "Q5"],
  ["TomTom site", "scats-aggregation / IntersectionKpi", "ControlDelaySec", "SiteNo", "Q5"],
  ["Link speed", "aimes / speed", "Speed (km/h), Provider TomTom", "DetectorGroupId = link_id", "Supplementary"],
], [1.4, 2.4, 2.4, 2, 1]),
P("Only the existing calculated KPIs are used. DemandShare, SignedGap, DemandPressure, GreenGapBusiest, RiskBusiest and the other fields are read by the audit tools but never by the screening."),
H2("3.3 TomTom"),
B("**Delay** comes from the TomTom KPIs already stored in InfluxDB for the same 30 minutes.",
  "**Queue** comes from the Junction Analytics API archive (`sources/tomtom_queue.py`, same endpoint and parsing as the production TomTom layer; recent and historical parts split at now − 24 h). Without a key, or for a site without a junction, the queue is reported as unavailable with the reason, never estimated.",
  "**Matching.** TomTom approaches are matched to EGRESS links with the validated mapping file. For about 11 % of approaches the file gives the link upstream of a short stub (`stub_hops` > 0); such an approach is matched to the site's approach on the same street only when exactly one candidate exists. Two TomTom approaches mapped to one link (seen at SCATS 4566) are named by their TomTom ID and disclosed; nothing is re-assigned."),
H2("3.4 Join keys"),
T(["From", "To", "Key"], [
  ["Neo4j Detector", "scats/volume", "`detector_number` = n of `d[n]`, per SiteNo"],
  ["Neo4j EGRESS Road", "volume, PerfApproach, aimes/speed", "`link_id` = `DetectorGroupId` / `LinkId` (normalised)"],
  ["Neo4j Intersection", "PerfKpi, PerfApproach, TomTom KPIs", "`scats_site_no` = `SiteNo` (with or without the S prefix, per feed)"],
  ["TomTom approach", "Neo4j EGRESS Road", "Mapping file `link_id` (with stub resolution)"],
  ["Link", "Operational-sheet arm", "Lowest-position active detectors of the link → DetectorNo → ArmNo (production only)"],
], [2, 2.6, 5]),
H2("3.5 Time, periods and record alignment"),
B("**Periods** are the 48 local clock slots of a day (:00–:30, :30–:00). The analysis period is the latest completed slot, used **10 minutes** after it ends (`data_latency_minutes`).",
  "**Time zones.** Data are stored in UTC; slots, weekdays, holidays and display use Melbourne time. Daylight saving is handled per reference week: on Fri 30 Oct 2026 15:00–15:30 the reference weeks after 4 Oct are 04:00–04:30 UTC and those before are 05:00–05:30 UTC, all 15:00–15:30 local (checked by the audit).",
  "**End labelling.** A 15-minute volume record stamped 15:15 covers 15:00–15:15; a 5-minute detector record goes to the 5 minutes its stamp falls in (records are written at :03, :08 …).",
  "**Records written after their interval.** IntersectionPerfKpi and IntersectionPerfApproach records are written about 7 minutes after the quarter-hour they describe: a record stamped 15:07 is 14:45–15:00 (confirmed with the data owner). They go to the quarter-hour that ended before their stamp, and the query reaches 15 minutes past the period, so 15:00–15:30 uses the records of 15:22 and 15:37. The audit confirms this network-wide: against the 15-minute link volumes, the PerfApproach volume of 31,587 records is closer to the quarter-hour before the stamp in 18,268 cases and to the quarter-hour of the stamp in 11,655 (mean difference 9.7 % vs 13.1 %).",
  "**Missing is never zero.** A 30-minute value needs both quarter-hours; a missing or non-numeric record gives no value."),
])

# ---------------------------------------------------------------- 4
add([H1("4. Screening Pipeline (Level 1)"),
H2("4.1 Historical baseline"),
B("**Reference periods**: the same weekday and slot in each of the 8 weeks before the analysis day. Victorian public holidays, the two daylight-saving change days and 24 Dec – 1 Jan are left out; an excluded or missing week is **not** replaced by an earlier one.",
  "**Envelope**: usual value = median of the valid observations; normal range = 10th–90th percentile (linear interpolation); at least **5** valid observations, otherwise INSUFFICIENT DATA.",
  "**Caching and versions**: values per reference period are cached, so a reference day read once serves every later analysis day. The baseline version (ISO week + method version) changes with any rule that affects baselines (history, percentiles, usual value, alignment), so baselines and snapshots are rebuilt automatically."),
H2("4.2 Q2 – detector health gate"),
T(["Detector result", "When"], [
  ["PASS", "60-minute count of its valid 5-minute records ≥ 10 (`q2.min_vehicles`), even if some records are missing"],
  ["FAIL", "Count below 10 with all twelve records present"],
  ["INSUFFICIENT DATA", "Count below 10 with records missing or negative (a negative count is treated as missing), or no valid record"],
], [2, 7.6]),
T(["Site result", "When"], [
  ["Detector Health Issue", "**Two or more** active detectors FAIL (`q2.tolerated_failed_detectors` = 1)"],
  ["PASS, one detector tolerated", "Exactly one active detector FAILs and every other passes; the site is screened and the detector is shown as a note: \"it may be a low-volume movement or a detector fault\""],
  ["Grey", "A detector is INSUFFICIENT (records missing), or the site has no active detector"],
  ["PASS", "Every active detector passes"],
], [2.4, 7.2]),
H2("4.3 Q1 – traffic abnormality"),
B("**Approaches**: the site's Neo4j EGRESS links; **evaluated** are those with volume in at least one reference week. The others are listed as \"Not assessed: no volume in any reference week\".",
  "**Value**: the sum of the two quarter-hour link volumes.",
  "**Abnormal approach**: outside the 10th–90th range **and** at least 10 % from the usual value.",
  "**Result**: ABNORMAL if any evaluated approach is abnormal, even when another cannot be assessed; otherwise INSUFFICIENT DATA if an evaluated approach lacks a current value or 5 historical values (`q1.grey_if_any_approach_missing`); otherwise NORMAL."),
H2("4.4 Q3 – signal-operation abnormality"),
T(["Measure", "Source", "Abnormal when"], [
  ["Q3A Cycle length", "IntersectionPerfKpi.AvgCycle, mean of the two quarter-hours", "Outside the range and ≥ 10 % from usual"],
  ["Q3B Cycle stability", "IntersectionPerfKpi.CycleStability, mean of the two quarter-hours", "Below the 10th percentile only (poorer stability)"],
  ["Q3C Phase service", "IntersectionPerfApproach.GreenShare per approach link, mean of the two quarter-hours", "Any evaluated approach below the 10th (LOW) or above the 90th percentile (HIGH)"],
], [1.8, 4.3, 3.5]),
B("**Cycle Stability** follows the KPI definition Score = (1 − CV/0.20) × 100, floored at 0, CV being the coefficient of variation of ActiveCycleLength in the 15-minute window. The audit found **no** stored value that departs from it, current or historical. A CV of 20 % or more reads 0 (e.g. SCATS 707, CV 39–44 %).",
  "**GreenShare is derived from phase durations**: it is the share of the cycle taken by the phases serving the approach, not measured signal-group green time. Network-wide, every multi-phase approach equals the sum of its single-phase approaches' shares (79 of 79) and approaches with the same phases have the same share (2,597 of 2,597). Approaches served in several phases overlap, so 100 % is a valid value (an approach green in every phase run).",
  "**Approach without green** (HasGreen = 0 or no record in a quarter-hour) makes the whole site Grey (`q3c.grey_site_if_any_approach_without_green`, strictest setting; decision (A) open).",
  "**Q3C result**: ABNORMAL if any evaluated approach is abnormal, even when another lacks a value or history; otherwise INSUFFICIENT DATA if one does; otherwise NORMAL. No materiality threshold is added (methodology §8).",
  "**Q3 overall**: ABNORMAL if at least 2 of 3 measures are abnormal; NORMAL if at least 2 are assessable; otherwise INSUFFICIENT DATA. One abnormal, one normal and one not assessable stays NORMAL, with a note saying what the category would be had the missing measure been abnormal."),
H2("4.5 Classification"),
T(["Q2", "Q1", "Q3", "Category"], [
  ["FAIL (2+ detectors)", "–", "–", "Detector Health Issue"],
  ["INSUFFICIENT", "–", "–", "Grey – Insufficient Data"],
  ["PASS", "any", "an evaluated approach without green", "Grey"],
  ["PASS", "INSUFFICIENT", "any", "Grey"],
  ["PASS", "any", "INSUFFICIENT", "Grey"],
  ["PASS", "NORMAL", "NORMAL", "Normal"],
  ["PASS", "ABNORMAL", "NORMAL", "Amber – Traffic Abnormality"],
  ["PASS", "NORMAL", "ABNORMAL", "Amber – Signal-Operation Abnormality"],
  ["PASS", "ABNORMAL", "ABNORMAL", "Red – Needs Attention"],
], [2, 1.7, 3, 3]),
P("Every Grey site keeps the reasons it is Grey (in the log, the contract's `insufficient_data_reason` and the evidence), so they can be investigated during platform testing."),
])

# ---------------------------------------------------------------- 5
add([H1("5. Site Report (Level 2)"),
P("The report of a Red site has four fixed sections: **1. Diagnosis**, **2. Supporting Evidence**, **3. TomTom Road-User Impact** and **4. Suggested Engineering Checks**. Sections 1, 2 and 4 come from D001, section 3 from D002 and the supplementary link speed."),
H2("5.1 D001 (Q4) – SCATS diagnostic interpretation"),
B("**Inputs**: the saved Q1/Q3 evidence of the run only; no further SCATS query or calculation.",
  "**Diagnosis**, two labelled lines: \"What the data show:\" (approaches and direction of each finding, without figures) and \"Possible explanations (not demonstrated by these data):\", which states that SCATS adapts cycle length and phase service to demand and coordination, so an abnormal value does not by itself show a signal problem.",
  "**Supporting Evidence**: one line saying what is outside its range; those rows are bold in the tables, which hold every measurement (current, usual, range, difference).",
  "**Suggested Engineering Checks**, numbered by priority: phase service against demand on an approach with both findings; adaptive response against plan or coordination change (plan, subsystem cycle, linking, offsets); phase service on approaches without a traffic finding; cycle-by-cycle stability; incidents, events or diversions for a volume change without a signal finding."),
T(["Combination of findings", "Possible explanation written"], [
  ["Longer (shorter) cycle with higher (lower) volume", "may be SCATS lengthening (shortening) the cycle as demand rose (fell)"],
  ["Cycle change without a matching volume change", "a plan or coordination change is a possible explanation"],
  ["Green and volume in the same direction on an approach", "may be SCATS following its demand, or the counted volume may follow the green given"],
  ["Less green to a busier approach (or the reverse)", "the opposite of a demand response, the finding most worth verifying"],
  ["Phase-service change without a volume change", "may follow demand on competing phases or the coordination plan"],
  ["Poorer stability", "the cycle varied more than usual, which can happen while SCATS adapts"],
], [4, 5.6]),
H2("5.2 D002 (Q5) – TomTom road-user impact"),
B("**Measures per approach** (same 30 minutes): control delay (plain mean of the 15-minute turn records, as the chatbot), approach delay, multi-stop rate, mean and maximum queue, and control delay per movement (left / through / right / u-turn from the mapping's travel directions). A negative delay counts as 0. An approach is adequately observed with records in both quarter-hours; its queue with at least 15 minutes.",
  "**Agreement per SCATS-identified approach**: agreement if it has the greatest control delay, the greatest approach delay or the longest queue among the adequately observed approaches; disagreement if observed without any; insufficient coverage if not observed.",
  "**Site verdict**: agreement (all agree), partial agreement (some agree, others differ or are not covered), disagreement (none agrees, at least one observed), insufficient coverage (none observed).",
  "**Text**, four labelled lines: \"Largest values:\", \"By approach:\", \"Overall:\" and \"Coverage:\" (full 30 minutes, or 15-minute periods and queue minutes per approach, and the approaches without TomTom data). The verdict and coverage lines are always the code's. TomTom shows a road-user impact, never its cause; \"highest among the observed approaches does not mean historically abnormal delay\" is always stated.",
  "**No TomTom data**: the methodology's fixed message \"TomTom confirmation unavailable for this intersection or analysis period.\" with the reason (e.g. SCATS 774: no TomTom approach mapping); Q4 still runs."),
H2("5.3 Supplementary TomTom link speed"),
B("Shown on Amber and Red clicks for the site's incoming EGRESS links: harmonic mean of the positive `aimes/speed` samples in the same 30 minutes.",
  "**Reference speed**: the same feed in the same 30 minutes of the reference weeks, one harmonic mean per week, their median, shown when at least 5 weeks have samples, with the number of weeks (fills the contract's `reference_speed_kmh`). Read on the click; nothing is stored and no network-wide speed baseline exists.",
  "Under its own heading in section 3, separate from Junction Analytics, and never used for any classification or the Q5 agreement."),
H2("5.4 Names of approaches"),
P("An approach reads \"Street [bound]\": the street from the site's EGRESS road, else any Neo4j road with that link_id, else the validated TomTom mapping. Two links that would read the same get their link IDs (\"William Street [N] (link WILLH6X4J54X)\"); without a reliable name the label is \"Link X [bound] (no street name)\". Nothing is guessed."),
])

# ---------------------------------------------------------------- 6
add([H1("6. Anti-Hallucination and Trustworthiness Design"),
B("**Classification is code.** Q1–Q3, the categories, the Q5 rankings and verdicts are deterministic; the LLM never sees them as something to decide.",
  "**The code writes a complete answer first.** Without an LLM, or when its wording is rejected, the code's answer is shown. Which one was used, and why a wording was rejected, is kept with the diagnosis.",
  "**LLM wording is checked** before use. It is rejected if it: is not the requested JSON; contains a number that is not in the evidence (compared by value); contains a link ID that is not in the evidence; drops an abnormal approach, a required label (\"What the data show:\", \"By approach:\", \"Overall: <verdict>\"); calls a cycle measure \"within\" its range when it is outside (checked against the measure named just before \"within\"); or makes a forbidden claim (fault, \"caused by\", timing changes).",
  "**Fixed texts.** The verdict and coverage lines of Q5 are always replaced by the code's; the caveat on historically abnormal delay is always kept.",
  "**Missing is never zero** in any measure; an unavailable queue makes \"has the largest queue\" unknown, not \"no\".",
  "**Every number is traceable**: each run and diagnosis keeps the configuration version, the data provenance (source, measurement, time range, record count) and the registry template IDs."),
])

# ---------------------------------------------------------------- 7
add([H1("7. Records, Reproducibility and Audit"),
T(["Record", "Where", "Written"], [
  ["Screening JSON log (§18.3)", "`screening-logs/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}.json`", "Once per completed run, never overwritten"],
  ["Baseline snapshot (§18.4)", "`baselines/{region}/{baseline_version}/{weekday}/{HHMM}.json.gz`", "By the weekly job and by a screening whose slot is missing; covers every site's approaches"],
  ["Site report (§18.2)", "Contract `SiteReport`", "On a Red click on the contract path"],
  ["Runs, diagnoses, configs, audits", "SQLite store", "Every run and diagnosis"],
], [2.2, 4.6, 2.8]),
B("**Log content**: metadata (run, times, region, period, status, baseline version and snapshot key, reference periods and skipped days, versions), every site with its category, Detector Health issues with the failed detectors and counts, traffic and signal abnormalities, Grey sites with reasons, summary counts and the complete Q2/Q1/Q3 evidence of every site.",
  "**Snapshot content**: per site Q3A/Q3B, per approach Q1 volume and Q3C green share: usual value, 10th–90th range and number of observations, with the weekday, slot and reference periods.",
  "**Storage failure**: the run still completes; the failure is recorded and the log can be written later (`main.py archive`)."),
])

# ---------------------------------------------------------------- 8
add([H1("8. Production Integration"),
T(["Function", "Contract models", "What it does"], [
  ["core.run_screening", "ScreeningInput → ScreeningResult", "Level 1; the input's ScreeningConfig overrides rules.json; writes the slot's BaselineSnapshot"],
  ["core.run_site_report", "SiteReportRequest + ScreeningRun → SiteReport", "Amber: evidence + LinkSpeedReport; Red: also Q4/Q5"],
  ["core.run_diagnosis", "DiagnosisInput → DiagnosisResult", "Q4/Q5 on the saved evidence"],
  ["core.run_link_speed", "SiteScreeningResult, AnalysisPeriod → LinkSpeedReport", "Supplementary link speed"],
  ["core.write_screening_log", "ScreeningRun → ScreeningLog", "The §18.3 log, once per run"],
], [2.2, 3.4, 4]),
B("**Timing**: the backend should screen a period from **10 minutes** after it ends (15:40 for 15:00–15:30); earlier, the last PerfKpi/PerfApproach record is not yet written and Q3 is not assessable.",
  "**Q2 tolerance**: `Q2DetectorGate.status` is PASS for a site with one failing detector while that detector's `passed` is False; `classify_site()` reads the status, so the contract's checks hold.",
  "**Verification**: `python main.py contract-check` passes every site of a stored run through the contract's models and validators.",
  "**Open with the production team**: a UTC cache key for periods; a rules hash in the cache key; the S3 bucket and prefix; the optional audit fields; one snapshot per slot or per week; D002's registry ID."),
])

# ---------------------------------------------------------------- 9
add([H1("9. Validation and Audit Results"),
P("All results are for **Fri 30 Oct 2026 15:00–15:30 (Melbourne)**, the period reviewed by the methodology owner, on the same data. The final run is **aed29f800b1d**."),
H2("9.1 Categories through the review"),
T(["Run", "Code", "Red", "Amber traffic", "Amber signal", "Normal", "Grey", "Detector Health"], [
  ["eebc0b2964f4", "As reviewed", "–", "–", "–", "–", "790", "692"],
  ["b77b122afab4", "Q1/Q3C precedence fix", "65", "467", "52", "435", "790", "692"],
  ["5065b14ac8a7", "+ one failing detector tolerated", "76", "556", "61", "515", "950", "343"],
  ["**aed29f800b1d**", "**+ PerfKpi/PerfApproach timing fix**", "**44**", "**590**", "**35**", "**542**", "**947**", "**343**"],
], [1.6, 2.6, 0.7, 1, 1, 0.8, 0.7, 1.1]),
P("**Why Red fell from 76 to 44 after the timing fix.** Q3A and Q3B changes largely cancel (cycle stability: 153 sites became normal, 148 abnormal). The decrease comes from Q3C: 333 sites went from abnormal to not assessable because 464 of their approaches dropped from 5 to 4 weeks of valid green share, below the 5-week minimum. With the corrected timing the period uses the 15:37 record, and a reference week whose last quarter-hour is missing (Friday afternoon gaps in the feed) is lost. The Red count is therefore sensitive to single data gaps while the history is at its minimum (Section 10). The per-week coverage is reported by the audit (section 7 of its output)."),
P("**SCATS 976**, the site that started the review, shows both effects. The precedence fix made it Red on the misaligned data. With the correct timing its Cycle Stability is 86.5 against a 10th percentile of 85.0 (normal) and its three approaches have only 4, 4 and 1 weeks of green-share history, so Q3 is NORMAL and the site is **Amber – Traffic Abnormality**, which is the correct result for the data."),
H2("9.2 Independent re-check of the log and snapshot"),
B("Every Q2, Q1, Q3A, Q3B and Q3C result, the two-of-three rule and every category were recomputed from the values stored in the log of aed29f800b1d: **0 differences** in 2,501 sites.",
  "All **14,039** baseline values quoted in the log equal the snapshot (usual value, 10th and 90th percentiles, number of observations); none is missing or NaN.",
  "The run is reproducible: repeated runs of the same period give identical counts."),
H2("9.3 Audit of the inputs"),
P("`python main.py audit` re-reads every input for the period and its reference weeks and classifies what it finds as **implementation** (fixed here), **mapping** (to address progressively with the data owner), **data** (gaps or implausible records) or **operation** (genuine traffic or signal behaviour)."),
T(["Question", "Finding", "Type"], [
  ["Q1", "Approach mapping: PerfApproach links and EGRESS links agree at every site. 1,115 sites have an EGRESS link with no volume in any reference week (left out of Q1, shown as \"Not assessed\"); 277 sites have a TomTom link that is not an EGRESS road.", "Mapping"],
  ["Q1", "17 sites have no current volume on an evaluated link.", "Data"],
  ["Q1", "Daylight saving: reference weeks before and after 4 Oct are aligned to Melbourne local time.", "Confirmed"],
  ["Q2", "Of 1,154 detectors below 10 vehicles, **1,000 (87 %) are usually below 10** at this time too (low-volume movements); 117 are below their usual count, 18 read 0 while usually counting many (possible faults), 19 have no history.", "Operation / data"],
  ["Q2", "1,565 sites have a counting d[n] field for a detector number that Neo4j does not list; 295 have an active Neo4j detector with no record.", "Mapping"],
  ["Q3A/B", "No stored Cycle Stability departs from the KPI formula; no zero cycle length. Records with a cycle length but TotalVolume 0: 10 sites now, 1,906 sites in the history.", "Confirmed / data"],
  ["Q3C", "GreenShare is derived from phase durations (79/79 and 2,597/2,597 consistency checks).", "Confirmed"],
  ["Q3C", "256 approaches without green at Grey sites: 224 have no phase assigned in the current record though they had green in 3–4 reference weeks (phase-to-approach mapping), 26 had an assigned phase that did not run (operation), 6 are at sites with empty records.", "Mapping / operation"],
  ["Q3C", "218 approaches at 100 %: 198 run in every phase recorded at the site (genuine), 20 while another phase ran (check mapping).", "Operation / mapping"],
  ["Q3C", "324 changes of 30 percentage points or more: 251 not determinable because the historical records have no Phases field; 73 have 100 % green records with no volume and no demand in their history (possible empty records).", "Data"],
  ["Timing", "PerfKpi/PerfApproach records describe the quarter-hour before their stamp; the screening used the stamp's quarter-hour.", "Implementation (fixed)"],
  ["Classification", "Q1/Q3 results are translated into categories as specified, including incomplete inputs; every insufficient result keeps its reason.", "Confirmed"],
], [1.5, 6.6, 1.5]),
H2("9.4 Representative intersections"),
T(["SCATS", "What it shows"], [
  ["976", "Precedence fix (any abnormal approach decides) and timing fix; now Amber – Traffic with Q3C not assessable (4, 4 and 1 weeks of history)"],
  ["707", "Cycle Stability 0 as a genuine measurement (CV 39–44 %); phase-to-approach mapping to check (Kendall Road [W] green with zero volume, Ringwood–Warrandyte Road [S] never green); the timing evidence"],
  ["4566", "Two links with the same name told apart; two TomTom approaches mapped to one link (disclosed); partial agreement"],
  ["774", "No Junction Analytics confirmation (no TomTom mapping) but valid link speed with a reference: Wantirna Road [S] 6.6 km/h against 7.0 km/h usually"],
  ["971 d8 / 3912 d3", "A low-volume movement (0 vehicles, usually 0) against a possible fault (0 vehicles, usually 680)"],
  ["991, 979", "Grey because an approach has no phase assigned in the current record"],
  ["559", "100 % green while another phase ran: phase-to-approach mapping to check"],
], [1.6, 8]),
])

# ---------------------------------------------------------------- 10
add([H1("10. Known Limitations and Open Items"),
H3("Data and mapping (data owner)"),
B("Signal Performance KPIs are missing for 455 screened sites (596 network-wide), which are therefore Grey.",
  "IntersectionPerfApproach before about 20 Oct 2026 has HasGreen = 0 on every approach, and historical records have no Phases field: Q3C history is short (1,431 of 1,876 screened sites cannot assess Q3C) and many large changes cannot be explained from history.",
  "The baseline is at its minimum: no value has more than 6 of the 7 reference weeks and about half have exactly 5, because of Friday afternoon gaps. One more gap makes many sites not assessable (Section 9.1).",
  "Neo4j detector lists against the d[n] fields (1,565 and 295 sites); unnamed `STNA…` links; the phase-to-approach mapping at sites such as 707 and 559; the TomTom mapping at 4566.",
  "Whether the 5-minute detector records are also written after their interval (the Q2 window would move by 5 minutes)."),
H3("Methodology owner"),
B("(A) An approach without green: keep the site Grey, treat the approach as not assessable, or treat a recorded HasGreen = 0 as 0 % green (14 sites would become Red).",
  "(C) Q3B: keep the stored Cycle Stability (floored at 0, no minimum difference) or change the method.",
  "(D) Whether the log's abnormality sections should list Grey sites with an abnormal finding.",
  "Q3C sensitivity: an assessable site is abnormal in most cases (420 abnormal, 25 normal) because the 10th–90th range of 5–6 weeks is narrow and any abnormal approach decides; the methodology adds no materiality threshold.",
  "A comparison of Q3C with raw SCATS phase timing (`site_phase`) has not been done."),
H3("Production"),
B("Screen a period from 10 minutes after it ends; the cache key, S3 location, audit fields and D002 registry ID listed in Section 8."),
])

# ---------------------------------------------------------------- 11
add([H1("11. Configuration and Environment"),
T(["Setting (rules.json)", "Value", "Meaning"], [
  ["history.weeks / min_observations", "8 / 5", "Reference weeks; minimum valid observations"],
  ["percentiles.low / high; reference_value", "0.10 / 0.90; median", "Normal range and usual value"],
  ["data_latency_minutes", "10", "A period is screened this long after it ends"],
  ["alignment.written_after_interval", "site_kpi, approach_perf", "Records that describe the quarter-hour before their stamp"],
  ["q2.min_vehicles / tolerated_failed_detectors", "10 / 1", "Detector threshold; failing detectors tolerated per site"],
  ["q1.min_pct_difference, q3a.min_pct_difference", "10", "Minimum difference from usual"],
  ["q1.grey_if_any_approach_missing", "true", "A missing approach withholds NORMAL"],
  ["q3c.grey_site_if_any_approach_without_green", "true", "An approach without green makes the site Grey"],
  ["q3.abnormal_required / assessable_required", "2 / 2", "Two of three"],
  ["tomtom.ranked_delays / delay_mean / negative_delay", "control, approach / plain / zero", "Q5 rankings"],
  ["tomtom.api_enabled / queue_min_minutes", "true / 15", "Junction Analytics queue"],
  ["link_speed.categories / reference_from_history", "amber, red / true", "Supplementary link speed"],
  ["click", "red: D001, D002", "What a click runs"],
], [3.6, 2.4, 3.6]),
T(["Environment variable", "Purpose"], [
  ["INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG", "InfluxDB"],
  ["NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD", "Neo4j"],
  ["TOMTOM_API_KEY, TOMTOM_QUEUE_*", "Junction Analytics queue archive"],
  ["OPENAI_API_KEY, OPENAI_MODEL", "Optional LLM wording"],
  ["DIAGNOSTICS_DB, DIAGNOSTICS_ARCHIVE", "SQLite store; S3 URL or folder for logs and snapshots"],
], [4.6, 5]),
])

# ---------------------------------------------------------------- 12
add([H1("12. Running, Checking and Releasing"),
T(["Command", "Purpose"], [
  ["python main.py screen --end 2026-10-30T15:30 [--force]", "Screen a period"],
  ["python main.py diagnose --run ID --site N", "Report for a Red site"],
  ["python main.py map", "Local map viewer"],
  ["python main.py summary [--run ID]", "Why sites got their category, with the review checks"],
  ["python main.py stats --end …", "Every check counted on its own for every site (JSON + CSV)"],
  ["python main.py audit --end …", "Input audit with problem types and example intersections"],
  ["python main.py kpi-check --site N --end …", "Every stored PerfKpi/PerfApproach field with the link volumes"],
  ["python main.py inspect --site N --end … [--history]", "Feed inspection and the history behind the baseline"],
  ["python main.py examples --run ID --site … --red N", "Example outputs per category (Markdown and HTML)"],
  ["python main.py export-run --run ID", "The screening log and baseline snapshot as plain JSON"],
  ["python main.py contract-check", "Validate a stored run against the production contract"],
  ["python main.py baseline --days 7", "The weekly baseline job"],
  ["python tools/build_production.py [--check]", "Build (or check) the production package"],
  ["python -m unittest", "160 tests, including the production package check"],
], [4.6, 5]),
P("A rule change is made in rules.json and documented in METHOD.md; the rules hash and, where relevant, the baseline version change with it, so runs and baselines are recomputed. The production package is rebuilt and checked by the tests before release."),
])

doc = {"title": "Intersections Diagnostics V1", "subtitle": "Technical Design & Implementation Guide",
       "tagline": "Network screening (Q1–Q3) and on-demand diagnosis (Q4–Q5) — Neo4j + InfluxDB + TomTom, deterministic classification with checked LLM wording",
       "meta": ["Document version: 1.0", "Date: 5 November 2026",
                "Methodology: Intersections Diagnostics V1 (M. Sarvi), incl. \"Speed added\" (2 Nov 2026)",
                "Audience: Methodology owner, Implementation / Production Engineering Team"],
       "body": body}
json.dump(doc, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
