"""Historical baselines: the same weekday and 30-minute slot in the previous eight weeks.

For an analysis period P the reference periods are P's slot on the same weekday 1..8 weeks before P's own
date, minus excluded days (timewin.reference_periods). Choosing a day in May therefore compares it with the
eight weeks before that day, not with the latest weeks.

Values per reference period ("slot values") are cached, so a reference day fetched once serves every later
analysis day that uses it. The weekly job (precompute) fetches each reference day whole and stores all its
slots; an on-demand request for a period without a stored baseline fetches only the eight reference
periods it needs.
"""
from __future__ import annotations

from collections import defaultdict

from . import stats
from .measures import Measures
from .settings import Settings
from .timewin import Period, period_at, reference_periods


def site_window(baseline: dict, site: str, links: list[str], rules: dict) -> tuple[dict, dict, dict, dict | None]:
    """One reference window for all the measures of a site (backfill, decision of 18 Nov 2026).

    Start from the first `weeks` usable weeks; while a measure of the site that can reach the minimum
    (history.min_observations) within the candidates has fewer values, add the next earlier candidate week, for every
    measure of the site together. A measure that cannot reach the minimum even with every candidate does not extend
    the window (it stays not assessable). Returns (volume, kpi, green) envelopes for the site over that window and
    {"from", "to", "weeks", "extended_for"}; without backfill the baseline's own envelopes and None."""
    if "candidates" not in baseline:
        return baseline["volume"], baseline["kpi"].get(site, {}), baseline["green"].get(site, {}), None
    minimum = rules["history"]["min_observations"]
    cands = [c["key"] for c in baseline["candidates"]]
    bw = baseline["by_week"]
    series = [("volume", link, bw["volume"][link]) for link in links if link in bw["volume"]]
    series += [("kpi", field, v) for field, v in (bw["kpi"].get(site) or {}).items()]
    series += [("green", link, v) for link, v in (bw["green"].get(site) or {}).items()]
    count = lambda weeks_map, n: sum(1 for k in cands[:n] if k in weeks_map)
    reachable = [x for x in series if count(x[2], len(cands)) >= minimum]
    n = baseline["calendar_weeks"]
    short = lambda n: [x for x in reachable if count(x[2], n) < minimum]
    extended_for = sorted({f"{kind} {name}" for kind, name, _ in short(n)})
    while n < len(cands) and short(n):
        n += 1
    window = cands[:n]
    env = lambda weeks_map: {**stats.envelope([weeks_map[k] for k in window if k in weeks_map], rules),
                             "values": [round(weeks_map[k], 3) for k in window if k in weeks_map]}
    volume = {link: env(v) for kind, link, v in series if kind == "volume"}
    kpi = {field: env(v) for kind, field, v in series if kind == "kpi"}
    green = {link: env(v) for kind, link, v in series if kind == "green"}
    days = [c["day"] for c in baseline["candidates"][:n]]
    info = {"from": days[-1], "to": days[0], "weeks": n, "calendar_weeks": baseline["calendar_weeks"],
            "extended_for": extended_for if n > baseline["calendar_weeks"] else []}
    return volume, kpi, green, info


def window_note(info: dict | None) -> str | None:
    if not info:
        return None
    text = f"Reference weeks for this site (all measures): {info['weeks']} weeks, {info['from']} to {info['to']}"
    if info["extended_for"]:
        text += (f"; extended from {info['calendar_weeks']} weeks because these measures had fewer than the minimum: "
                 + ", ".join(info["extended_for"]))
    return text + "."


