"""`python main.py compare-runs --run BASE OTHER`: how the categories of the same period change between two runs,
e.g. the default methodology against a sensitivity run with the switches on (`--switches all`)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

ORDER = ["red", "amber_traffic", "amber_signal", "normal", "grey", "detector_health"]


def compare(base: dict, other: dict) -> dict:
    a = {s["site"]: s for s in base["sites"]}
    b = {s["site"]: s for s in other["sites"]}
    moves = Counter((a[k]["category"], b[k]["category"]) for k in a.keys() & b.keys())
    changed = sorted(((k, a[k]["category"], b[k]["category"], a[k].get("name") or "") for k in a.keys() & b.keys()
                      if a[k]["category"] != b[k]["category"]), key=lambda x: (ORDER.index(x[1]), ORDER.index(x[2]), x[0]))
    weeks = lambda p: (len(p["baseline"].get("reference_periods", [])), p["baseline"].get("skipped_days", {}))
    return {"base": base["run_id"], "other": other["run_id"], "period": base["period"]["local"],
            "counts": {"base": Counter(s["category"] for s in base["sites"]),
                       "other": Counter(s["category"] for s in other["sites"])},
            "moves": moves, "changed": changed, "weeks": {"base": weeks(base), "other": weeks(other)},
            "rules": {"base": base.get("rules_version"), "other": other.get("rules_version")}}


def text(c: dict) -> str:
    lines = [f"# Run comparison - {c['period']}", "",
             f"Base `{c['base']}` (rules {c['rules']['base']}) against other `{c['other']}` (rules {c['rules']['other']}).", "",
             f"Reference periods: base {c['weeks']['base'][0]} (skipped {c['weeks']['base'][1]}); "
             f"other {c['weeks']['other'][0]} (skipped {c['weeks']['other'][1]}).", "",
             "| Category | Base | Other | Change |", "|---|---|---|---|"]
    for k in ORDER:
        x, y = c["counts"]["base"][k], c["counts"]["other"][k]
        lines.append(f"| {k} | {x} | {y} | {y - x:+d} |")
    lines += ["", "## Moves (base -> other)", "", "| From \\\\ To | " + " | ".join(ORDER) + " |", "|---" * (len(ORDER) + 1) + "|"]
    for f in ORDER:
        lines.append(f"| {f} | " + " | ".join(str(c["moves"][(f, t)]) if c["moves"][(f, t)] else "" for t in ORDER) + " |")
    lines += ["", f"## Sites that change ({len(c['changed'])})", "", "| Site | Intersection | Base | Other |", "|---|---|---|---|"]
    lines += [f"| {k} | {n} | {x} | {y} |" for k, x, y, n in c["changed"]]
    return "\n".join(lines) + "\n"


def write(svc, base_run: str, other_run: str, out_dir) -> Path:
    base, other = svc.store.get_run(base_run)["payload"], svc.store.get_run(other_run)["payload"]
    if base["period"]["key"] != other["period"]["key"]:
        raise ValueError("The two runs are not of the same period.")
    path = Path(out_dir) / f"compare_{base_run}_{other_run}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text(compare(base, other)), encoding="utf-8")
    return path
