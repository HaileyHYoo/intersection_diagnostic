"""Historical records (methodology 18.3, 18.4 and 18.6): screening JSON logs and weekly baseline snapshots.

Two separate datasets, never overwritten, kept apart from the current-result store (store.py):

    screening-logs/{region}/{YYYY}/{MM}/{DD}/{HHMM}_{run_id}.json
        one per completed screening run: metadata, every site's category, Detector Health, traffic and
        signal abnormalities, Grey reasons, the summary counts and the complete Q1-Q3 evidence (18.3)
    baselines/{region}/{baseline_version}/{weekday}/{HHMM}.json.gz
        the weekly baseline snapshot, one file per weekday and 30-minute slot: per site and approach the
        usual value, 10th-90th range and number of observations for Q1, Q3A, Q3B and Q3C (18.4)

Dates and times in the keys are the region's local analysis day and slot start (23:30-24:00 is HHMM 2330 of
its own day).
The baseline_version of a snapshot is the ISO week of the analysis day plus the method version, e.g.
"2026-W44.v1.1-88ffd9d604": every analysis day of week 44 compares with the eight weeks before it, and a
rule or schema change gives a new method version, hence a new snapshot.

The archive location is DIAGNOSTICS_ARCHIVE: a folder (default out/archive) or s3://bucket/prefix.
"""
from __future__ import annotations

import gzip
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .timewin import Period, period_ending

LOG_FORMAT = "intersections-diagnostics/screening-log/1"
BASELINE_FORMAT = "intersections-diagnostics/baseline-snapshot/1"


