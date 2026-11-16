"""Readings of a Red site: the quarter-hour view, the phases, and a small table of hypotheses with the evidence for
and against each (17 Nov 2026).

The table is a differential diagnosis: a fixed catalogue of readings, each scored from the site's own data. It ranks
the readings by the evidence available; it does not prove a cause. Strength of evidence (not a probability):

    Strong    two or more points for, none against, and no data limitation
    Moderate  one point for and none against, or two or more for and one against, or Strong with a data limitation
              (history at the 5-week minimum, a tolerated detector)
    Weak      anything else with at least one point for

A reading with no point for is left out.
"""
from __future__ import annotations

from ..stats import ABNORMAL

CATALOGUE = {          # key: the exact name used in the text (checked in an LLM wording)
    "data": "a data or mapping issue",
    "other_phases": "green given to other phases",
    "demand": "a response to demand",
    "plan": "a plan or coordination change",
    "event": "unusual demand (incident, event or diversion)",
}
STRENGTHS = ("Strong", "Moderate", "Weak")
OPPOSITE = "the opposite of a demand response"
MORE_LESS = {"HIGH": ("higher", "longer", "more green"), "LOW": ("lower", "shorter", "less green")}
KPI_FIELDS = {"cycle_length_s": "AvgCycle", "cycle_cv_pct": "CycleCvPct", "cycle_stability": "CycleStability"}


def _r(x, d=1):
    return None if x is None else round(float(x), d)


