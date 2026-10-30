"""Core-logic entry points in the production contract's terms.

The host (Dash background callback) owns the shared run store and the RUNNING/COMPLETED records; these two
functions only compute:

    run_screening(ScreeningInput)  -> ScreeningResult    Level 1 for the input's region and period
    run_diagnosis(DiagnosisInput)  -> DiagnosisResult    Level 2 for one Red site, from its saved evidence

The input's ScreeningConfig thresholds override rules.json; every other rule (exclusions, alignment, the
no-green rule, ...) comes from rules.json. Baselines are read from, or built into, the baseline store.

Audit (methodology 18): what the contract has no field for is written to an audit store when one is given
(store.save_audit / get_audits; SQLite by default, any object with the same two methods otherwise):

    screening   rules and schema used (config snapshot), source reads, record-alignment counts, both baseline
                versions, the full per-site evidence
    diagnosis   per template: registry ID, who wrote the answer (code / LLM), why an LLM answer was rejected,
                the evidence; source reads; config version
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import archive as history
from .. import screening
from ..baseline import BaselineBuilder
from ..settings import Settings, config_snapshot, load_rules
from ..store import SQLiteStore
from ..templates import d001, d002
from . import adapter


log = logging.getLogger(__name__)


def settings_for(config, base: Settings | None = None) -> Settings:
    base = base or Settings()
    return Settings(schema=base.schema, rules=load_rules(overrides=adapter.rules_overrides(config)), db_path=base.db_path)


def _reads(source, mark: int) -> list[dict]:
    return [dict(p) for p in getattr(source, "provenance", [])[mark:]]


def run_screening(inp, source, settings: Settings | None = None, store=None, audit_store=None, archive=None):
    """ScreeningInput -> ScreeningResult. With an archive, the run's screening JSON log and the baseline
    snapshot it used are written there (methodology 18.3/18.4)."""
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settings = settings_for(inp.config, settings)
    if inp.region != settings.region:
        raise ValueError(f"Region {inp.region} is not configured (rules region {settings.region}).")
    mark = len(getattr(source, "provenance", []))
    period = adapter.period_from_model(inp.period, settings.rules)
    baseline = BaselineBuilder(source, settings, store or SQLiteStore(settings.db_path)).get(period)
    result = screening.screen(source, settings, baseline, period, adapter.network(inp))
    payload = {"region": inp.region, "period": period.to_dict(), "baseline": {"version": baseline["version"]},
               "sites": result["sites"], "errors": result["errors"]}
    if archive is not None:
        try:
            _archive(archive, inp, settings, period, baseline, result, payload, started)
        except Exception as exc:  # noqa: BLE001 - the result does not depend on the archive
            log.warning("Screening log for run %s not written: %s", inp.run_id, exc)
            if audit_store is not None:
                audit_store.save_audit("archive_failed", inp.run_id, {"what": "screening log", "error": str(exc)})
    audit_ref = None
    if audit_store is not None:
        audit_store.put_config(settings.rules_version, config_snapshot(settings))
        audit_ref = str(audit_store.save_audit("screening", inp.run_id, {
            "run_id": inp.run_id, "region": inp.region, "period": period.to_dict(),
            "contract_baseline_version": inp.baseline_version, "baseline": {k: baseline[k] for k in
                                                                          ("version", "reference_periods", "skipped_days")},
            "config_version": settings.rules_version, "provenance": _reads(source, mark),
            "alignment": result["alignment"], "errors": result["errors"], "sites": result["sites"]}))
    return adapter.screening_result(payload, settings, run=inp.run_id, baseline_version=inp.baseline_version,
                                    audit_ref=audit_ref)


def _archive(archive, inp, settings, period, baseline, result, payload, started) -> None:
    snapshot = history.snapshot_version(period, baseline["version"])
    snapshot_key = history.write_baseline_snapshot(archive, settings.region, baseline, period, snapshot,
                                                    history.approaches_of(result["sites"]))
    history.write_screening_log(archive, {
        **payload, "run_id": inp.run_id, "counts": result["counts"], "rules_version": settings.rules_version,
        "schema_version": settings.schema.get("version"), "config_version": settings.rules_version,
        "contract_baseline_version": inp.baseline_version,
        "baseline": {**{k: baseline[k] for k in ("version", "reference_periods", "skipped_days")},
                     "snapshot_version": snapshot, "snapshot_key": snapshot_key}},
        {"started": started, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "complete"},
        settings.rules)


def run_diagnosis(inp, source, settings: Settings | None = None, llm=None, audit_store=None):
    """DiagnosisInput -> DiagnosisResult."""
    S = adapter.S
    if inp.evidence.category != S.SiteCategory.RED:
        raise ValueError(f"Site {inp.site.site_no} is {inp.evidence.category.value}; only Red sites are diagnosed.")
    settings = settings or Settings()
    period = adapter.period_from_model(inp.period, settings.rules)
    site = adapter.site_from_model(inp.evidence)
    mark = len(getattr(source, "provenance", []))
    r1 = d001.run(site, period.to_dict(), llm)
    r2 = d002.run(source, site, period, settings.rules, llm)
    refs = {"D001": inp.q4_template, "D002": inp.q5_template}
    audit_ref = None
    if audit_store is not None:
        audit_store.put_config(settings.rules_version, config_snapshot(settings))
        audit_ref = str(audit_store.save_audit("diagnosis", inp.diagnosis_id, {
            "diagnosis_id": inp.diagnosis_id, "screening_run_id": inp.screening_run_id, "site": inp.site.site_no,
            "period": period.to_dict(), "config_version": settings.rules_version, "provenance": _reads(source, mark),
            "templates": {t["template_id"]: {**t, "registry": refs[t["template_id"]].model_dump()} for t in (r1, r2)}}))
    return S.DiagnosisResult(diagnosis_id=inp.diagnosis_id, screening_run_id=inp.screening_run_id, site_no=inp.site.site_no,
                             period=inp.period, q4=adapter.q4_output(site, r1, settings.rules, inp.q4_template),
                             q5=adapter.q5_output(r2, period, settings.rules, inp.q5_template),
                             completed_at=datetime.now().astimezone(),
                             **adapter.optional(S.DiagnosisResult, config_version=settings.rules_version, audit_ref=audit_ref))
