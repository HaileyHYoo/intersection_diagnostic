# Ranking add-on — Intersections Diagnostics

Optional, delivered apart from the diagnostics package: it orders the Red sites and each Amber category of a
screening run by priority. It never changes a category. Drop `rank.py` into
`dash_backend/dash/intersections/diagnostics/` (next to `subsystems.py`, `stats.py` and `names.py`, which it imports).
Its parameters are in the package's `config/rules.json`, section `rank`.

## Call

```python
from dash_backend.dash.intersections.diagnostics import rank
from dash_backend.dash.intersections.diagnostics.contract import adapter
from dash_backend.dash.intersections.diagnostics.settings import Settings

ranked_categories = {"red", "amber_traffic", "amber_signal"}            # only these carry Q1/Q3 evidence
sites = [adapter.site_from_model(s) for s in screening_result.sites if s.category.value in ranked_categories]
previous = [{s.site_no: s.category.value for s in r.sites} for r in previous_results]   # optional, see below
ranked = rank.rank(sites, Settings().rules, previous)
# {"red": [...], "amber_traffic": [...], "amber_signal": [...], "mapping_suspect": [...]}
```

Each row: `rank`, `site`, `name`, `category`, `score`, `severity`, `impact`, `volume_veh_h`, `type_factor`,
`confidence`, `persistence`, `persistence_factor`, `subsystem`, `subsystem_sites`, `mapping_suspect`, `reasons`
(short English phrases to show next to the site).

`previous`: the categories of the same weekday and 30-minute period in the previous 4 weeks (from the screening logs),
for the persistence factor. Leave it empty or pass `None` for a week that was not screened.

## Rule

score = severity × impact × type × confidence × persistence

- severity: per abnormal finding, |current − usual| / spread, spread = (90th − 10th percentile) / c(n), where c(n) is the expected 10th–90th percentile width of n normal values and n the number of reference weeks (1.79 for 5 weeks, 1.91 for 6, 1.99 for 7, 2.05 for 8; 2.563 for a large sample), never below
  √usual vehicles for volumes, 2 s for cycle length, 1 point for Cycle Stability, 1 pp for green share; each capped at
  5; the three largest combined as √(Σz²). Approaches of one phase count once.
- impact: log10(1 + site veh/h) / log10(1 001).
- type: × 1.25 when phase service moves opposite to the volume on the same approach.
- confidence: × 0.8 at the 5-week minimum history, × 0.8 with a tolerated detector.
- persistence: × (1 + 0.25 k), k = previous weeks in which the site had the same category (Red; Red or Amber for Amber).
- Sites with a usual green share of 100 % or a usual volume of 0 behind a finding are listed apart (mapping_suspect).
- The weights (1.25, 0.8, 0.25) are judgement-based for now; they are to be checked against next-week recurrence and
  with a sensitivity analysis (proposal sent to the methodology owner, 20 Nov 2026).

On the AM peak of 10 Nov 2026 the top of the Red list was led by sites that are Red under both the default
methodology and the sensitivity run with every switch on (16 of the top 20).
