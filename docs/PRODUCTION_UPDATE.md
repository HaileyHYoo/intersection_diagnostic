# Production update — Intersections Diagnostics V1

**For:** the production / system team
**Package:** `production/dash_backend/ai_brains/intersections/diagnostics/`. It is generated from `diagnostics/` by `python tools/build_production.py`; do not edit it by hand.
**Host impact:** a new package next to `tomtom/`. Nothing in the existing chatbot changes.

## 1. What it does

The host can use the package in either of two ways:

- the service below, which keeps its own run store (SQLite);
- the production contract (`contract/`, section 4b), where the Dash callbacks keep the shared run store.

| Call | When | Returns |
|---|---|---|
| `screen()` | The map layer is activated, or the layer is refreshed while active | One category per intersection for the latest completed 30 minutes |
| `screen(period_end)` | A chosen past period | The same, compared with the 8 weeks before that day |
| `diagnose(run_id, site)` | Click on an intersection | **Red:** the four-section report from templates D001 + D002. **Any other category:** the saved evidence |
| `site_evidence(run_id, site)` | Any time | The saved Q2/Q1/Q3 evidence for one site |
| `refresh_baselines(days)` | Weekly job | Precomputed 8-week baselines, and the weekly baseline snapshot in the archive |
| `archive_run(run_id)` | After an archive outage | Writes a run's screening JSON log if it is missing |

`screen()`:
- returns the saved run when one exists for the same region, period, baseline version and rules version, so users share it;
- waits for a run already in progress rather than starting a second one;
- does not run on a timer. Screening runs only when the host asks (V1). `schedule.run_scheduled` / `schedule.backfill` exist for a later version that screens every period;
- writes one screening JSON log per completed run and keeps the weekly baseline snapshot (methodology 18.3/18.4) in `DIAGNOSTICS_ARCHIVE`.

## 2. Files

Copy `production/dash_backend/ai_brains/intersections/diagnostics/` into the backend's `dash_backend/ai_brains/intersections/`.

| Path | Purpose |
|---|---|
| `host.py` | `service_for_bot(bot)`: one service per process, using the chatbot's LLM client |
| `service.py` | `screen`, `diagnose`, `site_evidence`, `refresh_baselines` |
| `screening.py`, `measures.py`, `baseline.py`, `stats.py`, `series.py`, `timewin.py`, `vic_calendar.py`, `ids.py` | Level 1 (deterministic) |
| `templates/` | D001 (Q4) and D002 (Q5), `catalog.json` with both definitions |
| `report.py`, `llm.py` | Report assembly and the LLM guard |
| `sources/` | InfluxDB and Neo4j readers built from the schema |
| `store.py` | SQLite store (runs, baselines, diagnoses) |
| `archive.py` | Screening JSON logs and weekly baseline snapshots (S3 or a folder), and reading them back |
| `schedule.py` | Later extension: scheduled screening and back-calculation |
| `config/schema.json`, `config/rules.json` | Data schema (temporary) and rules |
| `contract/` | The production team's `intersections_diagnostics_schemas.py` (copied unchanged), `adapter.py` (conversion) and `core.py` (`run_screening`, `run_diagnosis`) |
| `sources/tomtom_queue.py` | TomTom Junction Analytics queue archive (Q5 queue length; `tomtom.api_enabled`, on) |
| `data/` | TomTom approach ↔ link mapping (from the chatbot) and the site ↔ subsystem map (fallback only) |

## 3. Dependencies and environment

**Dependencies.** No new packages beyond the chatbot's: `influxdb-client`, `neo4j`, `python-dotenv`, `tzdata`, `pydantic` (v2, for the contract), and `openai` through the host client. `boto3` (1.35 or later, for conditional writes) is needed only when the archive is on S3.

**Environment.** The same variables as the chatbot, plus:

| Variable | Default | Purpose |
|---|---|---|
| `DIAGNOSTICS_DB` | `diagnostics.sqlite3` (working directory) | SQLite file for runs, baselines and reports. Use a persistent, writable path. |
| `DIAGNOSTICS_ARCHIVE` | `archive/` next to the SQLite file | **`s3://bucket/prefix`** for the screening JSON logs and baseline snapshots (methodology 18.3/18.4). Needs `s3:PutObject`, `s3:GetObject` and `s3:ListBucket`; AWS credentials as usual for boto3. `off` disables it. |
| `DIAGNOSTICS_SCHEMA_FILE` | bundled `config/schema.json` | Your schema file, once it replaces the temporary one |
| `DIAGNOSTICS_RULES_FILE` | bundled `config/rules.json` | Only if the rules are managed outside the package |
| `TOMTOM_API_KEY` | — | **Needed for the Q5 queue length** (methodology section 13). The chatbot's TomTom layer already uses it. Without it, Q5 reports the queue as unavailable. |