def _and(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _phase_set(value) -> tuple[str, ...] | None:
    if not value or not isinstance(value, str):
        return None
    return tuple(sorted(p.strip() for p in value.split(",") if p.strip())) or None


def _phases_text(ph: tuple[str, ...]) -> str:
    return ("phase " if len(ph) == 1 else "phases ") + _and(list(ph))


# ---------------------------------------------------------------------------------------------- quarter-hour view
def quarter_view(site: dict, detail: dict | None, schema: dict | None = None) -> dict | None:
    """Per quarter-hour: cycle length, cycle variation, stability, volume and green share per approach, and the
    phases serving each approach (IntersectionPerfApproach "Phases")."""
    if not detail or not detail.get("quarters"):
        return None
    from ..names import approach_label
    green_field = ((schema or {}).get("influx", {}).get("sources", {}).get("approach_perf", {})
                   .get("fields", {}).get("green_share", "GreenShare"))
    kpi_fields = dict(KPI_FIELDS)
    for key, logical in (("cycle_length_s", "cycle_length"), ("cycle_stability", "cycle_stability")):
        kpi_fields[key] = ((schema or {}).get("influx", {}).get("sources", {}).get("site_kpi", {})
                           .get("fields", {}).get(logical, kpi_fields[key]))
    labels = {}
    for a in (site.get("q1") or {}).get("approaches") or []:
        labels[a["link"]] = approach_label(a)
    for a in ((site.get("q3") or {}).get("components") or {}).get("phase_service", {}).get("approaches") or []:
        labels.setdefault(a["link"], approach_label(a))
    view = {"quarters": detail["quarters"],
            **{key: [_r(q.get(field)) for q in detail["kpi"]] for key, field in kpi_fields.items()},
            "volume": {}, "green_share": {}, "phases": {}, "phases_changed": []}
    for link, values in (detail.get("volume") or {}).items():
        if link in labels:
            view["volume"][labels[link]] = [_r(v, 0) for v in values]
    for link, per_q in (detail.get("approaches") or {}).items():
        if link not in labels:
            continue
        label = labels[link]
        view["green_share"][label] = [_r(q.get(green_field)) for q in per_q]
        sets = [_phase_set(q.get("Phases")) for q in per_q if _phase_set(q.get("Phases"))]
        if sets:
            view["phases"][label] = ",".join(sets[-1])
            if len(set(sets)) > 1:
                view["phases_changed"].append(label)
    if not any(view[k] and any(v is not None for v in view[k]) for k in KPI_FIELDS) and not view["green_share"]:
        return None
    return view


def all_phases(view: dict | None) -> tuple[str, ...]:
    if not view:
        return ()
    return tuple(sorted({p for v in view["phases"].values() for p in v.split(",")}))


def served_in_every_phase(view: dict | None, label: str) -> bool:
    every = all_phases(view)
    return bool(every) and label in (view or {}).get("phases", {}) and tuple(view["phases"][label].split(",")) == every


# ---------------------------------------------------------------------------------------------- phase shifts
def phase_shifts(ev: dict, view: dict | None) -> list[dict]:
    """Per abnormal phase-service group: the phases serving it, the rest of the cycle, and the other approaches
    served by the rest. Green shares are of the cycle, so the phases not serving the approach take the remainder."""
    if not view or not view["phases"]:
        return []
    rows = {a["approach"]: a for a in ev["signal"]["phase_service"]["abnormal_approaches"]}
    every = all_phases(view)
    out = []
    for group in ev.get("phase_groups") or [[k] for k in rows]:
        a = rows[group[0]]
        own = view["phases"].get(group[0])
        if not own or a["current_green_share_pct"] is None or a["usual_green_share_pct"] is None:
            continue
        own_set = tuple(own.split(","))
        rest = tuple(p for p in every if p not in own_set)
        if not rest:
            continue
        # approaches served by the rest of the cycle; one served in every phase is green all cycle, so it says
        # nothing about where the green went
        others = sorted(k for k, v in view["phases"].items()
                        if k not in group and set(v.split(",")) & set(rest) and tuple(v.split(",")) != every)
        q_own = view["green_share"].get(group[0]) or []
        out.append({"approaches": group, "phases": ",".join(own_set), "other_phases": ",".join(rest),
                    "direction": a["direction"], "current": a["current_green_share_pct"],
                    "usual": a["usual_green_share_pct"],
                    "other_current": _r(100 - a["current_green_share_pct"]),
                    "other_usual": _r(100 - a["usual_green_share_pct"]),
                    "by_quarter": q_own, "other_by_quarter": [_r(100 - v) if v is not None else None for v in q_own],
                    "other_approaches": others})
    return out


def onset(view: dict | None, ev: dict) -> dict:
    """Which quarter-hour carries the change: {"signal": 0|1|None, "volume": {label: 0|1}}. A change is in one
    quarter when the cycle variation goes from at most 1% to more than 2%, or a green share moves by 5 pp or more
    between the quarters while the other quarter is within its normal range."""
    if not view or len(view["quarters"]) != 2:
        return {"signal": None, "volume": {}}
    sig = None
    cv = view["cycle_cv_pct"]
    if None not in cv:
        if cv[0] <= 1 < 2 < cv[1]:
            sig = 1
        elif cv[1] <= 1 < 2 < cv[0]:
            sig = 0
    if sig is None:
        for a in ev["signal"]["phase_service"]["abnormal_approaches"]:
            q = view["green_share"].get(a["approach"]) or []
            lo, hi = a.get("normal_range") or (None, None)
            if len(q) == 2 and None not in q and lo is not None and abs(q[1] - q[0]) >= 5:
                inside = [lo <= v <= hi for v in q]
                if inside[0] and not inside[1]:
                    sig = 1
                elif inside[1] and not inside[0]:
                    sig = 0
            if sig is not None:
                break
    vol = {}
    for a in ev["traffic"]["abnormal_approaches"]:
        q = view["volume"].get(a["approach"]) or []
        if len(q) == 2 and None not in q and min(q) > 0 and max(q) / min(q) >= 1.15:
            vol[a["approach"]] = 0 if (q[0] > q[1]) == (a["direction"] == "HIGH") else 1
    return {"signal": sig, "volume": vol}


def timing_sentences(view: dict | None, ev: dict) -> list[str]:
    if not view or len(view["quarters"]) != 2:
        return []
    q = view["quarters"]
    on = onset(view, ev)
    out = []
    for label, k in on["volume"].items():
        v = view["volume"][label]
        out.append(f"On {label} most of the change is in {q[k]} ({v[0]:.0f} then {v[1]:.0f} vehicles per 15 minutes).")
    cl, cv, st = view["cycle_length_s"], view["cycle_cv_pct"], view["cycle_stability"]
    if on["signal"] is not None and None not in cl and None not in cv:
        k = on["signal"]
        out.append(f"The signal change starts in {q[k]}: cycle length {cl[0]:.1f} s then {cl[1]:.1f} s, cycle "
                   f"variation {cv[0]:.1f}% then {cv[1]:.1f}%"
                   + (f", stability {st[0]:.1f} then {st[1]:.1f}" if None not in st else "") + ".")
    elif None not in cl and None not in cv and ev["signal"]["cycle_stability"]["status"] == ABNORMAL:
        out.append(f"Cycle length {cl[0]:.1f} s then {cl[1]:.1f} s and cycle variation {cv[0]:.1f}% then "
                   f"{cv[1]:.1f}% across the two quarter-hours, so the change covers the whole period.")
    return out


def shift_sentences(shifts: list[dict], view: dict | None) -> list[str]:
    out = []
    for s in shifts:
        own, rest = tuple(s["phases"].split(",")), tuple(s["other_phases"].split(","))
        who = (f"which serve {_and(s['other_approaches'])}" if s["other_approaches"]
               else "which serve none of the assessed approaches (side road, turning or pedestrian movements)")
        q = ""
        if view and len(s["by_quarter"]) == 2 and None not in s["by_quarter"]:
            q = f" ({view['quarters'][0]} {s['by_quarter'][0]:.1f}%, {view['quarters'][1]} {s['by_quarter'][1]:.1f}%)"
        text = _phases_text(own)
        out.append(f"{text[0].upper() + text[1:]}, serving {_and(s['approaches'])}, took {s['current']:.1f}% of "
                   f"the cycle against a usual {s['usual']:.1f}%{q}; {_phases_text(rest)}, {who}, took "
                   f"{s['other_current']:.1f}% against a usual {s['other_usual']:.1f}%.")
    return out


# ---------------------------------------------------------------------------------------------- readings
def readings(ev: dict) -> list[dict]:
    """The hypothesis table, most supported first: [{key, name, for, against, strength}]."""
    t, s = ev["traffic"], ev["signal"]
    cl, cs = s["cycle_length_s"], s["cycle_stability"]
    traffic = {a["approach"]: a["direction"] for a in t["abnormal_approaches"]}
    service = {a["approach"]: a for a in s["phase_service"]["abnormal_approaches"]}
    view, shifts = ev.get("quarter_view"), ev.get("phase_shifts") or []
    on = onset(view, ev)
    pro = {k: [] for k in CATALOGUE}
    con = {k: [] for k in CATALOGUE}

    # demand: phase service or cycle moving with the volume
    for k, a in service.items():
        own = traffic.get(k)
        if own == a["direction"]:
            pro["demand"].append(f"{MORE_LESS[a['direction']][2]} to {k} with {MORE_LESS[own][0]} volume")
        elif own:
            con["demand"].append(f"{MORE_LESS[a['direction']][2]} to {k} while its volume is {MORE_LESS[own][0]} "
                                 f"is {OPPOSITE}")
    if cl["status"] == ABNORMAL:
        longer = MORE_LESS[cl["direction"]]
        matching = [k for k, d in traffic.items() if d == cl["direction"]]
        opposite = [k for k, d in traffic.items() if d != cl["direction"]]
        if matching:
            pro["demand"].append(f"a {longer[1]} cycle with {longer[0]} volume on {_and(matching)}")
        if opposite and matching:
            other = MORE_LESS["LOW" if cl["direction"] == "HIGH" else "HIGH"][0]
            why = (f"volume is {longer[0]} on {_and(matching)} but {other} on {_and(opposite)}, so the {longer[1]} "
                   "cycle is not clearly a response to demand")
            con["demand"].append(why)
            pro["plan"].append(why)
        elif not matching:
            why = f"the {longer[1]} cycle is not matched by {longer[0]} volume"
            con["demand"].append(why)
            pro["plan"].append(why)

    # other phases: an approach losing green to the rest of the cycle
    for sh in shifts:
        if sh["direction"] != "LOW":
            continue
        pro["other_phases"].append(f"{_phases_text(tuple(sh['other_phases'].split(',')))} took "
                                   f"{sh['other_current']:.1f}% of the cycle against a usual {sh['other_usual']:.1f}%")
        gaining = [k for k in sh["other_approaches"] if traffic.get(k) == "HIGH"
                   or (service.get(k) or {}).get("direction") == "HIGH"]
        if gaining:
            pro["other_phases"].append(f"volume or green is higher than usual on {_and(gaining)}, served by those phases")
    a1 = [k for k, a in service.items() if a["direction"] == "LOW" and traffic.get(k) == "HIGH"]
    if a1:
        pro["other_phases"].append(f"less green to {_and(a1)} while {'its' if len(a1) == 1 else 'their'} volume is "
                                   f"higher is {OPPOSITE}")
    elif not shifts:
        lows = [k for k, a in service.items() if a["direction"] == "LOW"]
        if lows:
            pro["other_phases"].append(f"less green to {_and(lows)}")

    # plan or coordination change (a cycle change matched by volume is read as demand above)
    if cl["status"] == ABNORMAL and not traffic:
        pro["plan"].append(f"cycle length {cl.get('current')} s against a usual {cl.get('usual')} s with no volume change")
    if cs["status"] == ABNORMAL and cs.get("usual") is not None and cs["usual"] >= 99:
        pro["plan"].append(f"the usually fixed cycle varied (Cycle Stability {cs['current']} against a usual {cs['usual']})")
    if view and on["signal"] is not None:
        q = view["quarters"]
        con["plan"].append(f"{q[1 - on['signal']]} ran the usual cycle, so the change is not a plan for the whole period")
    elif view and cs["status"] == ABNORMAL and None not in view["cycle_cv_pct"] \
            and min(view["cycle_cv_pct"]) > 2:
        pro["plan"].append("the cycle varied in both quarter-hours")
    if cl["status"] != ABNORMAL and cs["status"] != ABNORMAL:
        con["plan"].append("cycle length and stability are within their usual behaviour")

    # unusual demand
    if ev["traffic_only_approaches"]:
        pro["event"].append(f"the volume change on {_and(ev['traffic_only_approaches'])} has no phase-service finding")
    up = [k for k, d in traffic.items() if d == "HIGH"]
    if len(up) >= 2:
        pro["event"].append(f"volume is higher on {len(up)} approaches")
    for label, k in on["volume"].items():
        pro["event"].append(f"the change on {label} is concentrated in {view['quarters'][k]}")

    # data or mapping
    for m in ev.get("mapping_checks") or []:
        pro["data"].append(f"a usual {m['measure']} of {'100%' if m['measure'] == 'green share' else '0'} on "
                           f"{m['approach']}")
    for d in ev.get("tolerated_detectors") or []:
        pro["data"].append(f"detector {d['detector']} counted fewer than {d['threshold']} vehicles in 60 minutes, so "
                           "the volume of its approach may be under-counted")
    for k, a in service.items():
        lo, hi = a.get("normal_range") or (None, None)
        if lo is not None and hi is not None and hi - lo >= 40:
            pro["data"].append(f"the normal range of the green share on {k} is wide ({lo:.1f}-{hi:.1f}%), so its "
                               "usual value mixes different operation")
    for label in (view or {}).get("phases_changed", []):
        pro["data"].append(f"the phases serving {label} changed between the quarter-hours")

    limited = bool(ev.get("tolerated_detectors")) or (ev.get("min_history") or 99) <= 5
    out = []
    for key, name in CATALOGUE.items():
        p, c = pro[key], con[key]
        if not p:
            continue
        if len(p) >= 2 and not c:
            strength = "Moderate" if limited else "Strong"
        elif (len(p) >= 1 and not c) or (len(p) >= 2 and len(c) == 1):
            strength = "Moderate"
        else:
            strength = "Weak"
        out.append({"key": key, "name": name, "for": p, "against": c, "strength": strength})
    order = list(CATALOGUE)
    out.sort(key=lambda r: (STRENGTHS.index(r["strength"]), -(len(r["for"]) - len(r["against"])), order.index(r["key"])))
    return out


def reading_lines(table: list[dict]) -> tuple[str, str, str]:
    """(strength of the main reading, its sentence, the other readings' sentence)."""
    if not table:
        return "Weak", "no reading is supported by these data beyond the findings above.", \
               "none of the catalogued readings is supported by these data."
    top = table[0]
    main = f"{top['name']}: " + "; ".join(top["for"])
    if top["against"]:
        main += ", although " + "; ".join(top["against"])
    others = []
    for r in table[1:]:
        if r["against"]:
            others.append(f"{r['name']} ({r['strength'].lower()}; against: {'; '.join(r['against'])})")
        else:
            others.append(f"{r['name']} ({r['strength'].lower()}; for: {'; '.join(r['for'])})")
    return top["strength"], main + ".", ("; ".join(others) + ".") if others else "no other reading is supported by these data."


def check_for(r: dict, ev: dict, window: str) -> str | None:
    """The first engineering check for a reading: verify it, then what to review if it is confirmed."""
    shifts = ev.get("phase_shifts") or []
    service = [a["approach"] for a in ev["signal"]["phase_service"]["abnormal_approaches"]]
    if r["key"] == "other_phases":
        lows = [sh for sh in shifts if sh["direction"] == "LOW"]
        if lows:
            rest = _phases_text(tuple(lows[0]["other_phases"].split(",")))
            return (f"In SCATS History for {window}, find which of {rest} extended or was called more often, and why "
                    "(pedestrian calls, side-road or turning demand, phase skips); if it recurs on the same weekday, "
                    f"review the maximum times of {rest} or the plan selection.")
        return (f"In SCATS History for {window}, find which phases took the green lost by {_and(service)} and why; if "
                "it recurs on the same weekday, review those phases' maximum times or the plan selection.")
    if r["key"] == "demand":
        return (f"Confirm in SCATS History for {window} that the phases serving the busier approaches reached their "
                "maximum in most cycles; if the higher demand persists on the same weekday, review whether the plan's "
                "maximums and splits fit it.")
    if r["key"] == "plan":
        return (f"Check the plan number, subsystem cycle length and linking/offsets in force for {window} against the "
                "usual weekday; if a plan or coordination change is found, confirm that it was intended.")
    if r["key"] == "event":
        names = ev["traffic_only_approaches"] or [a["approach"] for a in ev["traffic"]["abnormal_approaches"]]
        view, vol = ev.get("quarter_view"), onset(ev.get("quarter_view"), ev)["volume"]
        when = view["quarters"][vol[names[0]]] if view and names[0] in vol else "the period"
        return (f"Check for incidents, events, roadworks or diversions affecting {_and(names)} during {when}, and "
                "compare the same time next week.")
    return None                                     # data: the mapping and detector checks are written separately
