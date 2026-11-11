"""Every Red and Amber report of several periods, saved for a full review (read only for the data).

    python main.py audit-reports --end "AM peak=2026-11-10T08:30" "Midday=2026-11-10T12:30" \
        "PM peak=2026-11-10T17:30" "Weekend midday=2026-11-08T12:30" [--no-llm] [--no-amber-speed] [--resume]

For each period: the screening (reused when already stored), then every Red report (D001 + D002 + link speed,
as on a click) and every Amber evidence page (Q1/Q3 tables + link speed). Written to out/report_audit/<batch>/:

    index.csv              one row per Red/Amber site and period: findings, Q5 result, automatic review flags
    details.jsonl          the same sites in full (every approach, measure, TomTom value, link speed, D001 pattern
                           and checks), for the statistical review
    summary.md             counts per period and category, Q5 verdicts, flag counts, LLM use
    <period>/red.md|html   every Red report of the period
    <period>/amber.md|html every Amber evidence page of the period

The flags only point at what deserves a look; they change nothing in the screening.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..screening import CATEGORIES
from . import examples

RED, AMBERS = "red", ("amber_traffic", "amber_signal")
COLUMNS = ["period", "period_local", "run_id", "site", "name", "category",
           "q1_flagged", "q1_not_assessed", "cycle_length", "cycle_stability", "q3c_flagged", "q3c_not_assessed",
           "q5_available", "q5_verdict", "q5_per_approach", "q5_reason", "queue_status",
           "speed_links", "speed_without_reference", "wording", "llm_rejected", "flags", "notes"]


def parse_periods(values: list[str]) -> list[tuple[str, str]]:
    """["AM peak=2026-11-10T08:30", "2026-11-08T12:30"] -> [(label, end)]."""
    out = []
    for v in values:
        label, _, end = v.rpartition("=")
        out.append((label.strip() or end.strip(), end.strip()))
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or "period"


def _v(x) -> str:
    return "-" if x is None else f"{x:.1f}"


def _pct(x) -> str:
    return "" if x is None else f"{x:+.1f}%"


def _approaches(rows: list[dict], status: str, pp: bool = False) -> str:
    from ..names import approach_label
    out = []
    for a in rows:
        if a["status"] != status:
            continue
        if pp and a.get("current") is not None and a.get("usual") is not None:
            diff = f"{round(a['current'], 1) - round(a['usual'], 1):+.1f} pp"
        else:
            diff = _pct(a.get("pct_difference"))
        out.append(f"{approach_label(a)} {a.get('direction') or ''} {_v(a.get('current'))} vs {_v(a.get('usual'))} "
                   f"({diff}, {a.get('n_history')} wk)".replace("  ", " "))
    return "; ".join(out)


def _measure(c: dict) -> str:
    if c["status"] == "INSUFFICIENT DATA":
        return "not assessed"
    return f"{c['status'].lower()} {_v(c.get('current'))} vs {_v(c.get('usual'))} ({_pct(c.get('pct_difference'))}, {c.get('n_history')} wk)"


def flags(s: dict, d002: dict | None, speed: dict | None) -> list[str]:
    """What deserves a look in the review (not a judgement)."""
    out = []
    q1, comps = s.get("q1") or {}, (s.get("q3") or {}).get("components") or {}
    flagged_q1 = [a for a in q1.get("approaches", []) if a["status"] == "ABNORMAL"]
    if any((a.get("usual") or 0) < 20 for a in flagged_q1):
        out.append("q1_low_volume_usual_lt_20")                   # usual below 20 veh/30 min (no spaces: one token)
    if any(a.get("usual") == 0 for a in flagged_q1):
        out.append("q1_usual_zero")
    if any(abs(a.get("pct_difference") or 0) >= 50 for a in flagged_q1):
        out.append("q1_change>=50%")
    if q1.get("not_evaluated"):
        out.append("q1_approach_not_assessed")
    ps = (comps.get("phase_service") or {}).get("approaches", [])
    flagged_ps = [a for a in ps if a["status"] == "ABNORMAL"]
    if any((a.get("usual") or 0) >= 99.5 for a in flagged_ps):
        out.append("q3c_usual_100%")
    if any(a.get("usual") == 0 for a in flagged_ps):
        out.append("q3c_usual_zero")
    if any(a.get("current") is not None and a.get("usual") is not None and abs(a["current"] - a["usual"]) >= 30
           for a in flagged_ps):
        out.append("q3c_change>=30pp")
    cl = comps.get("cycle_length") or {}
    if cl.get("status") == "ABNORMAL" and abs(cl.get("pct_difference") or 0) >= 50:
        out.append("cycle_change>=50%")
    values = flagged_q1 + flagged_ps + [c for c in (cl, comps.get("cycle_stability") or {}) if c.get("status") == "ABNORMAL"]
    if any(v.get("n_history") == 5 for v in values):
        out.append("flagged_on_minimum_5_weeks")
    if (s.get("q2") or {}).get("tolerated"):
        out.append("one_detector_tolerated")
    if d002 is not None:
        ev = d002.get("evidence") or {}
        if not ev.get("available"):
            out.append("q5_unavailable")
        elif (ev.get("comparison") or {}).get("agreement") in ("disagreement", "insufficient coverage"):
            out.append("q5_" + ev["comparison"]["agreement"].replace(" ", "_"))
    if speed and speed.get("approaches"):
        if all(a.get("reference_kmh") is None for a in speed["approaches"] if a.get("speed_kmh") is not None):
            out.append("speed_no_reference")
    return out


def _row(label: str, p: dict, run_id: str, s: dict, d002: dict | None, speed: dict | None, templates: dict) -> dict:
    q1, comps = s.get("q1") or {}, (s.get("q3") or {}).get("components") or {}
    ps = (comps.get("phase_service") or {}).get("approaches", [])
    ev = (d002 or {}).get("evidence") or {}
    comp = ev.get("comparison") or {}
    return {
        "period": label, "period_local": p["period"]["local"], "run_id": run_id, "site": s["site"],
        "name": s.get("name") or "", "category": CATEGORIES.get(s["category"], s["category"]),
        "q1_flagged": _approaches(q1.get("approaches", []), "ABNORMAL"),
        "q1_not_assessed": len(q1.get("not_evaluated", [])) + sum(a["status"] == "INSUFFICIENT DATA" for a in q1.get("approaches", [])),
        "cycle_length": _measure(comps["cycle_length"]) if comps else "",
        "cycle_stability": _measure(comps["cycle_stability"]) if comps else "",
        "q3c_flagged": _approaches(ps, "ABNORMAL", pp=True),
        "q3c_not_assessed": sum(a["status"] == "INSUFFICIENT DATA" for a in ps),
        "q5_available": "" if d002 is None else ev.get("available"),
        "q5_verdict": comp.get("agreement", "" if d002 is None else "unavailable"),
        "q5_per_approach": "; ".join(f"{x['approach']}: {x['agreement']}" for x in comp.get("per_approach", [])),
        "q5_reason": "" if d002 is None or ev.get("available") else ev.get("coverage_note", ""),
        "queue_status": ev.get("queue", ""),
        "speed_links": "" if not speed else sum(a.get("speed_kmh") is not None for a in speed.get("approaches", [])),
        "speed_without_reference": "" if not speed else sum(a.get("speed_kmh") is not None and a.get("reference_kmh") is None
                                                            for a in speed.get("approaches", [])),
        "wording": ", ".join(f"{k}: {v.get('generated_by')}" for k, v in templates.items()),
        "llm_rejected": "; ".join(f"{k}: {v['rejected']}" for k, v in templates.items() if v.get("rejected")),
        "flags": " ".join(flags(s, d002, speed)),
        "notes": " | ".join(s.get("notes", [])),
    }


def _round(x, n=1):
    return None if x is None else round(x, n)


def _rows(rows: list[dict]) -> list[dict]:
    from ..names import approach_label
    keep = ("link", "status", "direction", "current", "usual", "p_low", "p_high", "n_history", "pct_difference")
    return [{"approach": approach_label(a), **{k: (_round(a.get(k), 2) if isinstance(a.get(k), float) else a.get(k))
                                              for k in keep}} for a in rows]


def _measure_row(c: dict | None) -> dict | None:
    if not c:
        return None
    return {k: (_round(c.get(k), 2) if isinstance(c.get(k), float) else c.get(k))
            for k in ("status", "direction", "current", "usual", "p_low", "p_high", "n_history", "pct_difference")}


def detail(label: str, p: dict, run_id: str, s: dict, r: dict | None, speed: dict | None) -> dict:
    """One site in full, for the statistical review (details.jsonl): every approach, measure, TomTom value and
    link speed, and for Red the D001 pattern and the code's checks (the deterministic ones, whatever the wording)."""
    from ..templates import d001
    q1, comps = s.get("q1") or {}, (s.get("q3") or {}).get("components") or {}
    out = {"period": label, "period_local": p["period"]["local"], "run_id": run_id, "site": s["site"],
           "name": s.get("name") or "", "category": s["category"],
           "q2": {"tolerated": (s.get("q2") or {}).get("tolerated", []),
                  "detectors": len((s.get("q2") or {}).get("detectors", []))},
           "q1": {"status": q1.get("status"), "approaches": _rows(q1.get("approaches", [])),
                  "not_evaluated": [a["link"] for a in q1.get("not_evaluated", [])]},
           "q3": {"status": (s.get("q3") or {}).get("status"),
                  "cycle_length": _measure_row(comps.get("cycle_length")),
                  "cycle_stability": _measure_row(comps.get("cycle_stability")),
                  "phase_service": _rows((comps.get("phase_service") or {}).get("approaches", []))},
           "notes": s.get("notes", [])}
    if speed:
        out["link_speed"] = [{"approach": a["approach"], "speed_kmh": a.get("speed_kmh"), "reference_kmh": a.get("reference_kmh"),
                              "minutes": a.get("minutes"), "reference_weeks": a.get("reference_weeks")}
                             for a in speed.get("approaches", [])]
    if r:
        t = r.get("templates") or {}
        one, two = t.get("D001") or {}, t.get("D002") or {}
        ev1 = one.get("evidence") or {}
        out["d001"] = {"same_approach": ev1.get("same_approach", []), "traffic_only": ev1.get("traffic_only_approaches", []),
                       "signal_only": ev1.get("signal_only_approaches", []),
                       "code_checks": d001.written(ev1)["suggested_checks"] if ev1 else [],
                       "code_diagnosis": d001.written(ev1)["diagnosis"] if ev1 else "",
                       "answer": {k: (one.get("answer") or {}).get(k) for k in ("diagnosis", "suggested_checks")},
                       "generated_by": one.get("generated_by"), "rejected": one.get("rejected")}
        ev2 = two.get("evidence") or {}
        comp = ev2.get("comparison") or {}
        out["d002"] = {"available": ev2.get("available"), "queue": ev2.get("queue"),
                       "agreement": comp.get("agreement"), "coverage_note": ev2.get("coverage_note"),
                       "per_approach": [{k: x.get(k) for k in ("approach", "scats_findings", "agreement", "has_largest_delay",
                                                               "has_largest_queue", "observed")}
                                        for x in comp.get("per_approach", [])],
                       "approaches": [{k: a.get(k) for k in ("approach", "link", "mapped", "adequate", "quarters_observed",
                                                             "control_delay_s", "approach_delay_s", "multi_stop_rate",
                                                             "queue_mean_m", "queue_max_m", "queue_minutes", "queue_adequate")}
                                      for a in ev2.get("approaches", [])],
                       "answer": (two.get("answer") or {}).get("road_user_impact"),
                       "code_answer": _d002_code(ev2),
                       "generated_by": two.get("generated_by"), "rejected": two.get("rejected")}
    return out


