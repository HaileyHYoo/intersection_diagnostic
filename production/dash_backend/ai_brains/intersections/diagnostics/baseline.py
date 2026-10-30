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
        refs, skipped = reference_periods(period, self.rules)
        values = self.slot_values(refs)
        ordered = [values[p.key] for p in refs]
        volume, kpi, green = defaultdict(list), defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
        for v in ordered:
            for link, x in v["volume"].items():
                volume[link].append(x)
            for site, fields in v["kpi"].items():
                for field, x in fields.items():
                    kpi[site][field].append(x)
            for site, links in v["green"].items():
                for link, x in links.items():
                    green[site][link].append(x)
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

    def precompute(self, days: list, slots: list[str] | None = None, progress=None) -> int:
        """The weekly job: baselines for every slot of the given analysis days."""
        minutes = self.rules["period_minutes"]
        slots = slots or [f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 24 * 60, minutes)]
        count = 0
        for day in days:
            periods = [period_at(day, slot, self.rules) for slot in slots]
            refs = {r.key: r for p in periods for r in reference_periods(p, self.rules)[0]}
            self.slot_values(list(refs.values()))           # one fetch per reference day
            for p in periods:
                self.store.put_baseline(self.region, self.version, p.key, self.build(p))
                count += 1
            if progress:
                progress(day, count)
        return count
