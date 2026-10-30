"""Local command line for Intersections Diagnostics V1.

    python main.py demo [--serve]                    synthetic network: screen, check, export map
    python main.py inspect --site 4397 [--end ...]   check the live feeds for one site
    python main.py screen [--end 2026-10-27T08:30]   screen the network (latest completed period by default)
    python main.py diagnose --run ID --site 4397     D001 + D002 report for a Red site
    python main.py summary [--run ID]                why sites got their category (stored run)
    python main.py map [--fake]                      local map viewer (http://127.0.0.1:8765)
    python main.py export-html --run ID --out out/map.html
    python main.py baseline [--start 2026-10-30] [--days 7]   weekly baseline job (+ weekly baseline snapshot)
    python main.py archive --run ID                  write a run's screening JSON log if it is missing
    python main.py site-history --site 4397 --from 2026-10-01 --to 2026-10-31   categories over screened periods
    python main.py watch                             (later extension) screen every new period as it completes
    python main.py backfill --from ... --to ...      (later extension) screen past periods one by one

Every completed screening writes one JSON log, and every baseline it uses is in that week's baseline
snapshot, under DIAGNOSTICS_ARCHIVE (a folder or s3://bucket/prefix; default: "archive" next to the database).

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
    from diagnostics.archive import open_archive
    from diagnostics.service import DiagnosticsService
    from diagnostics.settings import Settings
    from diagnostics.store import SQLiteStore
    settings = Settings()
    if fake:
        from diagnostics.local.fake import FakeSource
        source = FakeSource(settings.rules, settings.schema, scenario_end, n_sites=args.sites)
        db = args.db or str(ROOT / "out" / "demo.sqlite3")
        archive = open_archive(str(Path(db).parent / "demo_archive"))      # never mixed with live records
    else:
        from diagnostics.sources.live import LiveSource
        source = LiveSource(settings)
        db = args.db or settings.db_path
        settings.db_path = db
        archive = open_archive(settings.archive_location)
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    return DiagnosticsService(source, settings, SQLiteStore(db), make_llm(args), archive=archive)


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
    source = LiveSource(settings)
    report = inspect_data.inspect(source, settings, args.site, args.end, args.hours)
    print(inspect_data.summary(report))
    if args.history:
        report["history"] = inspect_data.history(source, settings, args.site, args.end)
        print(inspect_data.history_text(report["history"]))
    print("Saved:", inspect_data.save(report, args.out_dir))


def cmd_screen(args):
    import time
    svc = make_service(args)
    started = time.monotonic()
    view = svc.screen(args.end, force=args.force)
    print_counts(view)
    print(f"  took {time.monotonic() - started:.0f} s")
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


def cmd_summary(args):
    from diagnostics.local import summary
    svc = make_service(args, fake=args.fake)
    run_id = args.run or next((r["run_id"] for r in svc.store.list_runs(50) if r["status"] == "complete"), None)
    if not run_id:
        print("No complete screening run in the store; run `python main.py screen` first.")
        return 1
    result = summary.summarise({**svc.store.get_run(run_id)["payload"], "run_id": run_id})
    print(summary.text(result))
    print("Saved:", summary.save(result, args.out_dir))


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


def cmd_archive(args):
    svc = make_service(args)
    key = svc.archive_run(args.run)
    print(f"{svc.archive}: {key}" if key else "Not written (see the warning above, or no archive configured).")


def cmd_site_history(args):
    from diagnostics.archive import site_history
    svc = make_service(args, fake=args.fake)
    if svc.archive is None:
        print("No archive configured (DIAGNOSTICS_ARCHIVE=off).")
        return 1
    h = site_history(svc.archive, svc.settings.region, args.site, args.start, args.end)
    print(f"Site {h['site']} {h['from']}..{h['to']}: {h['screened_periods']} screened periods, "
          f"counts {h['counts']}, Red share {h['red_share']}")
    print("  Periods without a screening are not counted; the site was in no run for "
          f"{h['periods_without_this_site']} screened period(s).")
    for period, category in h["timeline"][-args.last:]:
        print(f"  {period}  {category}")


def cmd_watch(args):
    import logging
    from diagnostics.schedule import run_scheduled
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    svc = make_service(args)
    print("Screening every new period; Ctrl+C to stop.")
    try:
        run_scheduled(svc, max_runs=args.runs, on_run=print_counts)
    except KeyboardInterrupt:
        pass


def cmd_backfill(args):
    from diagnostics.schedule import backfill
    n = backfill(make_service(args), args.start, args.end, on_run=print_counts)
    print(f"{n} periods screened.")


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
    p.add_argument("--history", action="store_true", help="also show the reference periods behind the baseline")
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

    p = sub.add_parser("summary", help="why sites got their category, for a stored run")
    p.add_argument("--run", help="run id (default: the latest complete run)")
    p.add_argument("--fake", action="store_true", help="read the demo store")
    p.add_argument("--sites", type=int, default=48)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_summary)

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

    p = sub.add_parser("archive", help="write a run's screening JSON log if it is missing")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("site-history", help="a site's categories over the screened periods in the archive")
    p.add_argument("--site", required=True)
    p.add_argument("--from", dest="start", required=True, help="first local date, e.g. 2026-10-01")
    p.add_argument("--to", dest="end", required=True, help="last local date")
    p.add_argument("--last", type=int, default=20, help="timeline rows to print")
    p.add_argument("--fake", action="store_true", help="read the demo archive")
    p.add_argument("--sites", type=int, default=48)
    p.set_defaults(func=cmd_site_history)

    p = sub.add_parser("watch", help="(later extension) screen every new period as it completes")
    p.add_argument("--runs", type=int, help="stop after this many periods")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("backfill", help="(later extension) screen past periods one by one")
    p.add_argument("--from", dest="start", required=True, help="first period end, e.g. 2026-10-26T07:00")
    p.add_argument("--to", dest="end", required=True, help="last period end")
    p.set_defaults(func=cmd_backfill)

    args = parser.parse_args(argv)
    load_env(args.env)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
