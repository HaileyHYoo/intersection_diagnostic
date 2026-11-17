"""`python main.py rank`: screening only (no LLM, no reports) and the ranking of Red and Amber sites, for review.

For each period the network is screened (a stored run is reused), and so are the same weekday and slot in the
previous `rank.persistence_weeks` weeks for the persistence factor. Output under out/rank/<timestamp>/:

    summary.md / summary.html   categories per period, the ranking rule and checks of the ranking
    <period>/ranked.csv         every ranked site with its score, components and reasons
    <period>/ranked.md|html     the top sites per category and the mapping-suspect list
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .. import rank as rank_mod
from ..screening import CATEGORIES
from ..timewin import period_ending
from . import examples
from .report_audit import _slug

COLUMNS = ["rank", "category", "site", "name", "subsystem", "subsystem_sites", "score", "severity", "impact", "volume_veh_h", "type_factor",
           "confidence", "persistence", "persistence_factor", "findings", "min_history", "tolerated_detector",
           "opposite_direction", "mapping_suspect", "reasons"]
TITLES = {"red": "Red", "amber_traffic": "Amber - traffic", "amber_signal": "Amber - signal"}


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    a, b = ranks(xs), ranks(ys)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return None if not den else num / den


def checks(rows: list[dict], sites: dict[str, dict], top: int) -> list[str]:
    """Is the order driven by what it should be? Component correlations and the make-up of the top of the list."""
    if not rows:
        return ["(no site)"]
    t = rows[:top]
    sc = [r["score"] for r in rows]
    corr = lambda key: _spearman(sc, [r[key] or 0 for r in rows])
    fmt = lambda x: "n/a" if x is None else f"{x:.2f}"
    # a naive order for comparison: the largest percentage difference of any flagged volume
    def naive(r):
        q1 = (sites[r["site"]].get("q1") or {}).get("approaches") or []
        return max([abs(a["pct_difference"] or 0) for a in q1 if a["status"] == "ABNORMAL"] or [0])
    naive_top = {r["site"] for r in sorted(rows, key=lambda r: -naive(r))[:top]}
    share = lambda f: f"{sum(1 for r in t if f(r))} of {len(t)} (all: {sum(1 for r in rows if f(r))} of {len(rows)})"
    return [f"- Rank correlation of the score with severity {fmt(corr('severity'))}, impact {fmt(corr('impact'))}, "
            f"persistence {fmt(corr('persistence_factor'))}, confidence {fmt(corr('confidence'))}",
            f"- Top {len(t)}: under 200 veh/h {share(lambda r: (r['volume_veh_h'] or 0) < 200)}",
            f"- Top {len(t)}: phase service opposite to volume {share(lambda r: r['opposite_direction'])}",
            f"- Top {len(t)}: same category in at least one previous week {share(lambda r: (r['persistence'] or 0) > 0)}",
            f"- Top {len(t)}: history at the minimum {share(lambda r: (r['min_history'] or 99) <= 5)}",
            f"- Top {len(t)}: one detector tolerated {share(lambda r: r['tolerated_detector'])}",
            f"- Overlap with a naive order by the largest volume difference (%): {len(naive_top & {r['site'] for r in t})} of {len(t)}"]


def _table(rows: list[dict]) -> list[str]:
    out = ["| # | Site | Intersection | Subsystem | Score | Severity | Impact | veh/h | Factors | Reasons |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        factors = f"type {r['type_factor']:g}, conf {r['confidence']:g}, pers {r['persistence_factor']:g}"
        sub = f"{r['subsystem']} ({r['subsystem_sites']} sites)" if r.get("subsystem") else "-"
        out.append(f"| {r.get('rank', '')} | {r['site']} | {r['name'] or ''} | {sub} | {r['score']:.2f} | {r['severity']:.2f} | "
                   f"{r['impact']:.2f} | {'' if r['volume_veh_h'] is None else round(r['volume_veh_h'])} | {factors} | "
                   f"{'; '.join(r['reasons'] + r['mapping_suspect'])} |")
    return out


def subsystem_groups(ranked: dict, payload: dict) -> list[str]:
    """Subsystems with two or more Red or Amber sites in the period: SCATS sets the cycle and plan per subsystem, so
    these are read together (one subsystem decision can show at several sites)."""
    from ..subsystems import membership
    cats = {s["site"]: s["category"] for s in payload["sites"]}
    groups = {}
    for c, rows in ranked.items():
        for r in rows:
            if r.get("subsystem"):
                groups.setdefault(r["subsystem"], []).append(r)
    lines = ["| Subsystem | Sites in subsystem | Red / Amber sites (rank in its category) | Other sites |", "|---|---|---|---|"]
    n = 0
    for key, rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(rows) < 2:
            continue
        n += 1
        members = membership(rows[0]["site"])["members"]
        flagged = {r["site"] for r in rows}
        shown = "; ".join(f"{r['site']} {r['name'] or ''} ({TITLES.get(r['category'], r['category'])}"
                          + (f" #{r['rank']}" if r.get("rank") else ", mapping-suspect") + ")" for r in rows)
        others = ", ".join(f"{m} ({cats.get(m, 'not screened')})" for m in members if m not in flagged) or "-"
        lines.append(f"| {key} | {len(members)} | {shown} | {others} |")
    return lines if n else ["(no subsystem has two or more Red or Amber sites)"]


def previous_runs(svc, end: str, weeks: int, rescreen: bool, progress) -> list[dict | None]:
    period = period_ending(end, svc.settings.rules)
    out = []
    for k in range(1, weeks + 1):
        e = period.end - timedelta(days=7 * k)
        try:
            view = svc.screen(e, force=rescreen)
            payload = svc.store.get_run(view["run_id"])["payload"]
            out.append({s["site"]: s["category"] for s in payload["sites"]})
        except Exception as exc:  # noqa: BLE001 - a missing week only removes that week from persistence
            progress(f"  persistence week -{k}: not available ({exc})")
            out.append(None)
    return out


def reports(svc, run_id: str, rows: list[dict], folder: Path, progress=print) -> list[str]:
    """The SiteReport (contract) of each site, saved under <period>/reports/, for review of the top of the rank."""
    from . import contract_view
    out_dir = folder / "reports"
    lines = []
    for r in rows:
        try:
            report = contract_view.site_report(svc, run_id, r["site"])
            wording = contract_view.wording(svc, report)
            contract_view.save(report, run_id, out_dir, wording)
            w = (wording.get("D001") or {})
            lines.append(f"| {r['rank']} | {r['site']} | {r['name'] or ''} | {w.get('generated_by')} | "
                         f"{(w.get('rejected') or '')[:80]} |")
            progress(f"  report #{r['rank']} SCATS {r['site']}: D001 written by {w.get('generated_by')}")
        except Exception as exc:  # noqa: BLE001 - one report must not stop the others
            lines.append(f"| {r['rank']} | {r['site']} | {r['name'] or ''} | failed | {type(exc).__name__}: {exc} |")
    return lines


def run(svc, periods: list[tuple[str, str]], out_dir, top: int = 20, persistence: bool = True,
        rescreen: bool = False, progress=print, report_top: int = 0) -> Path:
    rules = svc.settings.rules
    weeks = rules["rank"]["persistence_weeks"] if persistence else 0
    batch = Path(out_dir) / "rank" / datetime.now().strftime("%Y%m%d_%H%M")
    batch.mkdir(parents=True, exist_ok=True)
    summary = ["# Ranking of Red and Amber sites - screening only", "",
               f"Rules `{svc.settings.rules_version}`, baseline `{svc.settings.baseline_version}`. No LLM, no reports. "
               "The rank orders sites within a category and never changes a category.", "",
               "## Rule", "", *[f"    {line}" for line in (rank_mod.__doc__ or "").strip().splitlines()], "",
               "## Categories", "", "| Period | Run | Red | Amber - traffic | Amber - signal | Normal | Grey | "
               "Detector Health | Mapping-suspect (set apart) | Persistence weeks found |",
               "|---|---|---|---|---|---|---|---|---|---|"]
    sections = []
    for label, end in periods:
        view = svc.screen(end, force=rescreen)
        payload = svc.store.get_run(view["run_id"])["payload"]
        sites = {s["site"]: s for s in payload["sites"]}
        prev = previous_runs(svc, end, weeks, rescreen, progress) if weeks else []
        ranked = rank_mod.rank(payload["sites"], rules, prev)
        n = Counter(s["category"] for s in payload["sites"])
        found = sum(p is not None for p in prev)
        summary.append(f"| {label} ({payload['period']['local']}) | `{view['run_id']}` | {n['red']} | {n['amber_traffic']} | "
                       f"{n['amber_signal']} | {n['normal']} | {n['grey']} | {n['detector_health']} | "
                       f"{len(ranked['mapping_suspect'])} | {found} of {weeks} |")
        progress(f"{label}: {payload['period']['local']} - Red {n['red']}, Amber {n['amber_traffic'] + n['amber_signal']}, "
                 f"persistence weeks {found}/{weeks}")

        folder = batch / _slug(label)
        folder.mkdir(exist_ok=True)
        with (folder / "ranked.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for c in (*rank_mod.RANKED, "mapping_suspect"):
                for r in ranked[c]:
                    w.writerow({**r, "category": c if c == "mapping_suspect" else r["category"],
                                "opposite_direction": "; ".join(r["opposite_direction"]),
                                "mapping_suspect": "; ".join(r["mapping_suspect"]), "reasons": "; ".join(r["reasons"])})
        page = [f"# {label} - ranked sites", "", f"Run `{view['run_id']}` - **{payload['period']['local']}**; "
                f"persistence from {found} of {weeks} previous weeks.", ""]
        sections.append(f"## {label} ({payload['period']['local']})")
        sections.append("")
        for c in rank_mod.RANKED:
            page += [f"## {TITLES[c]} - top {min(top, len(ranked[c]))} of {len(ranked[c])}", "", *_table(ranked[c][:top]), ""]
            sections += [f"**{TITLES[c]}** ({len(ranked[c])} ranked)", "", *checks(ranked[c], sites, top), ""]
            if ranked[c]:
                progress(f"  {TITLES[c]} top 5: " + ", ".join(f"{r['site']} ({r['score']:.1f})" for r in ranked[c][:5]))
        page += [f"## Mapping-suspect (not ranked) - {len(ranked['mapping_suspect'])}", "",
                 *_table(ranked["mapping_suspect"]), "",
                 "## Subsystems with two or more Red or Amber sites", "",
                 "SCATS sets the cycle length and plan per subsystem: these sites are best read together.", "",
                 *subsystem_groups(ranked, payload), ""]
        if report_top:
            page += [f"## Reports of the top {report_top} Red sites (reports/)", "",
                     "| # | Site | Intersection | D001 written by | LLM answer rejected |", "|---|---|---|---|---|",
                     *reports(svc, view["run_id"], ranked["red"][:report_top], folder, progress), ""]
        (folder / "ranked.md").write_text("\n".join(page), encoding="utf-8")
        (folder / "ranked.html").write_text(examples.to_html("\n".join(page), f"{label} - ranked sites"), encoding="utf-8")
    summary += ["", "## Checks of the ranking", "", *sections]
    (batch / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    (batch / "summary.html").write_text(examples.to_html("\n".join(summary), "Ranking - summary"), encoding="utf-8")
    return batch
