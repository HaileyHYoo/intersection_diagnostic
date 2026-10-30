"""Core-logic entry points in the production contract's terms.

The host (Dash background callback) owns the shared run store and the RUNNING/COMPLETED records; these two
functions only compute:

    run_screening(ScreeningInput)  -> ScreeningResult    Level 1 for the input's region and period
    run_diagnosis(DiagnosisInput)  -> DiagnosisResult    Level 2 for one Red site, from its saved evidence

The input's ScreeningConfig thresholds override rules.json; every other rule (exclusions, alignment, the
no-green rule, ...) comes from rules.json. Baselines are read from, or built into, the baseline store.
"""
from __future__ import annotations

from datetime import datetime

from .. import screening
from ..baseline import BaselineBuilder
from ..settings import Settings, load_rules
from ..store import SQLiteStore
from ..templates import d001, d002
from . import adapter


def settings_for(config, base: Settings | None = None) -> Settings:
    base = base or Settings()
    return Settings(schema=base.schema, rules=load_rules(overrides=adapter.rules_overrides(config)), db_path=base.db_path)


def run_screening(inp, source, settings: Settings | None = None, store=None):
    """ScreeningInput -> ScreeningResult."""
    settings = settings_for(inp.config, settings)
    if inp.region != settings.region:
        raise ValueError(f"Region {inp.region} is not configured (rules region {settings.region}).")
    period = adapter.period_from_model(inp.period, settings.rules)
    baseline = BaselineBuilder(source, settings, store or SQLiteStore(settings.db_path)).get(period)
    result = screening.screen(source, settings, baseline, period, adapter.network(inp))
    payload = {"region": inp.region, "period": period.to_dict(), "baseline": {"version": baseline["version"]},
               "sites": result["sites"], "errors": result["errors"]}
    return adapter.screening_result(payload, settings, run=inp.run_id, baseline_version=inp.baseline_version)


def run_diagnosis(inp, source, settings: Settings | None = None, llm=None):
    """DiagnosisInput -> DiagnosisResult."""
    S = adapter.S
    if inp.evidence.category != S.SiteCategory.RED:
        raise ValueError(f"Site {inp.site.site_no} is {inp.evidence.category.value}; only Red sites are diagnosed.")
    settings = settings or Settings()
    period = adapter.period_from_model(inp.period, settings.rules)
    site = adapter.site_from_model(inp.evidence)
    r1 = d001.run(site, period.to_dict(), llm)
    r2 = d002.run(source, site, period, settings.rules, llm)
    return S.DiagnosisResult(diagnosis_id=inp.diagnosis_id, screening_run_id=inp.screening_run_id, site_no=inp.site.site_no,
                             period=inp.period, q4=adapter.q4_output(site, r1, settings.rules, inp.q4_template),
                             q5=adapter.q5_output(r2, period, settings.rules, inp.q5_template),
                             completed_at=datetime.now().astimezone())
