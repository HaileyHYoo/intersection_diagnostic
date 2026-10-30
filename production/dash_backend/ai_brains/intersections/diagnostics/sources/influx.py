"""InfluxDB access: Flux built from the schema, rows returned as plain dicts.

Queries never aggregate in Flux. Several feeds hold mixed integer/string types ("schema collision" in the
inventory), which breaks group()/mean() across series; reading the raw records and converting in Python
avoids that, and keeps the interval logic in one place (series.py). Every query carries the Region tag:
SCATS site numbers repeat across cities.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .base import DataUnavailable


def flux_string(value) -> str:
    return json.dumps(str(value))


def flux_time(value: datetime) -> str:
    return "time(v: " + flux_string(value.strftime("%Y-%m-%dT%H:%M:%SZ")) + ")"


def build_flux(bucket: str, measurement: str, start: datetime, stop: datetime, *, region_tag: str, region: str,
               filters: dict | None = None, fields: list[str] | None = None, field_regex: str | None = None,
               tag_in: tuple[str, list[str]] | None = None, keep: list[str] | None = None) -> str:
    lines = [f"from(bucket: {flux_string(bucket)})",
             f"  |> range(start: {flux_time(start)}, stop: {flux_time(stop)})",
             f"  |> filter(fn: (r) => r._measurement == {flux_string(measurement)})",
             f"  |> filter(fn: (r) => r[{flux_string(region_tag)}] == {flux_string(region)})"]
    for tag, value in (filters or {}).items():
        lines.append(f"  |> filter(fn: (r) => r[{flux_string(tag)}] == {flux_string(value)})")
    if fields:
        lines.append("  |> filter(fn: (r) => " + " or ".join(f"r._field == {flux_string(f)}" for f in fields) + ")")
    if field_regex:
        lines.append(f"  |> filter(fn: (r) => r._field =~ /{field_regex}/)")
    if tag_in:
        tag, values = tag_in
        lines.append(f"  |> filter(fn: (r) => contains(value: r[{flux_string(tag)}], "
                     f"set: [{', '.join(flux_string(v) for v in values)}]))")
    if keep:
        lines.append("  |> keep(columns: [" + ", ".join(flux_string(c) for c in ["_time", "_value", "_field", *keep]) + "])")
    return "\n".join(lines)


class InfluxReader:
    """Runs Flux and streams records; connection errors become DataUnavailable."""

    def __init__(self, url: str, token: str, org: str, timeout_ms: int = 120_000):
        if not url or not token or not org:
            raise DataUnavailable("InfluxDB is not configured: set INFLUXDB_URL, INFLUXDB_TOKEN and INFLUXDB_ORG.")
        from influxdb_client import InfluxDBClient
        self._client = InfluxDBClient(url=url, token=token, org=org, timeout=timeout_ms)
        self._api = self._client.query_api()
        self.queries: list[str] = []

    def rows(self, flux: str) -> list[dict]:
        self.queries.append(flux)
        try:
            records = self._api.query_stream(flux)
            out = []
            for record in records:
                values = record.values
                row = {k: v for k, v in values.items() if not k.startswith("_") and k not in ("result", "table")}
                row["time"] = values.get("_time")
                row["field"] = values.get("_field")
                row["value"] = values.get("_value")
                out.append(row)
            return out
        except Exception as exc:  # noqa: BLE001 - the caller reports which feed failed
            raise DataUnavailable(f"InfluxDB query failed ({type(exc).__name__}: {str(exc)[:200]})") from exc

    def close(self) -> None:
        self._client.close()


def padded(start: datetime, end: datetime, tolerance_seconds: float) -> tuple[datetime, datetime]:
    """Query range covering stamps in [start - tolerance, end + tolerance] (Flux stop is exclusive)."""
    pad = timedelta(seconds=tolerance_seconds)
    return start - pad, end + pad + timedelta(seconds=1)
