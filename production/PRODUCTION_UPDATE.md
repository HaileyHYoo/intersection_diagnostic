# Production update — Intersections Diagnostics V1

**For:** the production / system team
**Package:** `production/dash_backend/ai_brains/intersections/diagnostics/`. It is generated from `diagnostics/` by `python tools/build_production.py`; do not edit it by hand.
**Host impact:** a new package next to `tomtom/`. Nothing in the existing chatbot changes.

## 1. What it does

Intersections Diagnostics V1 (methodology "speed added", Nov 2026). Level 1 screens every signalised site for the latest completed 30 minutes (Q2 → Q1 + Q3, Normal / Amber / Red / Grey / Detector Health). A click on an Amber site shows its evidence and TomTom link speed; a click on a Red site also runs Q4 (D001) and Q5 (D002) for the four-section report. The classification is deterministic; the LLM only rewords answers written by code, under a guard.

**Use it through your contract** (`contract/intersections_diagnostics_schemas.py`, your Nov 2026 file, copied unchanged). Every result validates against your models; on 2 Nov 2026 all 2,501 live sites passed (`ScreeningResult`, Grey reasons, decision matrix, 2-of-3 rule).

| Your callback | Call (`diagnostics.host`) | Contract models |
|---|---|---|
| Layer activation / refresh, after writing the RUNNING `ScreeningRun` | `run_screening(screening_input)` | `ScreeningInput` → `ScreeningResult` (+ `BaselineSnapshot` of the slot in S3) |
| After writing the COMPLETED `ScreeningRun` | `log_screening(screening_run)` | `ScreeningLog` in S3 (18.3), once per run |
| Click on an Amber or Red site | `run_site_report(site_report_request, screening_run, bot)` | `SiteReportRequest` + `ScreeningRun` → `SiteReport` (Amber: evidence + `LinkSpeedReport`; Red: + `DiagnosisResult`, and the `SiteReport` kept in S3, 18.2) |
| Weekly refresh (e.g. Sunday night) | `weekly_baseline_job("2026-W45")` | 8-week baselines for the coming week, `BaselineSnapshot` files named with your `baseline_version` (18.4) |

`run_diagnosis(DiagnosisInput)` and `run_link_speed(evidence, period)` are also available on their own. A local service with its own SQLite run store (`service_for_bot(bot)`, section 4) exists too; it is what the local map viewer uses.

## 2. Files

Copy `production/dash_backend/ai_brains/intersections/diagnostics/` into the backend's `dash_backend/ai_brains/intersections/` (without `__pycache__` folders).

