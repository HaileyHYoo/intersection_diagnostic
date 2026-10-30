# Temporary data schema

`diagnostics/config/schema.json` names every bucket, measurement, field and tag the code reads. It was designed from:

- the InfluxDB inventory of 5 Oct 2026;
- the intersection chatbot's Neo4j queries and TomTom mapping.

When the production team's schema arrives, either edit this file or point `DIAGNOSTICS_SCHEMA_FILE` at a new one. Change the `version` value as well, so that cached baselines and runs are rebuilt. No code change is needed as long as each feed keeps the same role.

## Feeds

| Key | Used by | Bucket / measurement | Identity | Fields | Interval |
|---|---|---|---|---|---|
| `detector_counts` | Q2 | `scats` / `volume` (raw) | `SiteNo` plain (`4397`) | `d[1]` … `d[48]` (n = `Detector.detector_number`) | 5 min |
| `link_volume` | Q1 | `scats-aggregation` / `volume`, `MinutesPast=15` | `DetectorGroupId` = `Road.link_id` | `Volume` | 15 min |
| `site_kpi` | Q3A, Q3B | `scats-aggregation` / `IntersectionPerfKpi`, `MinutesPast=15` | `SiteNo` `S4397` | `AvgCycle`, `CycleStability` | 15 min |
| `approach_perf` | Q3C | `scats-aggregation` / `IntersectionPerfApproach` | `SiteNo`, `LinkId`, `Bound` | `GreenShare` (%), `HasGreen` | 15 min |
| `tomtom_site_kpi` | D002 | `scats-aggregation` / `IntersectionKpi`, `Provider=TomTom` | `SiteNo` | `ControlDelaySec`, … | 15 min |
| `tomtom_turn_kpi` | D002 | `scats-aggregation` / `IntersectionTurnKpi`, `Provider=TomTom` | `SiteNo`, `ApproachId`, `ExitId` | `ApproachDelaySec`, `ControlDelaySec`, `MultiStopRate`, `TurnRatioPct`, `SampleCount` | 15 min |
| `tomtom_queue` (`tomtom.api_enabled`, on) | D002 queue | TomTom Junction Analytics archive, `…/archive/{junction_uuid}/data/flat/daily` | junction UUID from the mapping file, `approachId` | `queueLengthMeters` | 1 min |
| fallback `cycle_length` (off) | Q3A | `scats` / `subsystem_status` | `RegionNo`, `SubsystemNo` | `ActiveCycleLength` | — |

Neo4j queries are in `graph`:
- `sites`: Intersection in the Region, with latitude, longitude and street names;
- `detectors`: BELONG_TO, with `detector_number` and `active`;
- `approaches`: EGRESS `Road.link_id` and `street_name`.

## Rules every query follows

- **Region tag.** Every Flux query filters on the `Region` tag. SCATS site numbers repeat across cities: Melbourne shares 188 numbers with Riyadh and 68 with Doha.
- **No aggregation in Flux.** Some feeds mix integer and string types ("schema collision" in the inventory). Records are read raw, converted in Python and put on the grid by `series.py`.
- **ID normalisation.** Site numbers are normalised to the plain number. Link IDs lose the characters listed in `ids.strip_chars` (quotes, back-quote, spaces) at both ends only. A leading apostrophe added by spreadsheet auto-formatting is removed, and characters inside an ID are kept.
- **Logical field names.** Field names above the source layer are logical (`cycle_length`, `green_share`, …), so a renamed field is one edit in the schema.

## Still to confirm on live data

Run this for a few sites and periods. It writes `out/inspect_S<site>_<time>.json` and only reads from the databases:

```bash
python main.py inspect --site 4397 --end 2026-10-27T08:30 --hours 2
```

| Check | Where in the report | If it fails |
|---|---|---|
| `d[n]` is `Detector.detector_number` | `checks.detectors`: the active Neo4j detectors equal `fields_with_nonzero_counts` (unused fields `d[9]`… are zero) | Change `detector_field` or the `detectors` query |
| Value types of `scats/volume` | `feeds.detector_counts.value_types` | Nothing to change: strings are converted, and anything non-numeric is missing |
| Stamps are interval ends | `checks.timestamps`: each feed's `last` equals the window end | Set the feed's `timestamp_label` |
| Off-grid stamps | `feeds.*.offset_within_step`, `on_grid` | Nothing to change with `off_grid: "ceil"`; check `period_values` |
| EGRESS links have volume and green share | `checks.links` | Check the link ID format and `ids.strip_chars` |
| What the screening would use | `checks.period_values`: no `None` for Q2 detectors, Q1 volumes, Q3 KPIs, Q3C green | A `None` means the site would be Grey |
| TomTom queue time format | `checks.tomtom.queue_time_format` | If stamps have no offset and are not UTC, set `tomtom_queue.naive_timestamp_timezone` |

**Results for site 4397, 30 Oct 2026 (UTC 01:30–03:30):**
- confirmed: `d[n]` = detector number (1–8); detector counts are integers; the three EGRESS links have volume and green share; the 15-minute volumes are end-labelled; the TomTom mapping and queue archive work (3 approaches, 1 row per minute);
- found: detector counts are stamped at :03/:08 and PerfKpi/PerfApproach at :07/:22, which is now handled with `off_grid: "ceil"`;
- confirmed in a second run (UTC 23:00–01:00): the TomTom KPIs are end-labelled (the latest quarter can arrive a few minutes late); the TomTom queue archive stamps carry `Z` (UTC); every value the screening needs for the period is present.
- observed:
  - detector 1 at 4397 counts 1–2 vehicles per hour, so this site is a Detector Health Issue under the Q2 rule at both times;
  - `d[12]` counted traffic but is not associated with the site in Neo4j, so it is not part of Q2;
  - GreenShare is 100% on two of the three approaches (once stored as 99.99999999999999). Green share is rounded to 3 decimals (`q3c.round_decimals`) so that float noise is not read as LOW against a 100–100 range.
- still open: whether a PerfKpi record stamped :07 covers the 15 minutes up to :07 (the reading used) or an earlier quarter written late — a question for the production team.

