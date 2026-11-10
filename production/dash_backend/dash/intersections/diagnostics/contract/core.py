"""Core-logic entry points in the production contract's terms.

The host (Dash background callback) owns the shared run store and the RUNNING/COMPLETED records; these two
functions only compute:

    run_screening(ScreeningInput)  -> ScreeningResult    Level 1 for the input's region and period
    run_diagnosis(DiagnosisInput)  -> DiagnosisResult    Level 2 for one Red site, from its saved evidence
    run_site_report(SiteReportRequest, ScreeningRun) -> SiteReport
                                   an Amber or Red click: saved evidence + link speed, and Q4/Q5 for Red
    run_link_speed(SiteScreeningResult, AnalysisPeriod) -> LinkSpeedReport
                                   supplementary TomTom incoming-link speed (display only)
    write_screening_log(archive, ScreeningRun)    the 18.3 ScreeningLog of a COMPLETED run, once

With an archive, run_screening also writes the 18.4 BaselineSnapshot of its slot under the input's
baseline_version, and run_site_report keeps a Red site's SiteReport (18.2).

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
from .. import link_speed as speed
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
    """The baseline snapshot of this slot under the host's baseline_version; with a contract that has
    ScreeningLog the host logs the COMPLETED run itself (write_screening_log), else our own log is written."""
    snapshot_key = history.write_baseline_snapshot(archive, settings.region, baseline, period, inp.baseline_version,
                                                    history.approaches_of(result["sites"]) + result.get("network_links", []),
                                                    settings.rules["history"]["weeks"])
    if hasattr(adapter.S, "ScreeningLog"):
        return
    history.write_screening_log(archive, {
        **payload, "run_id": inp.run_id, "counts": result["counts"], "rules_version": settings.rules_version,
        "schema_version": settings.schema.get("version"), "config_version": settings.rules_version,
        "contract_baseline_version": inp.baseline_version,
        "baseline": {**{k: baseline[k] for k in ("version", "reference_periods", "skipped_days")},
                     "snapshot_version": inp.baseline_version, "snapshot_key": snapshot_key}},
        {"started": started, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "complete"},
        settings.rules)


def write_screening_log(archive, run, settings: Settings | None = None) -> str:
    """Methodology 18.3: the contract's ScreeningLog of a COMPLETED ScreeningRun, written once (never overwritten)
    at screening-logs/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}.json."""
    log = adapter.S.ScreeningLog.from_run(run)
    period = adapter.period_from_model(log.period, (settings or Settings()).rules)
    key = history.log_key(log.region, period, log.run_id)
    archive.put_new(key, log.model_dump_json().encode("utf-8"))
    return key


def run_link_speed(evidence, period_model, source, settings: Settings | None = None):
    """Supplementary TomTom incoming-link speed for one selected site (methodology, speed addition), as the
    contract's LinkSpeedReport. Display only: it never changes the screening result."""
    settings = settings or Settings()
    period = adapter.period_from_model(period_model, settings.rules)
    result = speed.link_speed(source, adapter.site_from_model(evidence), period, settings.schema, settings.region,
                              settings.rules)
    return adapter.link_speed_report(result, evidence.site_no, period_model)


def run_site_report(request, run, source, settings: Settings | None = None, llm=None, audit_store=None, archive=None):
    """SiteReportRequest + the saved ScreeningRun -> SiteReport (what an Amber or Red click shows).

    The evidence and period come from the run, never from the client. Amber: evidence and link speed.
    Red: also Q4/Q5 (run_diagnosis). With an archive, a Red site's report is kept as the 18.2 record
    (site-reports/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}_{site}.json, never overwritten)."""
    S = adapter.S
    settings = settings or Settings()
    if run.result is None or run.status != S.RunStatus.COMPLETED:
        raise ValueError(f"Screening run {run.run_id} is not completed.")
    if request.screening_run_id != run.run_id or request.region != run.result.region:
        raise ValueError("The request does not belong to this screening run.")
    evidence = run.site(request.site_no)
    if evidence is None:
        raise KeyError(f"Site {request.site_no} is not in run {run.run_id}.")
    if evidence.category not in S.SELECTABLE_CATEGORIES:
        raise ValueError(f"Site {request.site_no} is {evidence.category.value}; only Amber and Red sites have a report.")
    period = run.result.period
    try:
        link_speed = run_link_speed(evidence, period, source, settings) if speed.applies(
            adapter.CATEGORY_BACK[evidence.category], settings.rules) else None
    except Exception as exc:  # noqa: BLE001 - "None when the lookup failed" (contract)
        log.warning("Link speed for site %s not read: %s", request.site_no, exc)
        link_speed = None
    diagnosis = None
    if evidence.category == S.SiteCategory.RED:
        diagnosis = run_diagnosis(S.DiagnosisInput(
            diagnosis_id=f"diag_{run.run_id}_{evidence.site_no}", screening_run_id=run.run_id, region=run.result.region,
            period=period, site=S.ScreeningSite(site_no=evidence.site_no, name=evidence.name, coordinates=evidence.coordinates),
            evidence=evidence, q4_template=adapter.template_ref(settings.rules, "D001"),
            q5_template=adapter.template_ref(settings.rules, "D002")), source, settings, llm, audit_store)
    report = S.SiteReport(region=run.result.region, screening_run_id=run.run_id, site_no=evidence.site_no, period=period,
                          evidence=evidence, diagnosis=diagnosis, link_speed=link_speed,
                          created_at=datetime.now().astimezone())
    if archive is not None and diagnosis is not None:
        p = adapter.period_from_model(period, settings.rules)
        key = history.log_key(report.region, p, f"{run.run_id}_{report.site_no}").replace("screening-logs/", "site-reports/", 1)
        try:
            archive.put_new(key, report.model_dump_json().encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - the report is still returned
            log.warning("Site report %s not archived: %s", key, exc)
    return report


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
