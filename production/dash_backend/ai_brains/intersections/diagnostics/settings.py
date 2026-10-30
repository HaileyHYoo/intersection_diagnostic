"""Settings: the data schema, the screening rules and the connection environment.

The schema (config/schema.json) names every bucket, measurement, field and tag the code reads, and the
rules (config/rules.json) hold every threshold and switch. Both are plain JSON so the production team's
schema can replace the temporary one without touching code:

    DIAGNOSTICS_SCHEMA_FILE   another schema file
    DIAGNOSTICS_RULES_FILE    another rules file
    DIAGNOSTICS_DB            SQLite file for cached runs, baselines and reports

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


def load_rules(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    rules = _read_json(Path(path or os.environ.get("DIAGNOSTICS_RULES_FILE") or CONFIG_DIR / "rules.json"))
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
            "history": self.rules["history"],
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