## 4. Host code

```python
from dash_backend.ai_brains.intersections.diagnostics.host import service_for_bot

svc = service_for_bot(bot)                 # bot: the SCATSQaBot instance

# layer activation / refresh
view = svc.screen()                        # {"run_id", "period", "counts", "sites": [{site, name, lat, lon, category, label, reasons, selectable}], ...}

# click
result = svc.diagnose(view["run_id"], site)
if result["mode"] == "report":             # Red: D001 + D002
    sections = result["report"]["sections"]   # 4 sections: title, text, bullets, tables
    markdown = result["report"]["markdown"]
else:                                      # other categories: saved evidence (Q2/Q1/Q3 tables)
    evidence = result["site"]
```

**Categories:** `red`, `amber_traffic`, `amber_signal`, `normal`, `grey`, `detector_health`. Labels are in `view["categories"]`. How to draw them (including whether to show Normal) is the UI's decision.

**Weekly baseline job.** Schedule this once a week, for example on Sunday night:

```bash
python -c "from datetime import date, timedelta; from dash_backend.ai_brains.intersections.diagnostics.host import service_for_bot; s = service_for_bot(); print(s.refresh_baselines([date.today() + timedelta(days=i) for i in range(7)]))"
```

## 4b. With the production contract

```python
from dash_backend.ai_brains.intersections.diagnostics.host import run_screening, run_site_report, log_screening

# background callback, after writing the RUNNING ScreeningRun
result = run_screening(screening_input)            # ScreeningInput -> ScreeningResult (+ BaselineSnapshot in S3)
# ... after writing the COMPLETED ScreeningRun
log_screening(screening_run)                       # ScreeningLog in S3 (18.3), once per run

# click on an Amber or Red site
report = run_site_report(site_report_request, screening_run, bot)   # SiteReportRequest + ScreeningRun -> SiteReport
# Amber: evidence + link_speed; Red: also diagnosis (Q4/Q5), and the SiteReport is kept in S3 (18.2)
```

`run_diagnosis(DiagnosisInput)` and `run_link_speed(evidence, period)` remain available on their own.

- **The contract module.** The adapter uses its bundled copy of `intersections_diagnostics_schemas.py`. To share one set of classes with the host, call `contract.adapter.use_contract(<the host's module>)` once at start-up.
- **Audit records.** `host.run_screening` / `host.run_site_report` pass a SQLite store as `audit_store`. Each call saves an audit record (config snapshot, data provenance, registry template IDs, who wrote each answer) that the contract has no field for. If the contract gains the optional fields `generated_by`, `llm_rejected`, `config_version` and `audit_ref`, they are filled automatically (see METHOD.md §11).
- **S3 layout** (`DIAGNOSTICS_ARCHIVE=s3://bucket/prefix`; nothing is overwritten):
  - `screening-logs/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}.json`: `ScreeningLog`
  - `site-reports/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}_{site}.json`: `SiteReport` of a Red site
  - `baselines/{region}/{baseline_version}/{weekday}/{HHMM}.json.gz`: `BaselineSnapshot` of one weekday and slot
- **Check before going live:** `python main.py contract-check` validates every site of a stored live run against the contract.

## 5. Verification

```python
from dash_backend.ai_brains.intersections.diagnostics.templates import catalog
assert set(catalog()) == {"D001", "D002"}
from dash_backend.ai_brains.intersections.diagnostics.host import service_for_bot
view = service_for_bot().screen()
print(view["counts"], view["period"]["local"])
```

## 6. To agree with the production team

The Nov 2026 contract covers the no-green Grey flag, `has_largest_queue: bool | None`, link speed, `SiteReport` and the S3 records; the code uses all of them. Still open (METHOD.md §12):

- **Cache key.** Time zone of `period_end` (a UTC key), and a rules/config hash in the key or the `baseline_version`.
- **Audit fields.** The optional fields above, or where audit records should live.
- **S3.** The bucket and prefix for `DIAGNOSTICS_ARCHIVE`.
- **Baseline snapshot size.** One `BaselineSnapshot` per weekday and slot (as written now) rather than one per week.
- **Link speed.** `LinkSpeed.arm` mapping if needed; an existing historical reference speed (`schema.influx.sources.link_speed_reference` is ready for it).

- **Schema.** Replace `config/schema.json` with the final schema (see SCHEMA.md) and change its `version`.
- **Store.** Use SQLite on a persistent path, or a database. `store.SQLiteStore` is the interface to re-implement.
- **Call pattern.** The interface is Python functions returning JSON. An HTTP endpoint can wrap them if the UI needs one.
- **Map display.** Colours and icons per category, and whether Normal is drawn.
