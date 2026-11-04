"""Example outputs of one screening run, for review (e.g. with the methodology owner).

    python main.py examples [--run ID | --end 2026-11-02T15:30] [--red 2] [--sites 719 994]

One Markdown file with the run's category counts and, per category, a representative site exactly as an
operator would see it: Red - the four-section report (D001 + D002 + link speed); Amber - the saved Q1/Q3
evidence with link speed; Grey - the reasons; Detector Health - the failed detectors; Normal - one line.
Red sites with a TomTom result are preferred, one that agrees and one that does not when both exist.
"""
from __future__ import annotations

from pathlib import Path

from ..report import evidence_tables
from ..screening import CATEGORIES

ORDER = ["red", "amber_traffic", "amber_signal", "grey", "detector_health", "normal"]


def _table(t: dict) -> list[str]:
    from ..report import _tables                     # the same layout as the Red report (abnormal rows in bold)
    return _tables([{**t, "rows": [[str(c) for c in r] for r in t["rows"]]}])


def _speed(link_speed: dict | None) -> list[str]:
    from ..link_speed import table
    if not link_speed:
        return []
    lines = _table(table(link_speed)) if link_speed["approaches"] else []
    return lines + [f"- {n}" for n in link_speed["notes"]] + [f"- Reference speed: {link_speed['reference']}", ""]


def _site_head(s: dict) -> list[str]:
    return [f"### SCATS {s['site']} - {s.get('name') or ''}", "", f"**{s['label']}**", ""]


def _evidence(s: dict) -> list[str]:
    lines = _site_head(s) + [f"- {r}" for r in s.get("reasons", [])] + [f"- &#9888; {n}" for n in s.get("notes", [])] + [""]
    if s.get("q1") and s.get("q3"):
        for t in evidence_tables(s):
            lines += _table(t)
    return lines


def _detector_health(s: dict) -> list[str]:
    q2 = s["q2"]
    failed = [d for d in q2["detectors"] if d["detector"] in set(q2["failed"])]
    rows = [[str(d["detector"]), f"{d['count_60min']:.0f}", f"{d['records']}/{d['expected_records']}"] for d in failed]
    return _site_head(s) + [f"- {q2['reason']}", ""] + _table(
        {"title": f"Detectors below the threshold ({q2['threshold']} vehicles in 60 minutes)",
         "columns": ["Detector", "Count (60 min)", "5-min records"], "rows": rows})


def _pick_red(svc, run_id: str, reds: list[dict], wanted: int, tries: int) -> list[dict]:
    """Up to `wanted` Red diagnoses, preferring ones with a TomTom result: one agreement and one disagreement."""
    done, kept, seen = 0, [], set()
    for s in reds:
        if done >= tries or len(kept) >= wanted:
            break
        r = svc.diagnose(run_id, s["site"], reuse=False)           # always the current code, never a saved report
        done += 1
        d002 = (r.get("templates") or {}).get("D002") or {}
        verdict = d002.get("answer", {}).get("agreement") if d002.get("evidence", {}).get("available") else None
        if verdict and verdict not in seen:
            seen.add(verdict)
            kept.append(r)
    if len(kept) < wanted:                                    # fill up with any Red report
        for s in reds:
            if len(kept) >= wanted:
                break
            if all(k["site"] != s["site"] for k in kept):
                kept.append(svc.diagnose(run_id, s["site"], reuse=False))
    return kept[:wanted]


