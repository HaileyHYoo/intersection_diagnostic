"""SQLite store for reference-period values, baselines, screening runs and diagnoses.

The class is the storage interface; another backend only has to provide the same methods. Every payload
is JSON, so a stored run can be reproduced and every report traced to the run it came from.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS slot_values (
    region TEXT, version TEXT, period_key TEXT, payload TEXT, created TEXT,
    PRIMARY KEY (region, version, period_key));
CREATE TABLE IF NOT EXISTS baselines (
    region TEXT, version TEXT, period_key TEXT, payload TEXT, created TEXT,
    PRIMARY KEY (region, version, period_key));
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, region TEXT, period_key TEXT, baseline_version TEXT, rules_version TEXT,
    status TEXT, started TEXT, finished TEXT, summary TEXT, payload TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS runs_key ON runs (region, period_key, baseline_version, rules_version, status);
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, site TEXT, created TEXT, payload TEXT);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteStore:
    def __init__(self, path: str = "diagnostics.sqlite3"):
        self.path = path
        self._lock = threading.RLock()
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if path == ":memory:" else None
        with self._conn() as c:
            c.executescript(SCHEMA)

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001 - interpreter shutdown
            pass

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = self._memory or sqlite3.connect(self.path, timeout=30)
            try:
                yield conn
                conn.commit()
            finally:
                if self._memory is None:
                    conn.close()

    # ------------------------------------------------------------------ reference values and baselines
    def _get(self, table: str, region: str, version: str, key: str):
        with self._conn() as c:
            row = c.execute(f"SELECT payload FROM {table} WHERE region=? AND version=? AND period_key=?",
                            (region, version, key)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, table: str, region: str, version: str, key: str, payload) -> None:
        with self._conn() as c:
            c.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?,?)",
                      (region, version, key, json.dumps(payload), now_iso()))

    def get_slot_values(self, region, version, key):
        return self._get("slot_values", region, version, key)

    def put_slot_values(self, region, version, key, payload):
        self._put("slot_values", region, version, key, payload)

    def get_baseline(self, region, version, key):
        return self._get("baselines", region, version, key)

    def put_baseline(self, region, version, key, payload):
        self._put("baselines", region, version, key, payload)

    # ------------------------------------------------------------------ screening runs
    def find_run(self, region, period_key, baseline_version, rules_version, status="complete"):
        with self._conn() as c:
            row = c.execute("SELECT run_id, status, started FROM runs WHERE region=? AND period_key=? AND "
                            "baseline_version=? AND rules_version=? AND status=? ORDER BY started DESC LIMIT 1",
                            (region, period_key, baseline_version, rules_version, status)).fetchone()
        return {"run_id": row[0], "status": row[1], "started": row[2]} if row else None

    def start_run(self, region, period_key, baseline_version, rules_version) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("INSERT INTO runs (run_id, region, period_key, baseline_version, rules_version, status, started) "
                      "VALUES (?,?,?,?,?, 'running', ?)", (run_id, region, period_key, baseline_version, rules_version, now_iso()))
        return run_id

    def finish_run(self, run_id, payload: dict, summary: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status='complete', finished=?, summary=?, payload=? WHERE run_id=?",
                      (now_iso(), json.dumps(summary), json.dumps(payload), run_id))

    def fail_run(self, run_id, error: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status='failed', finished=?, error=? WHERE run_id=?", (now_iso(), error, run_id))

    def get_run(self, run_id) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT run_id, region, period_key, baseline_version, rules_version, status, started, "
                            "finished, summary, payload, error FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        keys = ["run_id", "region", "period_key", "baseline_version", "rules_version", "status", "started", "finished",
                "summary", "payload", "error"]
        run = dict(zip(keys, row))
        for k in ("summary", "payload"):
            run[k] = json.loads(run[k]) if run[k] else None
        return run

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT run_id, period_key, status, started, summary FROM runs ORDER BY started DESC LIMIT ?",
                             (limit,)).fetchall()
        return [{"run_id": r[0], "period_key": r[1], "status": r[2], "started": r[3],
                 "summary": json.loads(r[4]) if r[4] else None} for r in rows]

    # ------------------------------------------------------------------ diagnoses
    def save_diagnosis(self, run_id, site, payload) -> int:
        with self._conn() as c:
            cur = c.execute("INSERT INTO diagnoses (run_id, site, created, payload) VALUES (?,?,?,?)",
                            (run_id, site, now_iso(), json.dumps(payload)))
            return cur.lastrowid

    def latest_diagnosis(self, run_id, site):
        with self._conn() as c:
            row = c.execute("SELECT id, payload FROM diagnoses WHERE run_id=? AND site=? ORDER BY id DESC LIMIT 1",
                            (run_id, site)).fetchone()
        return {"id": row[0], **json.loads(row[1])} if row else None
