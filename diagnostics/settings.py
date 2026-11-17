"""Settings: the data schema, the screening rules and the connection environment.

The schema (config/schema.json) names every bucket, measurement, field and tag the code reads, and the
rules (config/rules.json) hold every threshold and switch. Both are plain JSON so the production team's
schema can replace the temporary one without touching code:

    DIAGNOSTICS_SCHEMA_FILE   another schema file
    DIAGNOSTICS_RULES_FILE    another rules file
    DIAGNOSTICS_DB            SQLite file for cached runs, baselines and reports
    DIAGNOSTICS_ARCHIVE       screening JSON logs and baseline snapshots: a folder or s3://bucket/prefix
                              (default: "archive" next to the SQLite file; "off" for none)

Connections use the same variables as the intersection chatbot (INFLUXDB_*, NEO4J_*, OPENAI_*).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PACKAGE_ROOT / "config"
NEW_HISTORY_DEFAULTS = {"max_lookback_weeks": 12, "school_holidays": "include"}


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_schema(path: str | Path | None = None) -> dict:
    return _read_json(Path(path or os.environ.get("DIAGNOSTICS_SCHEMA_FILE") or CONFIG_DIR / "schema.json"))


SWITCHES = {   # main.py --switches: methodology switches for sensitivity runs (all off in rules.json)
    "backfill": {"history": {"extend_beyond_weeks": True}},
    "school": {"history": {"school_holidays": "match"}},
    "noise": {"q1": {"min_count_noise_sd": 2}},
}


def switch_overrides(names: str | None) -> dict:
    """"all", "none" or a comma list of SWITCHES keys -> the rules overrides."""
    if not names or names == "none":
        return {}
    keys = list(SWITCHES) if names == "all" else [n.strip() for n in names.split(",") if n.strip()]
    unknown = [k for k in keys if k not in SWITCHES]
    if unknown:
        raise ValueError(f"Unknown switch(es) {unknown}; use all, none or {', '.join(SWITCHES)}")
    out: dict = {}
    for k in keys:
        out = _merge(out, SWITCHES[k])
    return out


def load_rules(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    rules = _read_json(Path(path or os.environ.get("DIAGNOSTICS_RULES_FILE") or CONFIG_DIR / "rules.json"))
    env = os.environ.get("DIAGNOSTICS_RULES_OVERRIDES")        # set by main.py --switches (local runs only)
    if env:
        rules = _merge(rules, json.loads(env))
    return _merge(rules, overrides) if overrides else rules


def package_file(relative: str) -> Path:
    """A data file named in the schema, relative to the package unless absolute."""
    path = Path(relative)
    return path if path.is_absolute() else PACKAGE_ROOT / path


@dataclass
class Settings:
    schema: dict = field(default_factory=load_schema)
    rules: dict = field(default_factory=load_rules)
    db_path: str = field(default_factory=lambda: os.environ.get("DIAGNOSTICS_DB", "diagnostics.sqlite3"))

    @property
    def archive_location(self) -> str:
        return os.environ.get("DIAGNOSTICS_ARCHIVE") or str(Path(self.db_path).resolve().parent / "archive")

    @property
    def region(self) -> str:
        return self.rules["region"]

    @property
    def baseline_version(self) -> str:
        """Identifies the inputs a baseline depends on: schema, history and percentile rules.

        A change to any of them gives a new version, so cached baselines and runs are never reused
        across a methodology or schema change.
        """
        relevant = {
            "schema": self.schema.get("version"),
            # switches added on 13 Nov 2026 count only when changed, so the default keeps the existing version
            "history": {k: v for k, v in self.rules["history"].items() if NEW_HISTORY_DEFAULTS.get(k, object()) != v},
            "percentiles": self.rules["percentiles"],
            "reference_value": self.rules["reference_value"],
            "alignment": self.rules["alignment"],
            "q1": self.rules["q1"].get("approach_history_min_presence"),
            "q3c": self.rules["q3c"].get("approach_history_min_presence"),
        }
        digest = hashlib.sha1(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:10]
        return f"{self.rules['version']}-{digest}"

    @property
    def rules_version(self) -> str:
        digest = hashlib.sha1(json.dumps(self.rules, sort_keys=True).encode()).hexdigest()[:10]
        return f"{self.rules['version']}-{digest}"


def config_snapshot(settings: "Settings") -> dict:
    """Everything a run's result depends on besides the data: rules, schema and the derived versions."""
    return {"rules_version": settings.rules_version, "baseline_version": settings.baseline_version,
            "schema_version": settings.schema.get("version"), "rules": settings.rules, "schema": settings.schema}


def connection_env() -> dict:
    """Connection values, read when a live source is built (never at import)."""
    get = os.environ.get
    return {
        "influx_url": get("INFLUXDB_URL", ""),
        "influx_token": get("INFLUXDB_TOKEN", ""),
        "influx_org": get("INFLUXDB_ORG", ""),
        "influx_timeout_ms": int(get("INFLUXDB_TIMEOUT_MS", "120000")),
        "neo4j_uri": get("NEO4J_URL") or get("NEO4J_URI", "bolt://localhost:7687"),
        "neo4j_user": get("NEO4J_USERNAME") or get("NEO4J_USER", "neo4j"),
        "neo4j_password": get("NEO4J_PASSWORD", ""),
        "neo4j_database": get("NEO4J_DB_NAME") or get("NEO4J_DATABASE", "neo4j"),
        "openai_api_key": get("OPENAI_API_KEY", ""),
        "openai_model": get("OPENAI_MODEL", ""),
    }
