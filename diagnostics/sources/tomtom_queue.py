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
                                 "queue_m": value, "raw_time": record[stamp]})
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
        detail = ""
        if code is not None and hasattr(exc, "read"):
            try:                                                 # TomTom explains a rejection in the body
                body = exc.read()[:300].decode("utf-8", "replace")
                detail = ": " + " ".join(body.replace(query.get("key", "\0"), "***").split())[:200] if body.strip() else ""
            except Exception:  # noqa: BLE001
                detail = ""
        raise DataUnavailable(f"TomTom queue archive request failed (HTTP {code}{detail})" if code else
                              "TomTom queue archive request failed (network)") from None


class QueueArchive:
    """As the production TomTom layer (tomtom/sources.py queue_history): a period is split at now - 24 h; the
    recent part uses the recent (live) archive, the older part the historical archive. URL templates and extra
    parameters come from the same environment variables (TOMTOM_QUEUE_ARCHIVE_URL_TEMPLATE,
    TOMTOM_QUEUE_HISTORIC_PARAMS, TOMTOM_QUEUE_RECENT_URL_TEMPLATE, TOMTOM_QUEUE_RECENT_PARAMS; JSON objects),
    because the account's archive contract is configured there."""

    def __init__(self, spec: dict, tz: str = "Australia/Melbourne", fetch=download, now=None):
        self.spec, self.tz, self.fetch = spec, ZoneInfo(tz), fetch
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._cache: dict[tuple, list[dict]] = {}

    def _backends(self, start: datetime, end: datetime) -> list[tuple]:
        env = os.environ.get
        default = self.spec["url_template"]
        cutoff = self.now() - timedelta(hours=24)
        if timedelta(0) < cutoff - start <= timedelta(minutes=5):     # "last 24 hours": keep it in the recent archive
            cutoff = start
        parts = []
        if start < cutoff:
            parts.append(("historical archive", start, min(end, cutoff), env("TOMTOM_QUEUE_ARCHIVE_URL_TEMPLATE") or default,
                          env("TOMTOM_QUEUE_HISTORIC_PARAMS")))
        if end > cutoff:
            parts.append(("recent archive", max(start, cutoff), end,
                          env("TOMTOM_QUEUE_RECENT_URL_TEMPLATE") or env("TOMTOM_QUEUE_ARCHIVE_URL_TEMPLATE") or default,
                          env("TOMTOM_QUEUE_RECENT_PARAMS")))
        return parts

    def rows(self, junction_uuid: str, start: datetime, end: datetime) -> list[dict]:
        """Per-minute rows with start < time <= end (UTC). A part that cannot be read raises DataUnavailable
        naming the archive (a period with no rows at all is not an error)."""
        import json as _json
        names = self.spec.get("date_params", {"from": "from", "to": "to"})
        out, failures = [], []
        for backend, a, b, template, extra in self._backends(start, end):
            if "{junction_uuid}" not in template and "{intersection_id}" not in template:
                raise DataUnavailable("Queue archive url_template must contain {junction_uuid}.")
            last = b - timedelta(seconds=1)
            first_day = min(a.date(), a.astimezone(self.tz).date())
            last_day = max(last.date(), last.astimezone(self.tz).date())
            params = {names["from"]: first_day.isoformat(), names["to"]: last_day.isoformat(), **(_json.loads(extra) if extra else {})}
            uuid = urllib.parse.quote(str(junction_uuid), safe="")
            url = template.replace("{junction_uuid}", uuid).replace("{intersection_id}", uuid)
            key = (url, tuple(sorted(params.items())))
            try:
                if key not in self._cache:
                    self._cache[key] = parse_archive(self.fetch(url, params), self.spec)
            except DataUnavailable as exc:
                hint = (" (older than 24 h; check TOMTOM_QUEUE_HISTORIC_PARAMS)" if backend == "historical archive" else "")
                failures.append(f"{backend}: {exc}{hint}")
                continue
            out += [r for r in self._cache[key] if a < r["time"] <= b]
        if failures and not out:
            raise DataUnavailable("; ".join(failures))
        return out


__all__ = ["QueueArchive", "parse_archive"]
