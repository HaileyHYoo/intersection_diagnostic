"""Local command line for Intersections Diagnostics V1.

    python main.py demo [--serve]                    synthetic network: screen, check, export map
    python main.py inspect --site 4397 [--end ...]   check the live feeds for one site
    python main.py screen [--end 2026-10-27T08:30]   screen the network (latest completed period by default)
    python main.py diagnose --run ID --site 4397     D001 + D002 report for a Red site
    python main.py map [--fake]                      local map viewer (http://127.0.0.1:8765)
    python main.py export-html --run ID --out out/map.html
    python main.py baseline [--start 2026-10-30] [--days 7]   weekly baseline job

Times without an offset are Melbourne local time. Connections come from .env (see .env.example).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env(path: str | None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(path) if path else ROOT / ".env")


def make_llm(args):
    if getattr(args, "no_llm", False):
        return None
    from diagnostics.llm import LLMUnavailable, OpenAIChat
    from diagnostics.settings import connection_env
    env = connection_env()
    try:
        return OpenAIChat(env["openai_api_key"], env["openai_model"])
    except (LLMUnavailable, ImportError) as exc:
        print(f"LLM wording off ({exc}); reports are written by code.")
        return None


def make_service(args, fake: bool = False, scenario_end=None):
    from diagnostics.service import DiagnosticsService
    from diagnostics.settings import Settings
    from diagnostics.store import SQLiteStore
    settings = Settings()
    if fake:
        from diagnostics.local.fake import FakeSource
        source = FakeSource(settings.rules, settings.schema, scenario_end, n_sites=args.sites)
        db = args.db or str(ROOT / "out" / "demo.sqlite3")
    else:
        from diagnostics.sources.live import LiveSource
        source = LiveSource(settings)
        db = args.db or settings.db_path
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    return DiagnosticsService(source, settings, SQLiteStore(db), make_llm(args))


def print_counts(view: dict) -> None:
    print(f"Run {view['run_id']} ({'cached' if view['cached'] else 'new'})  {view['period']['local']}")
    for key, label in view["categories"].items():
        print(f"  {label:40} {view['counts'].get(key, 0):5}")
    for n in view["notes"]:
        print("  note:", n)


def cmd_demo(args):
    from diagnostics.local.viewer import export_html, serve
    from diagnostics.timewin import period_ending
    from diagnostics.settings import load_rules
    end = args.end or "2026-10-27T08:30"
    period = period_ending(end, load_rules())
    svc = make_service(args, fake=True, scenario_end=period.end)
    view = svc.screen(end, force=True)
    print_counts(view)
    expected = svc.source.expected()
    wrong = [(s["site"], expected[s["site"]], s["category"]) for s in view["sites"] if expected[s["site"]] != s["category"]]
    print(f"Synthetic scenarios: {len(view['sites']) - len(wrong)}/{len(view['sites'])} classified as built"
          + ("" if not wrong else f"; mismatches {wrong}"))
    reds = [s["site"] for s in view["sites"] if s["category"] == "red"]
    if reds:
        report = svc.diagnose(view["run_id"], reds[0], reuse=False)
        print("\n" + report["report"]["markdown"])
    path = export_html(svc, view["run_id"], args.out or ROOT / "out" / "demo_map.html")
    print(f"\nMap (evidence only): {path}")
    if args.serve:
        serve(svc, port=args.port)
    return 1 if wrong else 0


def cmd_inspect(args):
    from diagnostics.local import inspect_data
    from diagnostics.settings import Settings
    from diagnostics.sources.live import LiveSource
    settings = Settings()
    report = inspect_data.inspect(LiveSource(settings), settings, args.site, args.end, args.hours)
    print(inspect_data.summary(report))
    print("Saved:", inspect_data.save(report, args.out_dir))


def cmd_screen(args):
    svc = make_service(args)
    view = svc.screen(args.end, force=args.force)
    print_counts(view)
    if args.json:
        Path(args.json).write_text(json.dumps(view, indent=2, default=str), encoding="utf-8")
        print("Saved:", args.json)


def cmd_diagnose(args):
    svc = make_service(args)
    result = svc.diagnose(args.run, args.site, reuse=not args.fresh)
    if result["mode"] == "report":
        print(result["report"]["markdown"])
    else:
        print(json.dumps(result["site"], indent=2, default=str))


def cmd_map(args):
    from diagnostics.local.viewer import serve
    scenario = None
    if args.fake and args.end:
        from diagnostics.settings import load_rules
        from diagnostics.timewin import period_ending
        scenario = period_ending(args.end, load_rules()).end
    serve(make_service(args, fake=args.fake, scenario_end=scenario), port=args.port)


def cmd_export(args):
    from diagnostics.local.viewer import export_html
    print("Saved:", export_html(make_service(args), args.run, args.out))


def cmd_baseline(args):
    svc = make_service(args)
    start = date.fromisoformat(args.start) if args.start else datetime.now().date()
    days = [start + timedelta(days=i) for i in range(args.days)]
    n = svc.refresh_baselines(days, progress=lambda d, c: print(f"  {d}: {c} baselines"))
    print(f"Stored {n} baselines ({svc.settings.baseline_version}).")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", help=".env file (default: ./.env)")
    parser.add_argument("--db", help="SQLite file (default: DIAGNOSTICS_DB or diagnostics.sqlite3)")
    parser.add_argument("--no-llm", action="store_true", help="reports written by code only")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", help="synthetic network end to end")
    p.add_argument("--end", help="period end, default 2026-10-27T08:30")
    p.add_argument("--sites", type=int, default=48)
    p.add_argument("--out")
    p.add_argument("--serve", action="store_true")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("inspect", help="check the live feeds for one site")
    p.add_argument("--site", required=True)
    p.add_argument("--end")
    p.add_argument("--hours", type=float, default=2.0)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("screen", help="screen the network")
    p.add_argument("--end")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("diagnose", help="D001 + D002 for one site of a run")
    p.add_argument("--run", required=True)
    p.add_argument("--site", required=True)
    p.add_argument("--fresh", action="store_true")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("map", help="local map viewer")
    p.add_argument("--fake", action="store_true")
    p.add_argument("--end", help="with --fake: the scenario period end")
    p.add_argument("--sites", type=int, default=48)
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("export-html", help="one run as a single HTML file")
    p.add_argument("--run", required=True)
    p.add_argument("--out", default=str(ROOT / "out" / "map.html"))
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("baseline", help="weekly baseline job")
    p.add_argument("--start")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=cmd_baseline)

    args = parser.parse_args(argv)
    load_env(args.env)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
