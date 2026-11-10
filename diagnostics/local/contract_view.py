"""The production contract's SiteReport for one site, and the page it supports (for the production team).

    python main.py contract-report --site 1037 [--run ID]

Writes out/contract_report_<run>_<site>.json (the SiteReport exactly as the production page receives it) and
out/contract_report_<run>_<site>.md: the same content laid out section by section, with the contract field each
line comes from, so the page can be checked against it.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..contract import adapter, core


def site_report(svc, run_id: str, site_no: str):
    """SiteReport through the production path (core.run_site_report) from a stored run."""
    S = adapter.S
    payload = svc.store.get_run(run_id)["payload"]
    result = adapter.screening_result(payload, svc.settings, run=run_id)
    run = S.ScreeningRun(run_id=run_id, status=S.RunStatus.COMPLETED, started_at=result.completed_at, result=result,
                         key=S.ScreeningCacheKey(region=result.region, period_end=result.period.end,
                                                 baseline_version=result.baseline_version))
    request = S.SiteReportRequest(region=result.region, screening_run_id=run_id, site_no=str(site_no))
    return core.run_site_report(request, run, svc.source, svc.settings, svc.llm)


def page(report) -> str:
    """The SiteReport as the page could show it, each part labelled with its contract field."""
    ev = report.evidence
    lines = [f"# SCATS {report.site_no} - {ev.name}", "",
             f"**{ev.category.value}** - {report.period.start:%a %d %b %Y %H:%M}-{report.period.end:%H:%M}", ""]
    if ev.notes:
        lines += ["_evidence.notes_", ""] + [f"- {n}" for n in ev.notes] + [""]
    d = report.diagnosis
    if d:
        lines += ["## 1. Diagnosis", "_diagnosis.q4.diagnosis_", "", d.q4.diagnosis, "",
                  "## 2. Supporting Evidence", "_diagnosis.q4.supporting_evidence[].statement_", ""]
        lines += [f"- {e.statement}" for e in d.q4.supporting_evidence] + [""]
        if d.q4.limitations:
            lines += ["_diagnosis.q4.limitations_", ""] + [f"- {x}" for x in d.q4.limitations] + [""]
        lines += ["## 3. TomTom Road-User Impact", "_diagnosis.q5.narrative_", "", d.q5.narrative, ""]
        if d.q5.approaches:
            lines += ["_diagnosis.q5.approaches_", "",
                      "| Approach | Approach delay (s) | Control delay (s) | Multi-stop rate | Mean queue (m) | Observed |",
                      "|---|---|---|---|---|---|"]
            f = lambda x, n=1: "-" if x is None else f"{x:.{n}f}"
            lines += [f"| {a.approach_name or a.approach_id} | {f(a.delay_s)} | {f(a.control_delay_s)} | "
                      f"{f(a.multi_stop_rate, 3)} | {f(a.queue_length_m)} | {'yes' if a.is_observed else 'no'} |"
                      for a in d.q5.approaches] + [""]
        if d.q5.scats_comparison:
            names = {a.approach_id: a.approach_name for a in d.q5.approaches}
            lines += ["_diagnosis.q5.scats_comparison_", ""]
            lines += [f"- {names.get(c.approach_id) or c.approach_id}: {', '.join(c.scats_findings)} - {c.agreement.value}"
                      for c in d.q5.scats_comparison] + [""]
    s = report.link_speed
    if s:
        lines += ["### Supplementary: TomTom incoming-link speed", "_link_speed.links / link_speed.notes_", "",
                  "| Incoming link | Arm | Speed (km/h) | Usual (km/h) |", "|---|---|---|---|"]
        f = lambda x: "-" if x is None else f"{x:.1f}"
        lines += [f"| {x.street_name or x.link_id} | {'-' if x.arm is None else x.arm} | {f(x.speed_kmh)} | "
                  f"{f(x.reference_speed_kmh)} |" for x in s.links] + [""]
        lines += [f"- {n}" for n in s.notes] + [""]
    if d:
        lines += ["## 4. Suggested Engineering Checks", "_diagnosis.q4.suggested_checks_", ""]
        lines += [f"{i}. {c}" for i, c in enumerate(d.q4.suggested_checks, 1)] + [""]
    return "\n".join(lines)


def save(report, run_id: str, out_dir) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"contract_report_{run_id}_{report.site_no}"
    data = json.loads(report.model_dump_json())
    base.with_suffix(".json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(page(report) + "\n", encoding="utf-8")
    return base.with_suffix(".json"), base.with_suffix(".md")