| Path | Purpose |
|---|---|
| `host.py` | Entry points: `run_screening`, `log_screening`, `run_site_report`, `weekly_baseline_job`, `run_diagnosis`, `run_link_speed`; `service_for_bot(bot)` for the local-store service |
| `contract/` | Your contract (unchanged), `adapter.py` (our records ↔ your models) and `core.py` (the contract-path logic) |
| `screening.py`, `measures.py`, `baseline.py`, `stats.py`, `series.py`, `timewin.py`, `vic_calendar.py`, `ids.py` | Level 1 (deterministic) |
| `templates/` | D001 (Q4) and D002 (Q5), `catalog.json` with both definitions |
| `report.py`, `llm.py` | Report assembly and the LLM guard (the chatbot's LLM client) |
| `link_speed.py`, `arms.py` | Supplementary TomTom link speed; arm numbers from your operational-sheet modules |
| `sources/` | InfluxDB and Neo4j readers built from the schema; `tomtom_queue.py` for the Junction Analytics queue archive |
| `archive.py` | S3 (or folder) records: logs, Red site reports, baseline snapshots; reading them back |
| `store.py` | SQLite: cached reference values and baselines, audit records (config snapshots, data provenance) |
| `service.py`, `schedule.py` | Local-store service; scheduled screening for a later version (not used in V1) |
| `config/schema.json`, `config/rules.json` | Data schema and every threshold/switch |
| `data/` | TomTom approach ↔ link mapping (identical to your TomTom layer's file) and the site ↔ subsystem map (fallback, off) |

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

## 4. Local-store service (alternative)

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

# weekly refresh, with the baseline_version your ScreeningInput will use that week
weekly_baseline_job("2026-W45")                    # BaselineSnapshot files baselines/{region}/2026-W45/... (18.4)
```

`run_diagnosis(DiagnosisInput)` and `run_link_speed(evidence, period)` remain available on their own.

- **The contract module.** The adapter uses its bundled copy of `intersections_diagnostics_schemas.py`. To share one set of classes with the host, call `contract.adapter.use_contract(<the host's module>)` once at start-up.
- **Audit records.** `host.run_screening` / `host.run_site_report` pass a SQLite store as `audit_store`. Each call saves an audit record (config snapshot, data provenance, registry template IDs, who wrote each answer) that the contract has no field for. If the contract gains the optional fields `generated_by`, `llm_rejected`, `config_version` and `audit_ref`, they are filled automatically (see METHOD.md §11).
- **S3 layout** (`DIAGNOSTICS_ARCHIVE=s3://bucket/prefix`; nothing is overwritten):
  - `screening-logs/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}.json`: `ScreeningLog`
  - `site-reports/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}_{site}.json`: `SiteReport` of a Red site
  - `baselines/{region}/{baseline_version}/{weekday}/{HHMM}.json.gz`: `BaselineSnapshot` of one weekday and slot
- **Check before going live:** section 5 in the backend, or `python main.py contract-check` in the development repository (validates every site of a stored live run against the contract).

## 5. Verification (in the backend)

```python
from datetime import datetime
from dash_backend.ai_brains.intersections.diagnostics import host
from dash_backend.ai_brains.intersections.diagnostics.contract import adapter
from dash_backend.ai_brains.intersections.diagnostics.settings import Settings
from dash_backend.ai_brains.intersections.diagnostics.timewin import latest_period
S = adapter.S
period = latest_period(Settings().rules)
result = host.run_screening(S.ScreeningInput(run_id="check", region="AU-VIC-Melbourne", period=adapter.period_model(period),
                                             baseline_version="2026-W45", sites=[]))
print(len(result.sites), "sites,", len(result.errors), "errors")    # expect ~2,500 sites and no errors
```

`adapter.use_contract(<your schemas module>)` once at start-up makes the package use your classes instead of its bundled copy.

**Data notes from the live checks (2 Nov 2026).** Q3C (phase service) has little valid history before about 20 Oct (`HasGreen = 0` placeholders), so it is mostly not assessable until late November. Several 16:00–17:00 periods in September–October have no `scats-aggregation` outputs, which makes many sites Grey in those slots (asked of the data team). Both are data, not code.

## 6. To agree with the production team

The Nov 2026 contract covers the no-green Grey flag, `has_largest_queue: bool | None`, link speed, `SiteReport` and the S3 records; the code uses all of them. Still open (METHOD.md §12):

- **Cache key.** Time zone of `period_end` (a UTC key), and a rules/config hash in the key or the `baseline_version`.
- **Audit fields.** The optional fields above, or where audit records should live.
- **S3.** The bucket and prefix for `DIAGNOSTICS_ARCHIVE`.
- **Baseline snapshot size.** One `BaselineSnapshot` per weekday and slot (as written now) rather than one per week.
- **Template registry.** D002's ID `ID_Q5_TOMTOM_CONFIRMATION` (rules.json `contract.template_ids`) is a placeholder; please confirm or replace it.
- **Link speed.** An existing historical reference speed (`schema.influx.sources.link_speed_reference` is ready for it). `LinkSpeed.arm` reuses the backend's operational-sheet modules (`db.operational_sheet_client`, `operational_sheet`, `operational_sheet_store`), as the TomTom layer does; no new configuration.

- **Schema.** Replace `config/schema.json` with the final schema (see SCHEMA.md) and change its `version`.
- **Store.** Use SQLite on a persistent path, or a database. `store.SQLiteStore` is the interface to re-implement.
- **Call pattern.** The interface is Python functions returning JSON. An HTTP endpoint can wrap them if the UI needs one.
- **Map display.** Colours and icons per category, and whether Normal is drawn.