def _d002_code(ev: dict) -> str | None:
    """The code's D002 answer for the same evidence (the deterministic draft), to set beside the LLM wording."""
    from ..templates import d002
    try:
        return d002.written(ev)["road_user_impact"] if ev else None
    except Exception:  # noqa: BLE001 - review aid only
        return None


def _llm_failed(r: dict) -> bool:
    return any("LLM call failed" in str(t.get("rejected") or "") for t in (r.get("templates") or {}).values())


def run(svc, periods: list[tuple[str, str]], out_dir, amber_speed: bool = True, resume: bool = False,
        progress=print, rescreen: bool = False) -> Path:
    batch = Path(out_dir) / "report_audit" / datetime.now().strftime("%Y%m%d_%H%M")
    batch.mkdir(parents=True, exist_ok=True)
    index = batch / "index.csv"
    rows, counts, verdicts = [], {}, Counter()
    details = (batch / "details.jsonl").open("w", encoding="utf-8")
    with index.open("w", newline="", encoding="utf-8-sig") as fh:            # utf-8-sig: opens cleanly in Excel
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for label, end in periods:
            view = svc.screen(end, force=rescreen)
            run_id = view["run_id"]
            p = svc.store.get_run(run_id)["payload"]
            folder = batch / _slug(label)
            folder.mkdir(exist_ok=True)
            by_cat = Counter(s["category"] for s in p["sites"])
            counts[label] = (p["period"]["local"], run_id, by_cat)
            progress(f"{label}: {p['period']['local']} run {run_id} - Red {by_cat[RED]}, "
                     f"Amber {by_cat['amber_traffic'] + by_cat['amber_signal']}")

            red = [f"# {label} - Red reports", "", f"Run `{run_id}` - **{p['period']['local']}**", ""]
            reds = [s for s in p["sites"] if s["category"] == RED]
            for k, s in enumerate(reds, 1):
                try:
                    r = svc.diagnose(run_id, s["site"], reuse=resume)
                    if resume and svc.llm and _llm_failed(r):        # a saved report whose LLM call failed: redo it
                        r = svc.diagnose(run_id, s["site"], reuse=False)
                except Exception as exc:  # noqa: BLE001 - one site never stops the batch
                    red += [f"## SCATS {s['site']} - report failed: {type(exc).__name__}: {exc}", "", "---", ""]
                    continue
                md = r["report"]["markdown"].replace("\n### ", "\n#### ").replace("\n## ", "\n### ")
                red += ["## " + md[2:] if md.startswith("# ") else md, ""]
                rejected = [f"{t['template_id']}: {t['rejected']}" for t in (r.get("templates") or {}).values() if t.get("rejected")]
                red += [f"- LLM answer not used (code wording shown) - {x}" for x in rejected] + ["", "---", ""]
                d002 = (r.get("templates") or {}).get("D002")
                row = _row(label, p, run_id, s, d002, r.get("link_speed"), r.get("templates") or {})
                details.write(json.dumps(detail(label, p, run_id, s, r, r.get("link_speed")), default=str) + "\n")
                writer.writerow(row)
                rows.append(row)
                verdicts[(label, row["q5_verdict"])] += 1
                if k % 10 == 0:
                    progress(f"  Red {k}/{len(reds)}")
                    fh.flush()
            (folder / "red.md").write_text("\n".join(red), encoding="utf-8")
            (folder / "red.html").write_text(examples.to_html("\n".join(red), f"{label} - Red reports"), encoding="utf-8")

            amber = [f"# {label} - Amber evidence", "", f"Run `{run_id}` - **{p['period']['local']}**", ""]
            ambers = [s for s in p["sites"] if s["category"] in AMBERS]
            for k, s in enumerate(ambers, 1):
                speed = None
                if amber_speed:
                    try:
                        speed = svc.site_evidence(run_id, s["site"]).get("link_speed")
                    except Exception as exc:  # noqa: BLE001
                        amber += [f"- SCATS {s['site']}: link speed failed ({type(exc).__name__})"]
                amber += examples._evidence(s) + examples._speed(speed) + ["---", ""]
                row = _row(label, p, run_id, s, None, speed, {})
                details.write(json.dumps(detail(label, p, run_id, s, None, speed), default=str) + "\n")
                writer.writerow(row)
                rows.append(row)
                if k % 50 == 0:
                    progress(f"  Amber {k}/{len(ambers)}")
                    fh.flush()
            for s in p["sites"]:                               # every other site, for network-wide distributions
                if s["category"] != RED and s["category"] not in AMBERS:
                    details.write(json.dumps(detail(label, p, run_id, s, None, None), default=str) + "\n")
            (folder / "amber.md").write_text("\n".join(amber), encoding="utf-8")
            (folder / "amber.html").write_text(examples.to_html("\n".join(amber), f"{label} - Amber evidence"), encoding="utf-8")
    details.close()
    (batch / "summary.md").write_text(summary(counts, rows, verdicts, svc), encoding="utf-8")
    return batch


