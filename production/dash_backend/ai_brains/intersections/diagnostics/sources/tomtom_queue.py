"""TomTom Junction Analytics queue archive: per-minute queue length per approach for one junction.

Used by D002 only, and only when rules tomtom.api_enabled is true. The endpoint, parameters and CSV
parsing follow the chatbot's TomTom layer: one daily archive (.zip of CSV files) per junction UUID,
requested for every calendar date the period touches in UTC and in local time, then filtered by timestamp.
Only the standard library is used. The API key never appears in an error message.
"""
from __future__ import annotations

import csv
import io
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..series import number
from .base import DataUnavailable


def _first(header: list[str], names: list[str]) -> str | None:
    return next((n for n in names if n in header), None)


def parse_time(value, naive_zone: str) -> datetime:
    text = str(value).strip()
    if text.isdigit():
        n = int(text)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc)
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=ZoneInfo(naive_zone))
    return t.astimezone(timezone.utc)


def parse_archive(blob: bytes, spec: dict) -> list[dict]:
    """{approach, time, queue_m} rows from an archive .zip; a queue file without approach/time columns fails."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with archive.open(name) as handle:
                reader = csv.DictReader(io.TextIOWrapper(handle, "utf-8-sig"))
                header = reader.fieldnames or []
                queue = _first(header, spec["queue_columns"])
                approach = _first(header, spec["approach_columns"])
                stamp = _first(header, spec["time_columns"])
                if not queue:
                    continue
                if not approach or not stamp:
                    raise DataUnavailable(f"Queue archive file {name} has no approach/time column; columns: {header}")
                for record in reader:
                    value = number(record.get(queue))
                    if value is None or value < 0:
                        continue
                    rows.append({"approach": str(record[approach]), "time": parse_time(record[stamp], spec["naive_timestamp_timezone"]),
                                 "queue_m": value})
    return rows


def download(url: str, params: dict, timeout: float = 120) -> bytes:
    query = dict(params)
    if os.environ.get("TOMTOM_API_KEY"):
        query["key"] = os.environ["TOMTOM_API_KEY"]
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(query))
    if os.environ.get("TOMTOM_API_TOKEN"):
        header = os.environ.get("TOMTOM_AUTH_HEADER", "Authorization")
        request.add_header(header, (os.environ.get("TOMTOM_AUTH_PREFIX", "Bearer") + " " + os.environ["TOMTOM_API_TOKEN"]).strip())
    if not query.get("key") and not os.environ.get("TOMTOM_API_TOKEN"):
        raise DataUnavailable("TomTom queue archive needs TOMTOM_API_KEY (or TOMTOM_API_TOKEN).")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        code = getattr(exc, "code", None)
        raise DataUnavailable(f"TomTom queue archive request failed (HTTP {code})" if code else
                              "TomTom queue archive request failed (network)") from None


class QueueArchive:
    def __init__(self, spec: dict, tz: str = "Australia/Melbourne", fetch=download):
        self.spec, self.tz, self.fetch = spec, ZoneInfo(tz), fetch
        self._cache: dict[tuple, list[dict]] = {}

    def rows(self, junction_uuid: str, start: datetime, end: datetime) -> list[dict]:
        """Per-minute rows with start < time <= end (UTC)."""
        if "{junction_uuid}" not in self.spec["url_template"]:
            raise DataUnavailable("Queue archive url_template must contain {junction_uuid}.")
        last = end - timedelta(seconds=1)
        first_day = min(start.date(), start.astimezone(self.tz).date())
        last_day = max(last.date(), last.astimezone(self.tz).date())
        names = self.spec.get("date_params", {"from": "from", "to": "to"})
        params = {names["from"]: first_day.isoformat(), names["to"]: last_day.isoformat()}
        url = self.spec["url_template"].replace("{junction_uuid}", urllib.parse.quote(str(junction_uuid), safe=""))
        key = (url, tuple(sorted(params.items())))
        if key not in self._cache:
            self._cache[key] = parse_archive(self.fetch(url, params), self.spec)
        return [r for r in self._cache[key] if start < r["time"] <= end]


__all__ = ["QueueArchive", "parse_archive"]
