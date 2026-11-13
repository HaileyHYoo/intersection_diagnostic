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


class BaselineBuilder:
    def __init__(self, source, settings: Settings, store):
        self.source, self.settings, self.store = source, settings, store
        self.rules, self.region = settings.rules, settings.region
        self.version = settings.baseline_version
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
            cached = self.store.get_slot_values(self.region, self.version, p.key)
            if cached is None:
                missing.append(p)
            else:
                out[p.key] = cached
        by_day = defaultdict(list)
        for p in missing:
            by_day[p.day].append(p)
        for day_periods in by_day.values():
            for key, values in self._measure(day_periods).items():
                self.store.put_slot_values(self.region, self.version, key, values)
                out[key] = values
        return out

    # ------------------------------------------------------------------ baselines
    def build(self, period: Period) -> dict:
        backfill = self.rules["history"].get("extend_beyond_weeks", False)
        refs, skipped = reference_periods(period, self.rules, candidates=backfill)
        values = self.slot_values(refs)
        ordered = [(p, values[p.key]) for p in refs]                # most recent first
        weeks = self.rules["history"]["weeks"]
        volume, kpi, green = defaultdict(list), defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
        used = set()

        def add(series: list, x, p: Period):
            # backfill: per series, the N most recent weeks with a value (a week without data is replaced)
            if x is not None and (not backfill or len(series) < weeks):
                series.append(x)
                used.add(p.key)

        for p, v in ordered:
            for link, x in v["volume"].items():
                add(volume[link], x, p)
            for site, fields in v["kpi"].items():
                for field, x in fields.items():
                    add(kpi[site][field], x, p)
            for site, links in v["green"].items():
                for link, x in links.items():
                    add(green[site][link], x, p)
        if backfill:
            refs = [p for p in refs if p.key in used] or refs[:weeks]
        env = lambda xs: {**stats.envelope(xs, self.rules), "values": [round(x, 3) for x in xs]}
        return {
            "version": self.version,
            "period": period.to_dict(),
            "reference_periods": [p.to_dict() for p in refs],
            "skipped_days": skipped,
            "volume": {link: env(xs) for link, xs in volume.items()},
            "kpi": {site: {field: env(xs) for field, xs in fields.items()} for site, fields in kpi.items()},
            "green": {site: {link: env(xs) for link, xs in links.items()} for site, links in green.items()},
        }

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