def build(svc, run_id: str, red: int = 2, sites: list[str] | None = None, tries: int = 12, tomtom_sites=None,
          synthetic: bool = False) -> str:
    run = svc.store.get_run(run_id)
    p = run["payload"]
    by_cat = {c: [s for s in p["sites"] if s["category"] == c] for c in ORDER}
    chosen = {str(x) for x in sites or []}
    pick = lambda c: ([s for s in by_cat[c] if s["site"] in chosen] or by_cat[c])
    lines = ["# Intersections Diagnostics V1 - example outputs", "",
             f"Run `{run_id}` - **{p['period']['local']}** - region {p['region']}", ""]
    if synthetic:
        lines += ["**Synthetic demo network - illustrative only, not measured data.**", ""]
    lines += [
             "| Category | Sites |", "|---|---|"]
    lines += [f"| {CATEGORIES[c]} | {len(by_cat[c])} |" for c in ORDER] + [f"| Total | {len(p['sites'])} |", ""]
    if p.get("notes"):
        lines += [f"- {n}" for n in p["notes"]] + [""]

    lines += [f"- Report wording: {'LLM (' + str(getattr(svc.llm, 'model', '') or 'host client') + '), checked against the evidence' if svc.llm else 'code only (no LLM configured)'}",
              ""]
    lines += ["## Red - Needs Attention (click: Q4 + Q5 report)", ""]
    reds = pick("red")
    if tomtom_sites is not None:                              # sites with a TomTom mapping first
        reds = sorted(reds, key=lambda s: s["site"] not in tomtom_sites)
    for r in _pick_red(svc, run_id, reds, red, tries):
        md = r["report"]["markdown"].replace("\n### ", "\n##### ").replace("\n## ", "\n#### ")   # keep the supplement below its section
        lines += ["### " + md[2:] if md.startswith("# ") else md, ""]
        rejected = [f"{t['template_id']}: {t['rejected']}" for t in (r.get("templates") or {}).values() if t.get("rejected")]
        if rejected:
            lines += [f"- LLM answer not used (code wording shown) - {x}" for x in rejected] + [""]
        lines += ["---", ""]
    if not reds:
        lines += ["No Red site in this period.", ""]

    for c, title in (("amber_traffic", "Amber - Traffic Abnormality (click: evidence + link speed, no Q4/Q5)"),
                     ("amber_signal", "Amber - Signal-Operation Abnormality (click: evidence + link speed, no Q4/Q5)")):
        lines += [f"## {title}", ""]
        if by_cat[c]:
            s = pick(c)[0]
            e = svc.site_evidence(run_id, s["site"])
            lines += _evidence(s) + _speed(e.get("link_speed"))
        else:
            lines += ["No site in this category in this period.", ""]

    lines += ["## Grey - Insufficient Data", ""]
    for s in pick("grey")[:2]:
        lines += _site_head(s) + [f"- {r}" for r in s.get("reasons", [])] + [""]
    lines += ["## Detector Health Issue", ""]
    if by_cat["detector_health"]:
        lines += _detector_health(pick("detector_health")[0])
    lines += ["## Normal", ""]
    if by_cat["normal"]:
        s = pick("normal")[0]
        lines += [f"SCATS {s['site']} - {s.get('name') or ''}: no approach outside its normal range and signal "
                  "operation normal (not shown on the map)."] + [f"- &#9888; {n}" for n in s.get("notes", [])] + [""]
    return "\n".join(lines)


def save(text: str, run_id: str, out_dir) -> Path:
    path = Path(out_dir) / f"examples_{run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def to_html(text: str, title: str = "Intersections Diagnostics V1 - example outputs") -> str:
    """The Markdown above as a plain, printable HTML page (headings, paragraphs, lists, tables, bold, rules)."""
    import html
    import re

    def inline(s: str) -> str:
        s = html.escape(s, quote=False).replace("&amp;#9888;", "&#9888;")
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        return re.sub(r"(?<![\w*])_(.+?)_(?!\w)", r"<i>\1</i>", s)

    out, rows, items, numbered = [], [], [], []

    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if numbered:
            out.append("<ol>" + "".join(f"<li>{inline(i)}</li>" for i in numbered) + "</ol>")
            numbered.clear()
        if rows:
            head, body = rows[0], [r for r in rows[2:]]
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>")
            rows.clear()

    for line in text.splitlines():
        if line.startswith("|"):
            if items:
                flush()
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        if line.startswith("- "):
            if rows or numbered:
                flush()
            items.append(line[2:])
            continue
        if re.match(r"\d+\. ", line):
            if rows or items:
                flush()
            numbered.append(line.split(". ", 1)[1])
            continue
        flush()
        if not line.strip():
            continue
        if line.strip() == "---":
            out.append("<hr>")
        elif line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 5)
            out.append(f"<h{level}>{inline(line.lstrip('#').strip())}</h{level}>")
        else:
            out.append(f"<p>{inline(line)}</p>")
    flush()
    body = "\n".join(out)
    # detail tables folded away (movements): the title and its table inside <details>
    body = re.sub(r"<p><b>(TomTom movements[^<]*)</b></p>\n(<table>.*?</table>)",
                  r"<details><summary><b>\1</b> (click to show)</summary>\2</details>", body, flags=re.S)
    style = ("body{font:14px/1.45 system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1d2433}"
             "h1{font-size:22px}h2{font-size:18px;margin-top:32px;border-bottom:1px solid #ccd}h3{font-size:16px}h4{font-size:15px}h5{font-size:14px;color:#556}"
             "table{border-collapse:collapse;margin:6px 0 14px}th,td{border:1px solid #ccd;padding:3px 8px;text-align:left}"
             "th{background:#f1f3f8}td b{color:#a3261a}summary{cursor:pointer;margin:6px 0}code{background:#f1f3f8;padding:0 3px}hr{border:0;border-top:2px solid #ccd;margin:28px 0}")
    return (f"<!doctype html><html lang=en><meta charset=utf-8><title>{title}</title><style>{style}</style><body>"
            + body + "</body></html>")


def save_html(text: str, run_id: str, out_dir) -> Path:
    path = Path(out_dir) / f"examples_{run_id}.html"
    path.write_text(to_html(text), encoding="utf-8")
    return path