def summary(counts: dict, rows: list[dict], verdicts: Counter, svc) -> str:
    order = ["red", "amber_traffic", "amber_signal", "grey", "detector_health", "normal"]
    lines = ["# Report audit - summary", "",
             f"Wording: {'LLM (' + str(getattr(svc.llm, 'model', '') or 'host client') + '), code where rejected' if svc.llm else 'code only'}", "",
             "| Period | Local time | Run | " + " | ".join(CATEGORIES[c] for c in order) + " |",
             "|---" * (3 + len(order)) + "|"]
    for label, (local, run_id, c) in counts.items():
        lines.append(f"| {label} | {local} | `{run_id}` | " + " | ".join(str(c[x]) for x in order) + " |")
    lines += ["", "## Q5 (Red) verdicts", "", "| Period | Verdict | Sites |", "|---|---|---|"]
    lines += [f"| {lab} | {v} | {n} |" for (lab, v), n in sorted(verdicts.items())]
    lines += ["", "## Review flags (Red + Amber)", "", "| Period | Category | Flag | Sites |", "|---|---|---|---|"]
    tally = Counter((r["period"], r["category"], f) for r in rows for f in r["flags"].split())
    lines += [f"| {p} | {c} | {f} | {n} |" for (p, c, f), n in sorted(tally.items())]
    rejected = sum(bool(r["llm_rejected"]) for r in rows)
    lines += ["", f"LLM answers not used (code wording shown instead): {rejected}", "",
              "Flags point at what deserves a look; they change nothing in the screening. index.csv has one row per site."]
    return "\n".join(lines) + "\n"