# ---------------------------------------------------------------------- storage
class LocalArchive:
    """A folder. put_new never replaces an existing file."""

    def __init__(self, root):
        self.root = Path(root)

    def __repr__(self):
        return f"LocalArchive({self.root})"

    def put_new(self, key: str, data: bytes) -> bool:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "xb") as f:
                f.write(data)
        except FileExistsError:
            return False
        return True

    def get(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.exists() else None

    def keys(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())


class S3Archive:
    """An S3 bucket (boto3, credentials from the usual AWS environment). Conditional writes keep objects
    from being overwritten."""

    def __init__(self, url: str, client=None):
        bucket, _, prefix = url.removeprefix("s3://").partition("/")
        self.bucket, self.prefix = bucket, prefix.strip("/")
        if client is None:
            import boto3                                              # only needed when S3 is used
            client = boto3.client("s3")
        self.s3 = client

    def __repr__(self):
        return f"S3Archive(s3://{self.bucket}/{self.prefix})"

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_new(self, key: str, data: bytes) -> bool:
        try:
            self.s3.put_object(Bucket=self.bucket, Key=self._key(key), Body=data, IfNoneMatch="*")
        except Exception as exc:  # noqa: BLE001 - botocore ClientError without importing botocore
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in ("PreconditionFailed", "ConditionalRequestConflict"):
                return False
            raise
        return True

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise

    def keys(self, prefix: str) -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": self._key(prefix)}
            if token:
                kw["ContinuationToken"] = token
            page = self.s3.list_objects_v2(**kw)
            cut = len(self.prefix) + 1 if self.prefix else 0
            out += [o["Key"][cut:] for o in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                return sorted(out)
            token = page["NextContinuationToken"]


def open_archive(location: str | None = None, default=None):
    """DIAGNOSTICS_ARCHIVE (or `location`): s3://bucket/prefix, a folder, or "off" for none."""
    location = location or os.environ.get("DIAGNOSTICS_ARCHIVE") or default
    if not location or str(location).lower() == "off":
        return None
    return S3Archive(str(location)) if str(location).startswith("s3://") else LocalArchive(location)


def _json(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8")


def read_json(archive, key: str):
    data = archive.get(key)
    if data is None:
        return None
    return json.loads(gzip.decompress(data) if key.endswith(".gz") else data)


# ---------------------------------------------------------------------- baseline version and keys
def baseline_week(period: Period) -> str:
    year, week, _ = period.day.isocalendar()
    return f"{year}-W{week:02d}"


def snapshot_version(period: Period, method_version: str) -> str:
    return f"{baseline_week(period)}.{method_version}"


def log_key(region: str, period: Period, run_id: str) -> str:
    return f"screening-logs/{region}/{period.day:%Y/%m/%d}/{period.slot.replace(':', '')}_{run_id}.json"


def baseline_key(region: str, version: str, period: Period) -> str:
    return f"baselines/{region}/{version}/{period.day:%A}/{period.slot.replace(':', '')}.json.gz"


# ---------------------------------------------------------------------- 18.3 screening JSON log
def approaches_of(sites: list[dict]) -> list[dict]:
    """The approaches a screening evaluated, from its site records (no extra network query)."""
    out = []
    for s in sites:
        q1, q3 = s.get("q1") or {}, s.get("q3") or {}
        phase = (q3.get("components") or {}).get("phase_service") or {}
        for a in q1.get("approaches", []) + phase.get("approaches", []):
            out.append({"site": s["site"], "link": a["link"]})
    return out


def screening_log(payload: dict, run: dict | None = None) -> dict:
    """The JSON log of one completed run, from the run payload (service._run) and its store record."""
    sites = payload["sites"]
    detector_health, traffic, signal, grey = [], [], [], []
    for s in sites:
        q2, q1, q3 = s.get("q2") or {}, s.get("q1") or {}, s.get("q3") or {}
        if q2.get("status") == "FAIL":
            failed = set(q2.get("failed", []))
            detector_health.append({"site": s["site"], "name": s.get("name"), "threshold": q2.get("threshold"),
                                    "failed_detectors": [{"detector": d["detector"], "count_60min": d["count_60min"],
                                                          "records": d.get("records"),
                                                          "expected_records": d.get("expected_records")}
                                                         for d in q2.get("detectors", []) if d["detector"] in failed]})
        if q1.get("status") == "ABNORMAL":
            traffic.append({"site": s["site"], "name": s.get("name"), "category": s["category"],
                            "approaches": [a for a in q1.get("approaches", []) if a["link"] in q1.get("flagged", [])]})
        if q3.get("status") == "ABNORMAL":
            comp = q3.get("components", {})
            phase = comp.get("phase_service") or {}
            signal.append({"site": s["site"], "name": s.get("name"), "category": s["category"],
                           "cycle_length": comp.get("cycle_length"), "cycle_stability": comp.get("cycle_stability"),
                           "phase_service": {"status": phase.get("status"), "approaches": [
                               a for a in phase.get("approaches", []) if a["link"] in phase.get("flagged", [])]}})
        if s["category"] == "grey":
            grey.append({"site": s["site"], "name": s.get("name"), "reasons": s.get("reasons", [])})
    run = run or {}
    return {
        "format": LOG_FORMAT,
        "metadata": {"run_id": payload["run_id"], "region": payload["region"], "period": payload["period"],
                     "started": run.get("started"), "completed": run.get("finished"),
                     "logged": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "status": run.get("status", "complete"),
                     "baseline_version": payload["baseline"].get("snapshot_version", payload["baseline"]["version"]),
                     "baseline_snapshot": payload["baseline"].get("snapshot_key"),
                     "baseline_reference_periods": [p["end_local"] for p in payload["baseline"].get("reference_periods", [])],
                     "baseline_skipped_days": payload["baseline"].get("skipped_days", {}),
                     "contract_baseline_version": payload.get("contract_baseline_version"),
                     "rules_version": payload.get("rules_version"), "schema_version": payload.get("schema_version"),
                     "config_version": payload.get("config_version"), "notes": payload.get("notes", [])},
        "summary": {"sites": len(sites), "counts": payload["counts"], "errors": payload.get("errors", {})},
        "intersections": [{"site": s["site"], "name": s.get("name"), "category": s["category"]} for s in sites],
        "detector_health_issues": detector_health,
        "traffic_abnormalities": traffic,
        "signal_abnormalities": signal,
        "insufficient_data": grey,
        "sites": sites,                                                  # complete Q2/Q1/Q3 evidence of every site
    }


def write_screening_log(archive, payload: dict, run: dict, rules: dict) -> str:
    """Writes the run's log once; a second call for the same run leaves the first file as it is."""
    period = period_ending(payload["period"]["end"], rules)
    key = log_key(payload["region"], period, payload["run_id"])
    archive.put_new(key, _json(screening_log(payload, run)))
    return key


# ---------------------------------------------------------------------- 18.4 baseline snapshots
def baseline_snapshot(baseline: dict, period: Period, version: str, approaches: list[dict]) -> dict:
    """One weekday/slot of the weekly snapshot, per site and approach, from a built baseline (baseline.py)."""
    trim = lambda env: {k: env.get(k) for k in ("usual", "p_low", "p_high", "n")}
    links = defaultdict(set)
    for a in approaches:
        links[a["site"]].add(a["link"])
    sites = {}
    for site in sorted(set(links) | set(baseline["kpi"]) | set(baseline["green"])):
        kpi, green = baseline["kpi"].get(site, {}), baseline["green"].get(site, {})
        approach = {}
        for link in sorted(links.get(site, set()) | set(green)):
            row = {}
            if link in baseline["volume"]:
                row["q1_volume_30min"] = trim(baseline["volume"][link])
            if link in green:
                row["q3c_green_share_pct"] = trim(green[link])
            if row:
                approach[link] = row
        entry = {name: trim(kpi[f]) for f, name in (("cycle_length", "q3a_cycle_length"),
                                                    ("cycle_stability", "q3b_cycle_stability")) if f in kpi}
        if approach:
            entry["approaches"] = approach
        if entry:
            sites[site] = entry
    return {"format": BASELINE_FORMAT, "baseline_version": version, "method_version": baseline["version"],
            "calculated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "weekday": period.day.strftime("%A"), "slot": period.slot, "analysis_period": period.to_dict(),
            "reference_periods": [p["end_local"] for p in baseline["reference_periods"]],
            "skipped_days": baseline["skipped_days"], "sites": sites}


def write_baseline_snapshot(archive, region: str, baseline: dict, period: Period, version: str,
                            approaches: list[dict]) -> str:
    key = baseline_key(region, version, period)
    archive.put_new(key, gzip.compress(_json(baseline_snapshot(baseline, period, version, approaches))))
    return key


# ---------------------------------------------------------------------- 18.6 future historical analysis
def screened_periods(archive, region: str, start_day, end_day) -> list[str]:
    """Log keys of the runs screened between two local dates (inclusive)."""
    keys = []
    for key in archive.keys(f"screening-logs/{region}/"):
        parts = key.split("/")
        day = "-".join(parts[2:5])
        if str(start_day) <= day <= str(end_day):
            keys.append(key)
    return keys


def site_history(archive, region: str, site: str, start_day, end_day) -> dict:
    """How often a site was each category, over the periods that were actually screened.
    Unscreened periods are not counted as anything (18.6); several runs of one period count once (the latest)."""
    per_period = {}
    for key in screened_periods(archive, region, start_day, end_day):
        log = read_json(archive, key)
        period = log["metadata"]["period"]["end_local"]
        category = next((s["category"] for s in log["intersections"] if s["site"] == str(site)), None)
        per_period[period] = category                                      # keys are in time order: latest run wins
    counts = Counter(c for c in per_period.values() if c)
    screened = sum(counts.values())
    return {"site": str(site), "from": str(start_day), "to": str(end_day), "screened_periods": screened,
            "periods_without_this_site": sum(c is None for c in per_period.values()),
            "counts": dict(counts), "red_share": round(counts["red"] / screened, 4) if screened else None,
            "timeline": sorted(per_period.items())}