class BaselineBuilder:
    def __init__(self, source, settings: Settings, store):
        self.source, self.settings, self.store = source, settings, store
        self.rules, self.region = settings.rules, settings.region
        self.version = settings.baseline_version
        self.slot_version = settings.slot_version          # raw per-period values: reused across window methods
        self.fetches = 0

    # ------------------------------------------------------------------ reference values
    def _measure(self, periods: list[Period]) -> dict[str, dict]:
        m = Measures(self.source, self.rules, self.settings.schema)
        volume = m.link_volumes(periods)
        kpi, origin = m.site_kpi(periods)
        green = m.approach_green(periods)
        self.fetches += 1
        out = {}
        for p in periods:
            out[p.key] = {
                "volume": volume[p.key],
                "kpi": kpi[p.key],
                "kpi_origin": origin[p.key],
                "green": {site: {link: v["green_share"] for link, v in links.items() if v["green"]}
                          for site, links in green[p.key].items()},
            }
        return out

    def slot_values(self, periods: list[Period]) -> dict[str, dict]:
        out, missing = {}, []
        for p in periods:
            cached = self.store.get_slot_values(self.region, self.slot_version, p.key)
            if cached is None:
                missing.append(p)
            else:
                out[p.key] = cached
        by_day = defaultdict(list)
        for p in missing:
            by_day[p.day].append(p)
        for day_periods in by_day.values():
            for key, values in self._measure(day_periods).items():
                self.store.put_slot_values(self.region, self.slot_version, key, values)
                out[key] = values
        return out

    # ------------------------------------------------------------------ baselines
    def build(self, period: Period) -> dict:
        backfill = self.rules["history"].get("extend_beyond_weeks", False)
        refs, skipped = reference_periods(period, self.rules, candidates=backfill)
        values = self.slot_values(refs)
        ordered = [(p, values[p.key]) for p in refs]                # most recent first
        weeks = self.rules["history"]["weeks"]
        # With backfill the envelopes below cover the first `weeks` usable weeks; each site then takes one window for
        # all its measures (site_window), extended to earlier weeks together when a measure has too few values.
        calendar = {p.key for p in refs[:weeks]} if backfill else {p.key for p in refs}
        volume, kpi, green = defaultdict(list), defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
        by_week = {"volume": defaultdict(dict), "kpi": defaultdict(lambda: defaultdict(dict)),
                   "green": defaultdict(lambda: defaultdict(dict))}
        for p, v in ordered:
            inside = p.key in calendar
            for link, x in v["volume"].items():
                if x is not None:
                    by_week["volume"][link][p.key] = x
                    if inside:
                        volume[link].append(x)
            for site, fields in v["kpi"].items():
                for field, x in fields.items():
                    if x is not None:
                        by_week["kpi"][site][field][p.key] = x
                        if inside:
                            kpi[site][field].append(x)
            for site, links in v["green"].items():
                for link, x in links.items():
                    if x is not None:
                        by_week["green"][site][link][p.key] = x
                        if inside:
                            green[site][link].append(x)
        env = lambda xs: {**stats.envelope(xs, self.rules), "values": [round(x, 3) for x in xs]}
        out = {
            "version": self.version,
            "period": period.to_dict(),
            "reference_periods": [p.to_dict() for p in refs if p.key in calendar],
            "skipped_days": skipped,
            "volume": {link: env(xs) for link, xs in volume.items()},
            "kpi": {site: {field: env(xs) for field, xs in fields.items()} for site, fields in kpi.items()},
            "green": {site: {link: env(xs) for link, xs in links.items()} for site, links in green.items()},
        }
        if backfill:
            out["candidates"] = [{"key": p.key, "day": p.day.isoformat()} for p in refs]
            out["calendar_weeks"] = min(weeks, len(refs))
            out["by_week"] = {"volume": dict(by_week["volume"]),
                              "kpi": {k: dict(v) for k, v in by_week["kpi"].items()},
                              "green": {k: dict(v) for k, v in by_week["green"].items()}}
        return out

    def get(self, period: Period) -> dict:
        cached = self.store.get_baseline(self.region, self.version, period.key)
        if cached is None:
            cached = self.build(period)
            self.store.put_baseline(self.region, self.version, period.key, cached)
        return cached

    def precompute(self, days: list, slots: list[str] | None = None, progress=None, on_built=None) -> int:
        """The weekly job: baselines for every slot of the given analysis days. on_built(period, baseline) is
        called for each, e.g. to write the weekly baseline snapshot."""
        minutes = self.rules["period_minutes"]
        slots = slots or [f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 24 * 60, minutes)]
        count = 0
        for day in days:
            periods = [period_at(day, slot, self.rules) for slot in slots]
            backfill = self.rules["history"].get("extend_beyond_weeks", False)
            refs = {r.key: r for p in periods for r in reference_periods(p, self.rules, candidates=backfill)[0]}
            self.slot_values(list(refs.values()))           # one fetch per reference day
            for p in periods:
                baseline = self.build(p)
                self.store.put_baseline(self.region, self.version, p.key, baseline)
                if on_built:
                    on_built(p, baseline)
                count += 1
            if progress:
                progress(day, count)
        return count
