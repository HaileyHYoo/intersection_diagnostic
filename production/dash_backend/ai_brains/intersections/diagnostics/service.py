"""The interface a host (map layer, backend) calls. Every method returns JSON-ready dicts.

    screen(period_end=None)      Level 1 for the latest completed period (or a chosen one). A complete run
                                 for the same region, period, baseline version and rules is returned from
                                 the store; a run already in progress is waited for, not started twice.
    site_evidence(run_id, site)  The saved Q2/Q1/Q3 evidence of one site (any category, no LLM).
    diagnose(run_id, site)       What a click runs: D001 + D002 and the four-section report for a Red site;
                                 the saved evidence for every other category (rules.click decides).
    refresh_baselines(days)      The weekly baseline job; writes the weekly baseline snapshot.
    archive_run(run_id)          Writes a run's screening JSON log if it is missing (e.g. S3 was unreachable).

Historical records (methodology 18.3/18.4): when the service has an archive, every completed run writes one
screening JSON log, and every baseline it uses is in that week's baseline snapshot (archive.py).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from . import archive as history
from . import screening
from .baseline import BaselineBuilder
from .report import assemble
from .settings import Settings, config_snapshot
from .store import SQLiteStore
from .templates import d001, d002
from .timewin import Period, latest_period, period_ending
from .vic_calendar import day_note

log = logging.getLogger(__name__)
_inflight: dict[tuple, threading.Event] = {}
_inflight_lock = threading.Lock()


class DiagnosticsService:
    def __init__(self, source, settings: Settings | None = None, store=None, llm=None, wait_seconds: float = 600,
                 archive=None):
        self.source = source
        self.archive = archive
        self.settings = settings or Settings()
        self.store = store or SQLiteStore(self.settings.db_path)
        self.llm = llm
        self.wait_seconds = wait_seconds
        self.baselines = BaselineBuilder(source, self.settings, self.store)

    # ------------------------------------------------------------------ periods
    def period(self, period_end: datetime | str | None = None, now: datetime | None = None) -> Period:
        return latest_period(self.settings.rules, now) if period_end is None else period_ending(period_end, self.settings.rules)

    def _key(self, period: Period) -> tuple:
        return (self.settings.region, period.key, self.settings.baseline_version, self.settings.rules_version)

    # ------------------------------------------------------------------ Level 1
    def screen(self, period_end: datetime | str | None = None, force: bool = False, now: datetime | None = None) -> dict:
        period = self.period(period_end, now)
        key = self._key(period)
        if not force:
            done = self.store.find_run(*key)
            if done:
                return self.map_view(self.store.get_run(done["run_id"]), cached=True)
        with _inflight_lock:
            event = _inflight.get(key)
            owner = event is None
            if owner:
                event = _inflight[key] = threading.Event()
        if not owner:
            event.wait(self.wait_seconds)
            done = self.store.find_run(*key)
            if done:
                return self.map_view(self.store.get_run(done["run_id"]), cached=True)
        try:
            self._wait_for_other_process(key)
            done = None if force else self.store.find_run(*key)
            if done:
                return self.map_view(self.store.get_run(done["run_id"]), cached=True)
            return self.map_view(self.store.get_run(self._run(period, key)), cached=False)
        finally:
            if owner:
                with _inflight_lock:
                    _inflight.pop(key, None)
                event.set()

    def _wait_for_other_process(self, key: tuple) -> None:
        """Another process (or worker) running the same screening: wait for it rather than run twice."""
        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            running = self.store.find_run(*key, status="running")
            if not running or self.store.find_run(*key):
                return
            started = datetime.fromisoformat(running["started"])
            if (datetime.now(started.tzinfo) - started).total_seconds() > self.wait_seconds:
                return                                    # a stale run (crashed worker) is not waited for
            time.sleep(1)

    def _provenance_since(self, mark: int) -> list[dict]:
        """Source reads made since `mark`; the list is trimmed so a long-lived service does not grow it forever."""
        log = getattr(self.source, "provenance", [])
        taken = [dict(p) for p in log[mark:]]
        if len(log) > 5000:
            del log[:len(log) - 1000]
        return taken

    def _run(self, period: Period, key: tuple) -> str:
        run_id = self.store.start_run(*key)
        mark = len(getattr(self.source, "provenance", []))
        self.store.put_config(self.settings.rules_version, config_snapshot(self.settings))
        try:
            baseline = self.baselines.get(period)
            result = screening.screen(self.source, self.settings, baseline, period)
            snapshot = history.snapshot_version(period, baseline["version"])
            snapshot_key = self._snapshot(baseline, period, history.approaches_of(result["sites"]))
            notes = [n for n in [day_note(period.day)] if n]
            if baseline["skipped_days"]:
                notes.append("Reference days left out of the history: " + ", ".join(
                    f"{d} ({r})" for d, r in sorted(baseline["skipped_days"].items())))
            payload = {"run_id": run_id, "region": self.settings.region, "period": period.to_dict(),
                       "baseline": {"version": baseline["version"], "reference_periods": baseline["reference_periods"],
                                    "skipped_days": baseline["skipped_days"], "snapshot_version": snapshot,
                                    "snapshot_key": snapshot_key},
                       "rules_version": self.settings.rules_version, "schema_version": self.settings.schema.get("version"),
                       "counts": result["counts"], "errors": result["errors"], "alignment": result["alignment"], "notes": notes,
                       "config_version": self.settings.rules_version,
                       "provenance": self._provenance_since(mark), "sites": result["sites"]}
            self.store.finish_run(run_id, payload, {"counts": result["counts"], "sites": len(result["sites"])})
        except Exception as exc:
            self.store.fail_run(run_id, f"{type(exc).__name__}: {exc}")
            raise
        self.archive_run(run_id)
        return run_id

    # ------------------------------------------------------------------ historical records (18.3, 18.4)
    def _snapshot(self, baseline: dict, period: Period, approaches: list[dict]) -> str | None:
        if self.archive is None:
            return None
        version = history.snapshot_version(period, baseline["version"])
        try:
            return history.write_baseline_snapshot(self.archive, self.settings.region, baseline, period, version, approaches)
        except Exception as exc:  # noqa: BLE001 - the screening result does not depend on the archive
            log.warning("Baseline snapshot %s %s not written: %s", version, period.key, exc)
            self.store.save_audit("archive_failed", period.key, {"what": "baseline snapshot", "error": str(exc)})
            return None

    def archive_run(self, run_id: str) -> str | None:
        """The run's screening JSON log, written once (an existing log is left as it is). A failure is
        recorded and does not undo the run; calling this again later retries."""
        if self.archive is None:
            return None
        run = self.store.get_run(run_id)
        try:
            key = history.write_screening_log(self.archive, run["payload"], run, self.settings.rules)
        except Exception as exc:  # noqa: BLE001
            log.warning("Screening log for run %s not written: %s", run_id, exc)
            self.store.save_audit("archive_failed", run_id, {"what": "screening log", "error": str(exc)})
            return None
        self.store.save_audit("screening_log", run_id, {"key": key, "archive": repr(self.archive)})
        return key

    def map_view(self, run: dict, cached: bool) -> dict:
        p = run["payload"]
        keep = ("site", "name", "lat", "lon", "category", "label", "reasons", "selectable", "total_volume_veh_h")
        return {"run_id": run["run_id"], "cached": cached, "region": p["region"], "period": p["period"],
                "baseline": p["baseline"], "rules_version": p["rules_version"], "schema_version": p["schema_version"],
                "counts": p["counts"], "notes": p["notes"], "alignment": p["alignment"], "errors": p.get("errors", {}),
                "categories": screening.CATEGORIES, "sites": [{k: s[k] for k in keep} for s in p["sites"]]}

    # ------------------------------------------------------------------ Level 2
    def _site(self, run_id: str, site: str) -> tuple[dict, dict]:
        run = self.store.get_run(run_id)
        if not run or run["status"] != "complete":
            raise KeyError(f"No complete screening run {run_id}.")
        for s in run["payload"]["sites"]:
            if s["site"] == str(site):
                return run, s
        raise KeyError(f"Site {site} is not in run {run_id}.")

    def site_evidence(self, run_id: str, site: str) -> dict:
        run, s = self._site(run_id, site)
        return {"mode": "evidence", "run_id": run_id, "period": run["payload"]["period"],
                "baseline": run["payload"]["baseline"], "site": s}

    def diagnose(self, run_id: str, site: str, reuse: bool = True) -> dict:
        run, s = self._site(run_id, site)
        templates = self.settings.rules["click"].get(s["category"], [])
        if not templates:
            return self.site_evidence(run_id, site)
        if reuse:
            saved = self.store.latest_diagnosis(run_id, s["site"])
            if saved:
                return {**saved, "cached": True}
        p = run["payload"]
        period = period_ending(p["period"]["end"], self.settings.rules)
        mark = len(getattr(self.source, "provenance", []))
        r1 = d001.run(s, p["period"], self.llm) if "D001" in templates else None
        r2 = d002.run(self.source, s, period, self.settings.rules, self.llm) if "D002" in templates else None
        report = assemble(s, p["period"], r1, r2)
        registry = self.settings.rules.get("contract", {}).get("template_ids", {})
        templates = {t["template_id"]: {**t, "registry": registry.get(t["template_id"])} for t in (r1, r2) if t}
        record = {"mode": "report", "run_id": run_id, "site": s["site"], "period": p["period"], "report": report,
                  "templates": templates, "config_version": self.settings.rules_version,
                  "provenance": self._provenance_since(mark)}
        record["id"] = self.store.save_diagnosis(run_id, s["site"], record)
        return {**record, "cached": False}

    # ------------------------------------------------------------------ weekly job
    def refresh_baselines(self, days: list, slots: list[str] | None = None, progress=None) -> int:
        on_built = None
        if self.archive is not None:
            sites = [s["site"] for s in self.source.sites()]
            approaches = self.source.approaches(sites)
            on_built = lambda period, baseline: self._snapshot(baseline, period, approaches)
        return self.baselines.precompute(days, slots, progress, on_built)


def live_service(settings: Settings | None = None, llm=None) -> DiagnosticsService:
    from .sources.live import LiveSource
    settings = settings or Settings()
    return DiagnosticsService(LiveSource(settings), settings, SQLiteStore(settings.db_path), llm,
                              archive=history.open_archive(settings.archive_location))
