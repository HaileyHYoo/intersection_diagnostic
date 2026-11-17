"""Readings of a Red site: the quarter-hour view, the phases, and a small table of hypotheses with the evidence for
and against each (17 Nov 2026).

The table is a differential diagnosis: a fixed catalogue of readings, each scored from the site's own data. It ranks
the readings by the evidence available; it does not prove a cause. Strength of evidence (not a probability) comes
from a score: points that discriminate between readings weigh 2, points that restate a screening finding weigh 1,
points against are subtracted (see weight() and readings()).

A reading with no point for is left out.
"""
from __future__ import annotations

import re

from ..stats import ABNORMAL

CATALOGUE = {          # key: the exact name used in the text (checked in an LLM wording)
    "data": "a data or mapping issue",
    "other_phases": "a local controller response (phase extensions, skips or pedestrian calls)",
    "demand": "a response to demand",
    "plan": "a subsystem decision (cycle, plan or coordination)",
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


def _solve(rows: list[list[float]], b: list[float]) -> list[float] | None:
    """Least squares by the normal equations; None unless every unknown is determined."""
    k = len(rows[0])
    a = [[sum(r[i] * r[j] for r in rows) for j in range(k)] + [sum(r[i] * y for r, y in zip(rows, b))] for i in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda i: abs(a[i][c]))
        if abs(a[p][c]) < 1e-9:
            return None
        a[c], a[p] = a[p], a[c]
        for i in range(k):
            if i != c:
                f = a[i][c] / a[c][c]
                a[i] = [x - f * y for x, y in zip(a[i], a[c])]
    return [a[i][k] / a[i][i] for i in range(k)]


def phase_shares(ev: dict, view: dict | None) -> list[dict]:
    """The share of the cycle of each phase (or group of phases always serving the same approaches), solved from the
    approaches' green shares and their "Phases": the green share of an approach is the sum of the shares of its
    phases, and the phases fill the cycle. Empty when the phases are not read or the shares are not determined or
    not consistent (more than 1.5 pp off for the current values, 4 pp for the usual medians)."""
    if not view or not view["phases"]:
        return []
    every = all_phases(view)
    # an approach served in every phase only restates that the phases fill the cycle (its usual median can be below
    # 100 when a week ran other phases), so it is left out of the equations
    rows = {a["approach"]: a for a in ev.get("phase_service_all") or []
            if a["approach"] in view["phases"] and a.get("current") is not None and a.get("usual") is not None
            and tuple(view["phases"][a["approach"]].split(",")) != every}
    if not rows:
        return []
    sets = {k: set(view["phases"][k].split(",")) for k in rows}
    atoms: dict[tuple, list[str]] = {}
    for ph in every:
        atoms.setdefault(tuple(ph in sets[k] for k in sorted(sets)), []).append(ph)
    atoms_list = [tuple(sorted(v)) for v in atoms.values()]
    eq = [[1.0 if set(at) <= sets[k] else 0.0 for at in atoms_list] for k in sorted(sets)] + [[1.0] * len(atoms_list)]

    def solve(values: dict, tol: float):
        b = [values[k] for k in sorted(sets)] + [100.0]
        x = _solve(eq, b)
        if x is None or any(abs(sum(c * v for c, v in zip(r, x)) - y) > tol for r, y in zip(eq, b)):
            return None
        return [_r(v) for v in x]

    cur = solve({k: rows[k]["current"] for k in sets}, 1.5)
    if cur is None:
        return []
    # usual medians that fit no single split: the reference weeks ran different splits (plans); shown without usual
    usual = solve({k: rows[k]["usual"] for k in sets}, 4.0) or [None] * len(atoms_list)
    quarters = []
    for q in range(len(view["quarters"])):
        vals = {k: (view["green_share"].get(k) or [None] * (q + 1))[q] for k in sets}
        quarters.append(solve(vals, 1.5) if None not in vals.values() else None)
    out = []
    for i, at in enumerate(atoms_list):
        serves = [k for k in sorted(sets) if set(at) <= sets[k] and tuple(sorted(sets[k])) != every]
        out.append({"phases": ",".join(at), "current": cur[i], "usual": usual[i],
                    "change": None if usual[i] is None else _r(cur[i] - usual[i]),
                    "by_quarter": [q[i] if q else None for q in quarters], "serves": serves})
    return out


def mixed_splits(shares: list[dict]) -> bool:
    return bool(shares) and any(s["usual"] is None for s in shares)


def phase_share_sentences(shares: list[dict], quarters: list[str] | None = None, brief: bool = False) -> list[str]:
    if not shares:
        return []
    if mixed_splits(shares):
        parts = ", ".join(f"{_phases_text(tuple(s['phases'].split(',')))} {s['current']:.1f}%" for s in shares)
        if brief:
            return [f"Share of the cycle by phase now: {parts} (the reference weeks ran different splits)."]
        return [f"Share of the cycle by phase now: {parts}. The usual green shares of the approaches do not fit one "
                "split, so the reference weeks ran different splits and no usual share by phase is given."]
    parts = ", ".join(f"{_phases_text(tuple(s['phases'].split(',')))} {s['current']:.1f}% ({s['usual']:.1f}%)"
                      for s in shares)
    out = [f"Share of the cycle by phase, current (usual): {parts}."]
    lost = min(shares, key=lambda s: s["change"])          # every change is set here (mixed splits returned above)
    gained = max(shares, key=lambda s: s["change"])
    if lost["change"] <= -3:
        who = f", serving {_and(lost['serves'])}," if lost["serves"] else ", serving none of the assessed approaches,"
        text = _phases_text(tuple(lost["phases"].split(",")))
        q = lost["by_quarter"]
        when = (f" ({quarters[0]} {q[0]:.1f}%, {quarters[1]} {q[1]:.1f}%)"
                if quarters and len(quarters) == 2 and len(q) == 2 and None not in q else "")
        out.append(f"{text[0].upper() + text[1:]}{who} lost {abs(lost['change']):.1f} percentage points{when}"
                   + (f"; {_phases_text(tuple(gained['phases'].split(',')))} gained {gained['change']:.1f}" 
                      if gained["change"] >= 3 else "") + ".")
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


def control_sentence(ctx: dict | None, brief: bool = False) -> str | None:
    """Where the site sits in SCATS control (subsystem membership; marriages and the critical site are not known)."""
    if not ctx:
        return None
    name = f"subsystem {ctx['subsystem']} of Region {ctx['region']}"
    crit = ((ctx.get("status") or {}).get("now") or {}).get("critical_site")
    if crit and not ctx["single_site"]:
        name += f" (critical site {crit})"
    if ctx["single_site"]:
        return f"Control: the site is the only site of {name}, so its cycle is set from its own measurements."
    parts = []
    for o in ctx["others"]:
        c = o.get("cycle_length_s") or {}
        cyc = (f"; cycle {c['current']:.1f} s against a usual {c['usual']:.1f} s"
               if c.get("current") is not None and c.get("usual") is not None else "")
        label = o["category"].replace("_", " - ").replace("amber", "Amber").replace("red", "Red") \
            .replace("normal", "Normal").replace("grey", "Grey").replace("detector - health", "Detector Health")
        parts.append(f"{o['site']}" + (f" {o['name']}" if o.get("name") else "") + f" ({label}{cyc})")
    if brief:
        return f"Control: {name}, shared with {_and(parts)}."
    return f"Control: {name}, shared with {_and(parts)}; SCATS sets the cycle length and plan per subsystem."


def status_sentence(ctx: dict | None, quarters: list[str] | None = None) -> str | None:
    """The subsystem's degree of saturation (DS), required cycle (RL) and active cycle (CL) in the period."""
    st = (ctx or {}).get("status")
    if not st:
        return None
    n, u = st["now"], st["usual"]
    crit = f", critical site {n['critical_site']}" if n.get("critical_site") else ""
    usual = f" (usual median {u['ds_median']:.0f})" if u.get("ds_median") is not None else ""
    inner = [] if n["cl_min"] == n["cl_max"] else [f"mean {n['cl_mean']:.1f} s"]
    if u.get("cl_mean") is not None:
        inner.append(f"usual {u['cl_mean']:.1f} s")
    cycle = (f"active cycle constant at {n['cl_mean']:.1f} s" if n["cl_min"] == n["cl_max"]
             else f"active cycle {n['cl_min']:.0f}-{n['cl_max']:.0f} s") + (f" ({', '.join(inner)})" if inner else "")
    text = (f"Subsystem {ctx['region']}-{ctx['subsystem']}{crit}: degree of saturation median {n['ds_median']:.0f}"
            f"{usual}, up to {n['ds_max']:.0f}, at 100 or more in {n['ds_at_least_100']} of {n['records']} records; "
            f"{cycle} against a required cycle of mean {n['rl_mean']:.1f} s; the active cycle was within 2 s of the "
            f"required cycle in {n['cl_with_rl']} records and at least 3 s above it in {n['cl_above_rl']}.")
    q = n.get("by_quarter") or []
    if quarters and len(q) == 2 and all(q):
        text += (f" Saturation median by quarter-hour: {quarters[0]} {q[0]['ds_median']:.0f}, {quarters[1]} "
                 f"{q[1]['ds_median']:.0f}.")
    return text


def status_brief(ctx: dict | None) -> str | None:
    """One clause on the subsystem for the diagnosis (the full statement is in the supporting evidence)."""
    st = (ctx or {}).get("status")
    if not st:
        return None
    n, u = st["now"], st["usual"]
    usual = f" (usual {u['ds_median']:.0f})" if u.get("ds_median") is not None else ""
    cycle = (f"constant at {n['cl_mean']:.1f} s" if n["cl_min"] == n["cl_max"]
             else f"{n['cl_min']:.0f}-{n['cl_max']:.0f} s")
    if n["cl_with_rl"] >= 0.6 * n["records"]:
        cycle += ", following the required cycle"
    elif n["cl_above_rl"] >= 0.5 * n["records"]:
        cycle += f", above the required cycle (mean {n['rl_mean']:.1f} s)"
    return f"Subsystem saturation median {n['ds_median']:.0f}{usual}; active cycle {cycle}."


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
        verb = "serve" if len(rest) > 1 else "serves"
        who = (f"which {verb} {_and(s['other_approaches'])}" if s["other_approaches"]
               else f"which {verb} none of the assessed approaches (side road, turning or pedestrian movements)")
        q = ""
        if view and len(s["by_quarter"]) == 2 and None not in s["by_quarter"]:
            q = f" ({view['quarters'][0]} {s['by_quarter'][0]:.1f}%, {view['quarters'][1]} {s['by_quarter'][1]:.1f}%)"
        text = _phases_text(own)
        out.append(f"{text[0].upper() + text[1:]}, serving {_and(s['approaches'])}, took {s['current']:.1f}% of "
                   f"the cycle against a usual {s['usual']:.1f}%{q}; {_phases_text(rest)}, {who}, took "
                   f"{s['other_current']:.1f}% against a usual {s['other_usual']:.1f}%.")
    return out


# ---------------------------------------------------------------------------------------------- readings
# Points that discriminate between readings weigh 2; points that restate a screening finding (true at most Red sites)
# weigh 1. Calibrated on the AM peak of 10 Nov 2026 (83 Red sites): with counts alone every leading reading was
# Moderate and the first two readings were close at 73% of the sites.
SPECIFIC = re.compile("|".join([
    r"percentage points and serves?", r"% of the cycle against a usual", OPPOSITE, r"subsystem's active cycle stayed at",
    r"degree of saturation was higher than usual", r"\(usually \d+% of records\)", r"followed the required cycle",
    r"above the required cycle", r"fit no single split", r"same cycle as", r"cycle change is shared by",
    r"kept its usual cycle", r"ran the usual cycle", r"stayed at its usual level", r"changed between the quarter-hours",
    r"usual green share of 100%", r"usual volume of 0", r"is concentrated in", r"did not change \("]))


def weight(point: str) -> int:
    return 2 if SPECIFIC.search(point) else 1


def readings(ev: dict) -> list[dict]:
    """The hypothesis table, most supported first: [{key, name, for, against, strength, score}].

    score = weighted points for - weighted points against (weight()); Strong: score 5 or more, nothing against and no
    tolerated detector; Moderate: score 3 or more, or 2 with nothing against; Weak: the rest."""
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

    # green moved between phases: towards busier approaches (demand) or elsewhere (local controller response)
    shares = ev.get("phase_shares") or []
    mixed = mixed_splits(shares)
    if mixed:
        pro["plan"].append("the usual green shares of its approaches fit no single split, so the reference weeks ran "
                           "different splits (plans)")
        shares, shifts = [], []                 # usual shares by phase are not defined: no claim of a shift
    busier = {k for k, d in traffic.items() if d == "HIGH"}
    if shares:
        for g in [x for x in shares if x["change"] is not None and x["change"] >= 3]:
            text = f"{_phases_text(tuple(g['phases'].split(',')))} gained {g['change']:.1f} percentage points"
            verb = "serve" if "," in g["phases"] else "serves"
            to_busier = sorted(set(g["serves"]) & busier)
            if to_busier:
                pro["demand"].append(f"{text} and {verb} {_and(to_busier)}, where volume is higher")
            else:
                who = (f"{verb} {_and(g['serves'])}, where volume is not higher" if g["serves"]
                       else f"{verb} none of the assessed approaches (side road, turning or pedestrian movements)")
                pro["other_phases"].append(f"{text} and {who}")
    else:
        for sh in shifts:
            if sh["direction"] != "LOW":
                continue
            gaining = [k for k in sh["other_approaches"] if traffic.get(k) == "HIGH"
                       or (service.get(k) or {}).get("direction") == "HIGH"]
            text = (f"{_phases_text(tuple(sh['other_phases'].split(',')))} took {sh['other_current']:.1f}% of the cycle "
                    f"against a usual {sh['other_usual']:.1f}%")
            if gaining:
                verb = "serve" if "," in sh["other_phases"] else "serves"
                pro["demand"].append(f"{text} and {verb} {_and(gaining)}, where volume or green is higher")
            else:
                pro["other_phases"].append(text)
    competing = any("where volume" in x for x in pro["demand"])     # green shown to go to busier approaches
    a1 = [k for k, a in service.items() if a["direction"] == "LOW" and traffic.get(k) == "HIGH"]
    if a1 and not competing:
        pro["other_phases"].append(f"less green to {_and(a1)} while {'its' if len(a1) == 1 else 'their'} volume is "
                                   f"higher is {OPPOSITE}")
    elif not shares and not shifts and not mixed:
        lows = [k for k, a in service.items() if a["direction"] == "LOW"]
        if lows:
            pro["other_phases"].append(f"less green to {_and(lows)}")
    n_assessed = ev["traffic"].get("approaches_assessed") or 0
    if len(busier) >= 2 and n_assessed and len(busier) / n_assessed >= 0.6:
        pro["demand"].append(f"volume is higher on {len(busier)} of {n_assessed} approaches")
    # the opposite-direction point counts against demand unless the lost green is shown to go to busier approaches
    con["demand"] = [c for c in con["demand"] if OPPOSITE not in c]
    if not competing:
        con["demand"] += [f"less green to {k} while its volume is higher is {OPPOSITE}" for k in a1]

    # subsystem decision: the cycle is set per subsystem (control context, subsystems.py)
    ctx = ev.get("control")
    if ctx and (cl["status"] == ABNORMAL or cs["status"] == ABNORMAL):
        from ..subsystems import shared_cycle
        sc = shared_cycle(ctx, cl)
        name = f"subsystem {ctx['region']}-{ctx['subsystem']}"
        if sc["same_change"]:
            pro["plan"].append(f"the cycle change is shared by {_and(sc['same_change'])} in {name}")
        elif sc["same_value"] and not ctx["single_site"]:
            pro["plan"].append(f"it runs the same cycle as {_and(sc['same_value'])} in {name}")
        elif sc["usual"] and cl["status"] == ABNORMAL:
            con["plan"].append(f"{_and(sc['usual'])}, in the same {name}, kept its usual cycle")
        if ctx["single_site"] and cl["status"] == ABNORMAL and cl.get("direction") and \
                any(d == cl["direction"] for d in traffic.values()):
            pro["demand"].append(f"it is the only site of {name}, so its cycle follows its own measurements")
    # subsystem state (subsystem_status: DS, required and active cycle)
    st = (ctx or {}).get("status")
    if st:
        n, u = st["now"], st["usual"]
        if u.get("ds_median") is not None and n["ds_median"] >= u["ds_median"] + 10:
            pro["demand"].append(f"the subsystem degree of saturation was higher than usual (median {n['ds_median']:.0f} "
                                 f"against {u['ds_median']:.0f})")
        elif n["ds_at_least_100"] >= 3:
            share, usual_share = n["ds_at_least_100"] / n["records"], u.get("ds_at_least_100_share")
            text = (f"the subsystem degree of saturation reached 100 or more in {n['ds_at_least_100']} of "
                    f"{n['records']} records")
            if usual_share is None:
                pro["demand"].append(text)
            elif share >= usual_share + 0.15:
                pro["demand"].append(f"{text} (usually {usual_share * 100:.0f}% of records)")
        # a large volume rise with a usual subsystem saturation: the counts and the strategic measurements disagree
        rise = max([a["pct_difference"] or 0 for a in t["abnormal_approaches"] if a["direction"] == "HIGH"] or [0])
        if rise >= 30 and u.get("ds_median") is not None and abs(n["ds_median"] - u["ds_median"]) <= 5:
            why = (f"volume rose by up to {rise:.1f}% while the subsystem degree of saturation stayed at its usual level "
                   f"(median {n['ds_median']:.0f} against {u['ds_median']:.0f})")
            con["demand"].append(why)
            con["event"].append(why)
            pro["data"].append(why + ", so the counts and the strategic measurements disagree")
        follows = n["cl_with_rl"] >= 0.6 * n["records"]
        if (cl["status"] == ABNORMAL or cs["status"] == ABNORMAL) and follows and n["cl_sd"] >= 3:
            why = (f"the active cycle followed the required cycle, which SCATS sets from saturation, between "
                   f"{n['cl_min']:.0f} and {n['cl_max']:.0f} s")
            if u.get("cl_sd") is not None:
                why += f" (spread {n['cl_sd']:.1f} s against a usual {u['cl_sd']:.1f} s)"
            pro["demand"].append(why + (", which accounts for the poorer stability" if cs["status"] == ABNORMAL else ""))
            con["plan"].append(why)
        if n["cl_above_rl"] >= 0.5 * n["records"]:
            pro["plan"].append(f"the active cycle ({n['cl_mean']:.1f} s) stayed at least 3 s above the required cycle "
                               f"(mean {n['rl_mean']:.1f} s) in {n['cl_above_rl']} of {n['records']} records, so it was "
                               "held by a plan, coordination or a configured minimum rather than by saturation")
        cv = [v for v in ((view or {}).get("cycle_cv_pct") or []) if v is not None]
        if cv and max(cv) > 2 and n["cl_sd"] <= 1:
            pro["other_phases"].append(f"the subsystem's active cycle stayed at {n['cl_mean']:.1f} s while the site's "
                                       f"measured cycles varied (cycle variation up to {max(cv):.1f}%), so the variation "
                                       "arose at the site")
            con["plan"].append(f"the subsystem's active cycle did not change ({n['cl_mean']:.1f} s)")
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

    # recurrence at this time (persistence.py): a recurring condition is not a one-off incident
    hist = ev.get("persistence") or {}
    if hist.get("weeks_screened", 0) >= 2:
        k, n = hist["weeks_flagged"], hist["weeks_screened"]
        if k >= 2:
            con["event"].append(f"the site was Red or Amber at this time in {k} of the previous {n} screened weeks, "
                                "so the condition recurs")
            pro["plan"].append(f"the condition recurs at this time ({k} of the previous {n} screened weeks)")
        elif k == 0:
            pro["event"].append(f"the site was not Red or Amber at this time in any of the previous {n} screened weeks")

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

    tolerated = bool(ev.get("tolerated_detectors"))
    out = []
    for key, name in CATALOGUE.items():
        p, c = pro[key], con[key]
        if not p:
            continue
        sc = sum(weight(x) for x in p) - sum(weight(x) for x in c)
        if sc >= 5 and not c and not tolerated:
            strength = "Strong"
        elif sc >= 3 or (sc >= 2 and not c):
            strength = "Moderate"
        else:
            strength = "Weak"
        out.append({"key": key, "name": name, "for": p, "against": c, "strength": strength, "score": sc})
    order = list(CATALOGUE)
    out.sort(key=lambda r: (STRENGTHS.index(r["strength"]), -r["score"], order.index(r["key"])))
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
    if len(table) > 1:
        second = table[1]
        if second["strength"] == top["strength"] and top.get("score", 0) - second.get("score", 0) <= 1:
            main += f". The evidence is close: {second['name']} is about as well supported"
    others = []
    for r in table[1:]:
        # one clause each: the main point against, or the main point for (the full lists are in the evidence)
        why = f"against: {r['against'][0]}" if r["against"] else f"for: {r['for'][0]}"
        others.append(f"{r['name']} ({r['strength'].lower()}; {why})")
    return top["strength"], main + ".", ("; ".join(others) + ".") if others else "no other reading is supported by these data."


def check_for(r: dict, ev: dict, window: str) -> str | None:
    """The first engineering check for a reading: verify it, then what to review if it is confirmed."""
    shifts = ev.get("phase_shifts") or []
    service = [a["approach"] for a in ev["signal"]["phase_service"]["abnormal_approaches"]]
    if r["key"] == "other_phases":
        gains = [x for x in ev.get("phase_shares") or [] if x["change"] is not None and x["change"] >= 3]
        if gains:
            ph = _phases_text(tuple(sorted({p for g in gains for p in g["phases"].split(",")})))
            return (f"In SCATS History for {window}, find why {ph} ran longer or more often at this site (phase "
                    "extensions, pedestrian calls, side-road or turning demand, skipped phases); if it recurs on the same "
                    f"weekday, review the maximum times of {ph}.")
        lows = [] if mixed_splits(ev.get("phase_shares") or []) else [sh for sh in shifts if sh["direction"] == "LOW"]
        if lows:
            rest = _phases_text(tuple(lows[0]["other_phases"].split(",")))
            which = f"which of {rest}" if "phases" in rest else f"whether {rest}"
            return (f"In SCATS History for {window}, find {which} extended or was called more often, and why "
                    "(pedestrian calls, side-road or turning demand, phase skips); if it recurs on the same weekday, "
                    f"review the maximum times of {rest} or the plan selection.")
        losing = [a["approach"] for a in ev["signal"]["phase_service"]["abnormal_approaches"] if a["direction"] == "LOW"]
        return (f"In SCATS History for {window}, find which phases took the green lost by {_and(losing or service)} and why; if "
                "it recurs on the same weekday, review those phases' maximum times or the plan selection.")
    if r["key"] == "demand":
        return (f"Confirm in SCATS History for {window} that the phases serving the busier approaches reached their "
                "maximum in most cycles and how saturated their strategic approaches were; if the higher demand "
                "persists on the same weekday, review whether the plan's maximums and splits fit it.")
    if r["key"] == "plan":
        ctx = ev.get("control")
        name = f"subsystem {ctx['region']}-{ctx['subsystem']}" if ctx else "its subsystem"
        others = [o["site"] for o in (ctx or {}).get("others", [])]
        return (f"Check {name} for {window} against the usual weekday: degree of saturation, required against active "
                "cycle length, active split and link plan, and any marriage or divorce; if it was a subsystem decision, "
                "review it for the whole subsystem" + (f" (with {_and(others)})" if others else "") + ".")
    if r["key"] == "event":
        names = ev["traffic_only_approaches"] or [a["approach"] for a in ev["traffic"]["abnormal_approaches"]]
        view, vol = ev.get("quarter_view"), onset(ev.get("quarter_view"), ev)["volume"]
        when = view["quarters"][vol[names[0]]] if view and names[0] in vol else "the period"
        return (f"Check for incidents, events, roadworks or diversions affecting {_and(names)} during {when}, and "
                "compare the same time next week.")
    return None                                     # data: the mapping and detector checks are written separately
