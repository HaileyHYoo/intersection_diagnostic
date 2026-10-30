"""The interface a host (map layer, backend) calls. Every method returns JSON-ready dicts.

    screen(period_end=None)      Level 1 for the latest completed period (or a chosen one). A complete run
                                 for the same region, period, baseline version and rules is returned from
                                 the store; a run already in progress is waited for, not started twice.
    site_evidence(run_id, site)  The saved Q2/Q1/Q3 evidence of one site (any category, no LLM).
    diagnose(run_id, site)       What a click runs: D001 + D002 and the four-section report for a Red site;
                                 the saved evidence for every other category (rules.click decides).
    refresh_baselines(days)      The weekly baseline job.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import screening
from .baseline import BaselineBuilder
from .report import assemble
from .settings import Settings
from .store import SQLiteStore
from .templates import d001, d002
from .timewin import Period, latest_period, period_ending
from .vic_calendar import day_note

_inflight: dict[tuple, threading.Event] = {}
_inflight_lock = threading.Lock()


class DiagnosticsService:
    def __init__(self, source, settings: Settings | None = None, store=None, llm=None, wait_seconds: float = 600):
        self.source = source
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

    def _run(self, period: Period, key: tuple) -> str:
        run_id = self.store.start_run(*key)
        try:
            baseline = self.baselines.get(period)
            result = screening.screen(self.source, self.settings, baseline, period)
            notes = [n for n in [day_note(period.day)] if n]
            if baseline["skipped_days"]:
                notes.append("Reference days left out of the history: " + ", ".join(
                    f"{d} ({r})" for d, r in sorted(baseline["skipped_days"].items())))
            payload = {"run_id": run_id, "region": self.settings.region, "period": period.to_dict(),
                       "baseline": {"version": baseline["version"], "reference_periods": baseline["reference_periods"],
                                    "skipped_days": baseline["skipped_days"]},
                       "rules_version": self.settings.rules_version, "schema_version": self.settings.schema.get("version"),
                       "counts": result["counts"], "alignment": result["alignment"], "notes": notes,
                       "sites": result["sites"]}
            self.store.finish_run(run_id, payload, {"counts": result["counts"], "sites": len(result["sites"])})
            return run_id
        except Exception as exc:
            self.store.fail_run(run_id, f"{type(exc).__name__}: {exc}")
            raise

    def map_view(self, run: dict, cached: bool) -> dict:
        p = run["payload"]
        keep = ("site", "name", "lat", "lon", "category", "label", "reasons", "selectable")
        return {"run_id": run["run_id"], "cached": cached, "region": p["region"], "period": p["period"],
                "baseline": p["baseline"], "rules_version": p["rules_version"], "schema_version": p["schema_version"],
                "counts": p["counts"], "notes": p["notes"], "alignment": p["alignment"],
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
        r1 = d001.run(s, p["period"], self.llm) if "D001" in templates else None
        r2 = d002.run(self.source, s, period, self.settings.rules, self.llm) if "D002" in templates else None
        report = assemble(s, p["period"], r1, r2)
        record = {"mode": "report", "run_id": run_id, "site": s["site"], "period": p["period"], "report": report,
                  "templates": {t["template_id"]: t for t in (r1, r2) if t}}
        record["id"] = self.store.save_diagnosis(run_id, s["site"], record)
        return {**record, "cached": False}

    # ------------------------------------------------------------------ weekly job
    def refresh_baselines(self, days: list, slots: list[str] | None = None, progress=None) -> int:
        return self.baselines.precompute(days, slots, progress)


def live_service(settings: Settings | None = None, llm=None) -> DiagnosticsService:
    from .sources.live import LiveSource
    settings = settings or Settings()
    return DiagnosticsService(LiveSource(settings), settings, SQLiteStore(settings.db_path), llm)
