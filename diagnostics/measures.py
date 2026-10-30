"""From raw records to one value per entity and analysis period.

One fetch covers every requested period (one period on demand, a whole day for the weekly baseline), and
each period then takes exactly the interval records it needs:

    link volume      sum of the two 15-minute records (both required)
    site KPIs        mean of the two 15-minute records (both required)
    green share      mean of the two 15-minute records; both must have GreenShare and HasGreen = 1
    detector count   sum of the twelve 5-minute records of the 60-minute window (all required)

An entity missing any required record has no value for that period. Missing is never zero.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean

from .series import Aligner, window_values
from .timewin import Period


def _span(periods: list[Period], window_minutes: int | None = None):
    start = min(p.end for p in periods) - timedelta(minutes=window_minutes or periods[0].minutes)
    return start, max(p.end for p in periods)


class Measures:
    def __init__(self, source, rules: dict, schema: dict):
        self.source, self.rules, self.schema = source, rules, schema
        self.aligner = Aligner(rules["alignment"])
        self.notes: list[str] = []

    def _step(self, feed: str) -> int:
        return self.schema["influx"]["sources"][feed]["interval_minutes"]

    def _label(self, feed: str) -> str:
        return self.schema["influx"]["sources"][feed].get("timestamp_label", self.schema["timestamps"]["label"])

    def _series(self, rows, key, step, feed):
        grouped = defaultdict(list)
        for r in rows:
            k = key(r)
            if None not in (k if isinstance(k, tuple) else (k,)):
                grouped[k].append((r["time"], r["value"]))
        label = self._label(feed)
        return {k: self.aligner.align(points, step, label) for k, points in grouped.items()}

    # ------------------------------------------------------------------ Q1
    def link_volumes(self, periods: list[Period]) -> dict[str, dict[str, float]]:
        step = self._step("link_volume")
        series = self._series(self.source.link_volumes(*_span(periods)), lambda r: r["link"], step, "link_volume")
        out = {}
        for p in periods:
            ends = p.interval_ends(step)
            values = {}
            for link, s in series.items():
                w = window_values(s, ends)
                if w is not None:
                    values[link] = sum(w)
            out[p.key] = values
        return out

    # ------------------------------------------------------------------ Q3A / Q3B
    def site_kpi(self, periods: list[Period], sites=None) -> tuple[dict, dict]:
        """({period: {site: {field: value}}}, {period: {site: {field: origin}}})."""
        step = self._step("site_kpi")
        span = _span(periods)
        series = self._series(self.source.site_kpi(*span, sites=sites), lambda r: (r["site"], r["field"]), step, "site_kpi")
        fallback = {}
        if self.rules.get("fallbacks", {}).get("enabled"):
            fallback = self._series(self.source.cycle_length_fallback(*span), lambda r: (r["site"], r["field"]), step, "site_kpi")
        out, origins = {}, {}
        for p in periods:
            ends = p.interval_ends(step)
            values, origin = defaultdict(dict), defaultdict(dict)
            for (site, field), s in series.items():
                w = window_values(s, ends)
                if w is not None:
                    values[site][field] = mean(w)
                    origin[site][field] = "primary"
            for (site, field), s in fallback.items():
                w = window_values(s, ends)
                if w is not None and field not in values[site]:
                    values[site][field] = mean(w)
                    origin[site][field] = "fallback"
            out[p.key], origins[p.key] = dict(values), dict(origin)
        return out, origins

    # ------------------------------------------------------------------ Q3C
    def approach_green(self, periods: list[Period], sites=None) -> dict[str, dict[str, dict[str, dict]]]:
        """{period: {site: {link: {green_share, green, complete, bound}}}}.

        green is True only when every required record has HasGreen = 1 and a GreenShare value;
        green_share is then the mean share in percent, otherwise None.
        """
        step = self._step("approach_perf")
        rows = self.source.approach_perf(*_span(periods), sites=sites)
        bounds = {(r["site"], r["link"]): r.get("bound") for r in rows if r.get("bound")}
        series = self._series(rows, lambda r: (r["site"], r["link"], r["field"]), step, "approach_perf")
        fraction = self.schema["influx"]["sources"]["approach_perf"].get("green_share_unit") == "fraction"
        out = {}
        for p in periods:
            ends = p.interval_ends(step)
            table = defaultdict(dict)
            links = {(site, link) for site, link, _ in series}
            for site, link in links:
                share = window_values(series.get((site, link, "green_share"), {}), ends)
                flag = window_values(series.get((site, link, "has_green"), {}), ends)
                complete = share is not None and flag is not None
                green = complete and all(v >= 0.5 for v in flag)
                value = mean(share) * (100 if fraction else 1) if green else None
                table[site][link] = {"green_share": value, "green": green, "complete": complete,
                                     "bound": bounds.get((site, link))}
            out[p.key] = dict(table)
        return out

    # ------------------------------------------------------------------ Q2
    def detector_totals(self, period: Period, window_minutes: int, sites=None) -> dict[str, dict[int, float | None]]:
        step = self._step("detector_counts")
        rows = self.source.detector_counts(*_span([period], window_minutes), sites=sites)
        series = self._series(rows, lambda r: (r["site"], r["detector"]), step, "detector_counts")
        ends = period.interval_ends(step, window_minutes)
        out = defaultdict(dict)
        for (site, detector), s in series.items():
            w = window_values(s, ends)
            out[site][detector] = sum(w) if w is not None else None
        return dict(out)
