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

COLUMNS = ["rank", "category", "site", "name", "score", "severity", "impact", "volume_veh_h", "type_factor",
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
    out = ["| # | Site | Intersection | Score | Severity | Impact | veh/h | Factors | Reasons |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        factors = f"type {r['type_factor']:g}, conf {r['confidence']:g}, pers {r['persistence_factor']:g}"
        out.append(f"| {r.get('rank', '')} | {r['site']} | {r['name'] or ''} | {r['score']:.2f} | {r['severity']:.2f} | "
                   f"{r['impact']:.2f} | {'' if r['volume_veh_h'] is None else round(r['volume_veh_h'])} | {factors} | "
                   f"{'; '.join(r['reasons'] + r['mapping_suspect'])} |")
    return out


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


def run(svc, periods: list[tuple[str, str]], out_dir, top: int = 20, persistence: bool = True,
        rescreen: bool = False, progress=print) -> Path:
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
                 *_table(ranked["mapping_suspect"]), ""]
        (folder / "ranked.md").write_text("\n".join(page), encoding="utf-8")
        (folder / "ranked.html").write_text(examples.to_html("\n".join(page), f"{label} - ranked sites"), encoding="utf-8")
    summary += ["", "## Checks of the ranking", "", *sections]
    (batch / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    (batch / "summary.html").write_text(examples.to_html("\n".join(summary), "Ranking - summary"), encoding="utf-8")
    return batch
