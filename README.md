# Intersections Diagnostics V1

Network-wide SCATS screening (Q2 detector gate, Q1 traffic, Q3 signal operation) with an on-demand diagnosis of a selected Red intersection (D001 = Q4 SCATS interpretation, D002 = Q5 TomTom confirmation), following the agreed V1 methodology of 29 Oct 2026.

- **Level 1** is deterministic code. It returns one category per intersection: Red, Amber (traffic or signal), Normal, Grey (insufficient data) or Detector Health Issue.
- **Level 2** runs only when a Red site is clicked. Code computes every number, and the LLM may only re-word the code's answer within the evidence.

| Path | Contents |
|---|---|
| `diagnostics/` | The package (shared source of local and production) |
| `diagnostics/config/` | `schema.json` (temporary data schema), `rules.json` (every threshold and switch) |
| `diagnostics/local/` | Local only: synthetic network, map viewer, feed inspection |
| `main.py` | Local command line |
| `production/` | Generated package for the backend (`python tools/build_production.py`) |
| `docs/METHOD.md` | How the code implements the methodology, with every agreed decision |
| `docs/SCHEMA.md` | The temporary schema and what to confirm on live data |
| `docs/PRODUCTION_UPDATE.md` | Hand-over for the production team |
| `docs/RUN_LOCAL.md` | Running it locally (Korean) |
| `tests/` | `python -m unittest discover -s tests -t .` |

## Quick start

```bash
pip install -r requirements.txt
```

```bash
python main.py --no-llm demo --serve
```

The demo is a synthetic network: it screens 48 sites, checks every scenario, prints one report and opens the map at http://127.0.0.1:8765.

To run on live data, copy `.env.example` to `.env` and fill in the chatbot's values. Then:

```bash
python main.py inspect --site 4397
```

```bash
python main.py map
```
