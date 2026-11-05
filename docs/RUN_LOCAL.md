# Running locally

## 1. Setup

```powershell
git clone -b claude/busy-volta-of5gyv https://github.com/HaileyHYoo/intersection_diagnostic.git
cd intersection_diagnostic
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env      # fill in the chatbot's .env values (InfluxDB, Neo4j, OpenAI)
```

Also set `TOMTOM_API_KEY` in `.env` (the same key as the chatbot's TomTom features); it is used for the queue archive.

Without an OpenAI key, or with `--no-llm`, the D001/D002 wording is written by code. Numbers and verdicts are always calculated by code.

## 2. End-to-end check on synthetic data

```powershell
python main.py --no-llm demo --serve
```

- Screens 48 synthetic intersections (around the Melbourne CBD) and checks that each scenario gets its intended category:
  - Red 4, Amber 2, Grey 4, Detector Health 1, Normal.
- Prints the report of the first Red intersection.
- Writes `out/demo_map.html`, which shows the evidence without a server.
- With `--serve`, opens the map at http://127.0.0.1:8765; clicking a Red site runs D001 + D002.

## 3. Live-data check (do this first)

```powershell
python main.py inspect --site 4397 --end 2026-10-27T08:30 --hours 2
```

This prints a summary and saves `out/inspect_S4397_<time>.json`. Check the following (details in SCHEMA.md):

| Check | Where |
|---|---|
| `d[n]` numbering equals Neo4j `detector_number` | `checks.detectors`: both `active_without_field` and `fields_without_neo4j_detector` empty |
| `scats/volume` value types | `feeds.detector_counts.value_types` |
| Timestamps label the end of the interval | each feed's `last` equals the window end |
| Pattern of off-grid records | `offset_within_step`, `on_grid` |
| EGRESS links have volume and GreenShare | `checks.links` |
| TomTom mapping and queue archive are readable | `checks.tomtom` (the `tomtom:` line of the summary) |

Depending on the result, change values in `diagnostics/config/schema.json` or `rules.json` only; no code change is needed.

## 4. Live screening and map

```powershell
python main.py map                                    # http://127.0.0.1:8765, latest 30 minutes
python main.py screen --end 2026-05-12T08:30          # a past period (history = the 8 weeks before it)
python main.py summary                                # why sites got their category in the latest run, plus REVIEW (methodology owner's checks)
python main.py kpi-check --site 707 --end 2026-10-30T15:30 --references 3   # every stored PerfKpi/PerfApproach field per quarter-hour
python main.py audit --end 2026-10-30T15:30          # Q1-Q3 input audit: problem types with example intersections (read only)
python main.py stats --end 2026-10-30T15:30          # every check counted on its own for every site, without gates (JSON + CSV)
python main.py export-run --run <run_id>              # the screening log and baseline snapshot as plain JSON (out/export_<run_id>/)
python main.py inspect --site 994 --end 2026-10-30T15:00 --history   # history per reference week and approach (why values are missing)
python main.py diagnose --run <run_id> --site 4397    # report for a Red site
python main.py export-html --run <run_id> --out out/map.html
python main.py baseline --days 7                      # precompute the weekly baseline and write the weekly baseline snapshot
python main.py site-history --site 4397 --from 2026-10-01 --to 2026-10-31   # categories over the logged periods
python main.py archive --run <run_id>                 # rewrite the log of a run whose log write failed
python main.py contract-check                         # validate the latest stored run against the production contract (Pydantic)
python main.py examples --site 4566 4564 774 --red 3  # example outputs per category in out\examples_<run>.md / .html
python main.py watch                                  # (later extension) screen every 30 minutes; Ctrl+C to stop
python main.py backfill --from 2026-10-26T07:00 --to 2026-10-26T10:00   # (later extension) screen past periods one by one
```

- **Records (methodology §18).** Every completed screening writes one JSON log, and the baseline it used goes into the weekly snapshot, under `DIAGNOSTICS_ARCHIVE`. The default is an `archive/` folder next to the database; production uses `s3://bucket/prefix`. Existing files are never overwritten.
  - `archive/screening-logs/AU-VIC-Melbourne/2026/10/30/1430_<run_id>.json`
  - `archive/baselines/AU-VIC-Melbourne/2026-W44.<method version>/Friday/1430.json.gz`
- **Link speed (supplementary).** Clicking an Amber or Red site shows the TomTom speed of its incoming (EGRESS) links (`aimes/speed`, harmonic mean over the same 30 minutes) and the reference speed (median of the same 30 minutes in the reference weeks). For Red it is in section 3 of the report. It is never used for the classification. The `link speed (period)` line of `inspect` shows the live data.
- Synthetic data (`demo`, `--fake`) is stored separately in `out/demo_archive/`, so it never mixes with live records.
- Times without an offset are Melbourne local time.
- The first run reads 8 weeks of reference periods and can take a while; later runs use the values cached in SQLite (`diagnostics.sqlite3`).

## 5. Changing rules

Every threshold and switch is in `diagnostics/config/rules.json`.

| Item | Default |
|---|---|
| Q2 minimum vehicles | `q2.min_vehicles` 10 |
| Percentage threshold | `q1.min_pct_difference` 10 |
| Grey when an approach has no green | `q3c.grey_site_if_any_approach_without_green` true |
| Grey when an approach has no volume | `q1.grey_if_any_approach_missing` true |
| Days left out of the history | `history.exclude` (public holidays, DST change days, year end) |
| Data latency allowance | `data_latency_minutes` 10 (the Q3 records are written about 7 minutes after their quarter-hour) |
| Feeds written after their quarter-hour | `alignment.written_after_interval` (IntersectionPerfKpi, IntersectionPerfApproach) |
| Templates run on a click | `click` (D001 and D002 for Red only) |
| Usual value | `reference_value` `"median"` (as in the production contract) |
| TomTom queue (API) | `tomtom.api_enabled` true (methodology §13); needs `TOMTOM_API_KEY` in `.env`, otherwise only the queue is "unavailable" |
| Reference link speed | `link_speed.reference_from_history` true |
| Production template IDs | `contract.template_ids` (the D002 ID is a placeholder until confirmed) |

When the rules or schema version change, baselines and runs are recalculated automatically.

## 6. Building the production package

```powershell
python tools/build_production.py          # build production/ and check the imports
python tools/build_production.py --check  # check that it matches the source
```
