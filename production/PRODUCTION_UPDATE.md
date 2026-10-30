# Production update — Intersections Diagnostics V1

**For:** the production / system team
**Package:** `production/dash_backend/ai_brains/intersections/diagnostics/`. It is generated from `diagnostics/` by `python tools/build_production.py`; do not edit it by hand.
**Host impact:** a new package next to `tomtom/`. Nothing in the existing chatbot changes.

## 1. What it does

| Call | When | Returns |
|---|---|---|
| `screen()` | The map layer is activated, or the layer is refreshed while active | One category per intersection for the latest completed 30 minutes |
| `screen(period_end)` | A chosen past period | The same, compared with the 8 weeks before that day |
| `diagnose(run_id, site)` | Click on an intersection | **Red:** the four-section report from templates D001 + D002. **Any other category:** the saved evidence |
| `site_evidence(run_id, site)` | Any time | The saved Q2/Q1/Q3 evidence for one site |
| `refresh_baselines(days)` | Weekly job | Precomputed 8-week baselines |

`screen()`:
- returns the saved run when one exists for the same region, period, baseline version and rules version, so users share it;
- waits for a run already in progress rather than starting a second one;
- does not run on a timer. Screening runs only when the host asks.

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
| `config/schema.json`, `config/rules.json` | Data schema (temporary) and rules |
| `data/` | TomTom approach ↔ link mapping (from the chatbot) and the site ↔ subsystem map (fallback only) |

## 3. Dependencies and environment

**Dependencies.** No new packages beyond the chatbot's: `influxdb-client`, `neo4j`, `python-dotenv`, `tzdata` (and `openai` through the host client).

**Environment.** The same variables as the chatbot, plus:

| Variable | Default | Purpose |
|---|---|---|
| `DIAGNOSTICS_DB` | `diagnostics.sqlite3` (working directory) | SQLite file for runs, baselines and reports. Use a persistent, writable path. |
| `DIAGNOSTICS_SCHEMA_FILE` | bundled `config/schema.json` | Your schema file, once it replaces the temporary one |
| `DIAGNOSTICS_RULES_FILE` | bundled `config/rules.json` | Only if the rules are managed outside the package |

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

## 5. Verification

```python
from dash_backend.ai_brains.intersections.diagnostics.templates import catalog
assert set(catalog()) == {"D001", "D002"}
from dash_backend.ai_brains.intersections.diagnostics.host import service_for_bot
view = service_for_bot().screen()
print(view["counts"], view["period"]["local"])
```

## 6. To agree with the production team

- **Schema.** Replace `config/schema.json` with the final schema (see SCHEMA.md) and change its `version`.
- **Store.** Use SQLite on a persistent path, or a database. `store.SQLiteStore` is the interface to re-implement.
- **Call pattern.** The interface is Python functions returning JSON. An HTTP endpoint can wrap them if the UI needs one.
- **Map display.** Colours and icons per category, and whether Normal is drawn.
