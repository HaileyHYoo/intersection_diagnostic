"""A synthetic Melbourne-like network for running the whole pipeline without the databases.

Every value is a deterministic function of (entity, timestamp), so any period can be asked for and the
history of a site is the same on every run. History has a few percent of noise around a daily profile;
the scenario period carries none, so a normal site is normal and each scenario site shows exactly the
behaviour it was built for:

    red_agree       Q1 N volume +45%, cycle stability poorer, N green share low; TomTom delay highest on N
    red_disagree    the same, but TomTom delay highest on another approach
    red_no_tomtom   the same, without any TomTom data
    amber_traffic   E volume -50%
    amber_signal    cycle length +30% and cycle stability poorer
    single_signal   cycle length +30% only (one Q3 measure -> Q3 normal -> Normal)
    detector_fail   one active detector counts 0 in the last 60 minutes   -> Detector Health Issue
    detector_gap    one active detector misses a 5-minute record           -> Grey
    volume_gap      one approach misses a 15-minute volume record           -> Grey
    no_green        one approach has HasGreen = 0 in the period             -> Grey
    kpi_gap         no IntersectionPerfKpi records in the period            -> Grey
    new_link        an EGRESS link with no history and one with no data     -> Normal (not evaluated)
    dirty           stamps a few seconds late, duplicates, quoted link IDs,
                    string values and an off-grid record                    -> Normal
    inactive_zero   an inactive detector recording zero                     -> Normal

Raw tags are emitted the way the live feeds hold them (quoted link IDs on "dirty" sites, numbers as
strings) and normalised with the same ids functions the live source uses.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta

from .. import ids
from ..series import ends_between
from ..timewin import Period, latest_period, to_utc

SCENARIOS = ["red_agree", "red_disagree", "red_no_tomtom", "amber_traffic", "amber_signal", "single_signal",
             "detector_fail", "detector_gap", "volume_gap", "no_green", "kpi_gap", "new_link", "dirty",
             "inactive_zero", "red_agree"]
EXPECTED = {"red_agree": "red", "red_disagree": "red", "red_no_tomtom": "red", "amber_traffic": "amber_traffic",
            "amber_signal": "amber_signal", "single_signal": "normal", "detector_fail": "detector_health",
            "detector_gap": "grey", "volume_gap": "grey", "no_green": "grey", "kpi_gap": "grey",
            "new_link": "normal", "dirty": "normal", "inactive_zero": "normal", "normal": "normal"}
BOUNDS = ["N", "E", "S", "W"]
STREETS = ["Swanston Street", "Elizabeth Street", "Queen Street", "William Street", "King Street",
           "Spencer Street", "Russell Street", "Exhibition Street", "Spring Street", "Lygon Street"]
CROSS = ["Flinders Street", "Collins Street", "Bourke Street", "Lonsdale Street", "La Trobe Street",
         "Victoria Street", "Grattan Street", "Queensberry Street", "Little Collins Street", "Little Bourke Street"]
GREEN_SPLIT = {"N": 34.0, "E": 22.0, "S": 30.0, "W": 14.0}
CBD = (-37.8136, 144.9631)


def unit(*key) -> float:
    """Deterministic number in [0, 1) for a key."""
    h = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2 ** 64


def time_of_day(local: datetime) -> float:
    h = local.hour + local.minute / 60
    return 0.25 + 0.9 * math.exp(-((h - 8.25) / 1.4) ** 2) + 0.8 * math.exp(-((h - 17.5) / 1.8) ** 2) \
        + 0.35 * math.exp(-((h - 13) / 3) ** 2)


class FakeSource:
    def __init__(self, rules: dict, schema: dict, scenario_end: datetime | str | None = None, n_sites: int = 48,
                 seed: int = 7, now: datetime | None = None):
        self.rules, self.schema, self.seed = rules, schema, seed
        self.region = rules["region"]
        self.provenance: list[dict] = []
        period = latest_period(rules, now) if scenario_end is None else None
        self.scenario_end = to_utc(scenario_end) if scenario_end is not None else period.end
        from ..timewin import zone
        self.tz = zone(rules)
        self._build(n_sites)

    # ------------------------------------------------------------------ network
    def _build(self, n: int) -> None:
        self.network = {}
        cols = 8
        for i in range(n):
            site = str(4300 + i * 3)
            scenario = SCENARIOS[i] if i < len(SCENARIOS) else "normal"
            r, c = divmod(i, cols)
            lat = CBD[0] + 0.0045 * (r - 3) + 0.0007 * (unit(site, "lat") - 0.5)
            lon = CBD[1] + 0.0055 * (c - 3.5) + 0.0007 * (unit(site, "lon") - 0.5)
            ns, ew = STREETS[c % len(STREETS)], CROSS[r % len(CROSS)]
            approaches = []
            for b in BOUNDS:
                street = ns if b in "NS" else ew
                link = (street[:4].upper() + b + site + "Q9")[:12]
                approaches.append({"link": link, "street": street, "bound": b,
                                   "base": 45 + 150 * unit(site, b, "base")})
            extra = []
            if scenario == "new_link":
                extra = [{"link": "NEWL" + site + "XX", "street": ns, "bound": "NE", "base": 60, "current_only": True},
                         {"link": "DEAD" + site + "XX", "street": ew, "bound": "SW", "base": 0, "never": True}]
            detectors = [{"detector": k + 1, "active": True, "link": approaches[k // 2]["link"]} for k in range(8)]
            if scenario == "inactive_zero":
                detectors.append({"detector": 9, "active": False, "link": approaches[0]["link"]})
            self.network[site] = {"site": site, "scenario": scenario, "lat": lat, "lon": lon, "streets": f"{ns}|{ew}",
                                  "approaches": approaches, "extra": extra, "detectors": detectors,
                                  "cycle": 70 + 40 * unit(site, "cycle"), "stability": 72 + 15 * unit(site, "stab"),
                                  "tomtom": scenario.startswith("red") and scenario != "red_no_tomtom"
                                  or unit(site, "tt") < 0.4}

    def expected(self) -> dict[str, str]:
        return {s: EXPECTED[n["scenario"]] for s, n in self.network.items()}

    # ------------------------------------------------------------------ helpers
    def _current(self, stamp: datetime, window_minutes: int = 30) -> bool:
        return self.scenario_end - timedelta(minutes=window_minutes) < stamp <= self.scenario_end

    def _noise(self, stamp: datetime, *key, scale=0.03) -> float:
        if self._current(stamp, 60):
            return 1.0
        return 1 + scale * (2 * unit(self.seed, stamp.isoformat(), *key) - 1)

    def _stamp(self, site: str, stamp: datetime) -> datetime:
        return stamp + timedelta(seconds=20) if self.network[site]["scenario"] == "dirty" else stamp

    def _link_tag(self, site: str, link: str) -> str:
        return "'" + link if self.network[site]["scenario"] == "dirty" else link

    def _value(self, site: str, value: float):
        return f"{value:.4f}" if self.network[site]["scenario"] == "dirty" else value

    def _volume(self, site: str, approach: dict, stamp: datetime) -> float:
        local = stamp.astimezone(self.tz)
        weekday = 0.8 if local.weekday() >= 5 else 1.0
        v = approach["base"] * time_of_day(local - timedelta(minutes=7)) * weekday
        v *= self._noise(stamp, site, approach["link"])
        scenario = self.network[site]["scenario"]
        if self._current(stamp, 60):
            if scenario.startswith("red") and approach["bound"] == "N":
                v *= 1.45
            if scenario == "amber_traffic" and approach["bound"] == "E":
                v *= 0.5
        return round(v, 1)

    def _ends(self, start, end, step):
        return ends_between(to_utc(start) - timedelta(minutes=step), to_utc(end), step)

    # ------------------------------------------------------------------ interface: network
    def sites(self):
        return [{"site": s, "lat": n["lat"], "lon": n["lon"], "streets": n["streets"]} for s, n in self.network.items()]

    def detectors(self, sites):
        wanted = set(sites)
        return [{"site": s, "detector": d["detector"], "active": d["active"]}
                for s, n in self.network.items() if s in wanted for d in n["detectors"]]

    def approaches(self, sites):
        wanted = set(sites)
        return [{"site": s, "link": a["link"], "street": a["street"]}
                for s, n in self.network.items() if s in wanted for a in n["approaches"] + n["extra"]]

    # ------------------------------------------------------------------ interface: time series
    def detector_counts(self, start, end):
        out = []
        for site, n in self.network.items():
            by_link = {a["link"]: a for a in n["approaches"]}
            for stamp in self._ends(start, end, 5):
                if not to_utc(start) <= stamp <= to_utc(end):
                    continue
                for d in n["detectors"]:
                    if not d["active"]:
                        value = 0.0
                    else:
                        value = self._volume(site, by_link[d["link"]], stamp) / 6
                    if self._current(stamp, 60):
                        if n["scenario"] == "detector_fail" and d["detector"] == 3:
                            value = 0.0
                        if n["scenario"] == "detector_gap" and d["detector"] == 5 and stamp == self.scenario_end - timedelta(minutes=20):
                            continue
                    out.append({"site": ids.site(site), "detector": d["detector"], "time": self._stamp(site, stamp),
                                "value": self._value(site, round(value, 1))})
        return out

    def link_volumes(self, start, end):
        out = []
        for site, n in self.network.items():
            for stamp in self._ends(start, end, 15):
                if not to_utc(start) <= stamp <= to_utc(end):
                    continue
                for a in n["approaches"] + n["extra"]:
                    if a.get("never") or (a.get("current_only") and not self._current(stamp)):
                        continue
                    if n["scenario"] == "volume_gap" and a["bound"] == "S" and stamp == self.scenario_end:
                        continue
                    row = {"link": ids.link(self._link_tag(site, a["link"])), "time": self._stamp(site, stamp),
                           "value": self._value(site, self._volume(site, a, stamp))}
                    out.append(row)
                    if n["scenario"] == "dirty" and a["bound"] == "N":
                        out.append({**row, "time": stamp + timedelta(seconds=5)})             # duplicate
                        out.append({**row, "time": stamp - timedelta(minutes=5), "value": 9999})  # off grid
        return out

    def site_kpi(self, start, end):
        out = []
        for site, n in self.network.items():
            for stamp in self._ends(start, end, 15):
                if not to_utc(start) <= stamp <= to_utc(end):
                    continue
                if n["scenario"] == "kpi_gap" and self._current(stamp):
                    continue
                local = stamp.astimezone(self.tz)
                cycle = n["cycle"] * (0.8 + 0.25 * time_of_day(local)) * self._noise(stamp, site, "cycle")
                stability = n["stability"] * self._noise(stamp, site, "stability", scale=0.02)
                if self._current(stamp):
                    if n["scenario"] in ("amber_signal", "single_signal"):
                        cycle *= 1.3
                    if n["scenario"].startswith("red") or n["scenario"] == "amber_signal":
                        stability *= 0.6
                for field, value in (("cycle_length", cycle), ("cycle_stability", stability)):
                    out.append({"site": site, "field": field, "time": self._stamp(site, stamp),
                                "value": self._value(site, round(value, 2))})
        return out

    def approach_perf(self, start, end):
        out = []
        for site, n in self.network.items():
            for stamp in self._ends(start, end, 15):
                if not to_utc(start) <= stamp <= to_utc(end):
                    continue
                for a in n["approaches"]:
                    share = GREEN_SPLIT[a["bound"]] * self._noise(stamp, site, a["link"], "green", scale=0.02)
                    has_green = 1.0
                    if self._current(stamp):
                        if n["scenario"].startswith("red") and a["bound"] == "N":
                            share *= 0.55
                        if n["scenario"] == "no_green" and a["bound"] == "W" and stamp == self.scenario_end:
                            has_green, share = 0.0, 0.0
                    link = ids.link(self._link_tag(site, a["link"]))
                    for field, value in (("green_share", round(share, 2)), ("has_green", has_green)):
                        out.append({"site": site, "link": link, "bound": a["bound"], "field": field,
                                    "time": self._stamp(site, stamp), "value": self._value(site, value)})
        return out

    def tomtom_mapping(self, site):
        n = self.network.get(ids.site(site))
        if not n or not n["tomtom"]:
            return {}
        return {str(-1000 - 10 * k - int(site)): {"link": a["link"], "street": a["street"], "direction": a["bound"]}
                for k, a in enumerate(n["approaches"])}

    def tomtom_turn_kpi(self, site, start, end):
        n = self.network.get(ids.site(site))
        if not n or not n["tomtom"]:
            return []
        worst = {"red_agree": "N", "red_disagree": "E"}.get(n["scenario"])
        out = []
        mapping = self.tomtom_mapping(site)
        for stamp in self._ends(start, end, 15):
            if not to_utc(start) <= stamp <= to_utc(end):
                continue
            for approach_id, entry in mapping.items():
                b = entry["direction"]
                delay = (12 + 25 * unit(site, b, "delay")) * self._noise(stamp, site, b, "tt", scale=0.1)
                if self._current(stamp) and b == worst:
                    delay *= 3.0
                for k, exit_id in enumerate(("1", "2", "3")):
                    share = (0.2, 0.6, 0.2)[k]
                    values = {"approach_delay": delay, "control_delay": delay * (0.8 + 0.2 * k),
                              "multi_stop_rate": 0.05 + delay / 400, "turn_ratio": share * 100,
                              "sample_count": round(20 * share * time_of_day(stamp.astimezone(self.tz)) + 1)}
                    for field, value in values.items():
                        out.append({"site": site, "approach": approach_id, "exit": approach_id + "-" + exit_id,
                                    "field": field, "time": stamp, "value": round(value, 3)})
        return out

    def tomtom_site_kpi(self, site, start, end):
        rows = self.tomtom_turn_kpi(site, start, end)
        out = {}
        for r in rows:
            if r["field"] == "control_delay":
                key = r["time"]
                out.setdefault(key, []).append(r["value"])
        return [{"site": site, "field": "control_delay", "time": t, "value": sum(v) / len(v)} for t, v in out.items()]

    def cycle_length_fallback(self, start, end):
        return []

    def scenario_period(self) -> Period:
        return Period(self.scenario_end - timedelta(minutes=self.rules["period_minutes"]), self.scenario_end,
                      self.rules.get("timezone", "Australia/Melbourne"))
