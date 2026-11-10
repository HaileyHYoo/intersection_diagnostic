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
    python main.py contract-check [--run ID]         validate a stored run against the production contract
    python main.py contract-report --site 1037       the SiteReport the production page receives (JSON + page view)
    python main.py audit-reports --end "AM peak=2026-11-10T08:30" ...   every Red/Amber report of several periods
    python main.py examples [--run ID | --end ...]   example outputs per category (Markdown + HTML) for review
    python main.py queue-probe --site 719 --end 2026-11-02T15:30   which TomTom queue-archive request works
    python main.py audit --end 2026-10-30T15:30      Q1-Q3 input audit: problem types with example intersections (read only)
    python main.py stats --end 2026-10-30T15:30      every check counted on its own for every site (no gates), JSON + CSV
    python main.py export-run --run ID               the run's screening log and baseline snapshot as plain JSON files
    python main.py kpi-check --site 707 --end 2026-10-30T15:30 [--references 3]   every stored PerfKpi/PerfApproach field
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


def cmd_examples(args):
    from diagnostics import tomtom_map
    from diagnostics.local import examples
    from diagnostics.settings import package_file
    svc = make_service(args, fake=args.fake)
    if args.end:
        run_id = svc.screen(args.end)["run_id"]
    else:
        run_id = args.run or next((r["run_id"] for r in svc.store.list_runs(50) if r["status"] == "complete"), None)
    if not run_id:
        print("No complete screening run in the store; run `python main.py screen` first or pass --end.")
        return 1
    mapped = {s for s, m in tomtom_map.load(str(package_file(svc.settings.schema["tomtom_mapping"]["file"]))).items()
              if m.get("uuid")} if not args.fake else None
    text = examples.build(svc, run_id, red=args.red, sites=args.site, tomtom_sites=mapped, synthetic=args.fake)
    print("Saved:", examples.save(text, run_id, args.out_dir))
    print("Saved:", examples.save_html(text, run_id, args.out_dir))


def cmd_queue_probe(args):
    """Tries the queue-archive request variants for one site and period and shows which return queue rows,
    so the TOMTOM_QUEUE_* settings are set from evidence (as the chatbot's probe_queue_archive.py):
    the daily archive (from/to) and the hourly archive (day/hour[/quarterHour], archiveType LIVE/HISTORICAL)."""
    import urllib.parse
    import zipfile
    from datetime import timedelta
    from diagnostics.settings import Settings
    from diagnostics.sources.base import DataUnavailable
    from diagnostics.sources.live import LiveSource
    from diagnostics.sources.tomtom_queue import download, parse_archive
    from diagnostics.timewin import period_ending
    settings = Settings()
    source = LiveSource(settings)
    period = period_ending(args.end, settings.rules)
    uuid = source.tomtom_mapping(args.site)["uuid"]
    if not uuid:
        print(f"Site {args.site} has no TomTom junction in the mapping file.")
        return 1
    spec = settings.schema["tomtom_queue"]
    daily = spec["url_template"].replace("{junction_uuid}", urllib.parse.quote(uuid, safe=""))
    hourly = daily.replace("/data/flat/daily", "/data/flat/hourly")

    def attempt(url, params):
        try:
            blob = download(url, params)
        except DataUnavailable as exc:
            return str(exc)
        try:
            rows = parse_archive(blob, spec)
        except (zipfile.BadZipFile, DataUnavailable) as exc:
            text = blob[:160].decode("utf-8", "replace").replace("\n", " ")
            return f"returned {len(blob)} bytes, not a queue archive ({type(exc).__name__}): {text}"
        inside = [r for r in rows if period.start < r["time"] <= period.end]
        span = f"{min(r['time'] for r in rows):%m-%d %H:%M}..{max(r['time'] for r in rows):%m-%d %H:%M} UTC" if rows else "-"
        return f"OK: {len(rows)} rows ({span}), {len(inside)} in the period"

    day = period.day
    print(f"Site {args.site}, junction {uuid}, period {period.label()} ({period.start:%Y-%m-%d %H:%M}-{period.end:%H:%M} UTC)")
    if args.arrival:
        return _arrival_probe(uuid, period, args)
    print("\nDaily archive (.../data/flat/daily)")
    for first, last in ((day, day), (day - timedelta(days=1), day)):
        params = {"from": first.isoformat(), "to": last.isoformat()}
        print(f"  {params}  ->  {attempt(daily, params)}")
    print("\nHourly archive (.../data/flat/hourly)")
    utc, local = period.start, period.local_start
    for zone, t in (("UTC", utc), ("Melbourne", local)):
        for kind in ("LIVE", "HISTORICAL"):
            for quarter in (None, t.minute // 15):
                params = {"day": t.date().isoformat(), "hour": t.hour, "archiveType": kind}
                if quarter is not None:
                    params["quarterHour"] = quarter
                print(f"  {zone:9} {params}  ->  {attempt(hourly, params)}")
    print("\nSend this output back; the working variant becomes the setting for recent and older periods.")


def _arrival_probe(uuid, period, args):
    """The raw-data arrival-times archive (hourly; day/hour/quarterHour/archiveType as the chatbot's
    fetch_tomtom_archive.py), saved as received, to see whether it holds a queue length at all."""
    import json
    import urllib.parse
    from diagnostics.sources.base import DataUnavailable
    from diagnostics.sources.tomtom_queue import download
    url = ("https://api.tomtom.com/junction-analytics/junctions/1/archive/" + urllib.parse.quote(uuid, safe="")
           + "/raw-data/arrival-times/hourly")
    start = period.start
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for kind in ("LIVE", "HISTORICAL"):
        params = {"day": start.strftime("%Y-%m-%d"), "hour": start.hour, "quarterHour": start.minute // 15, "archiveType": kind}
        try:
            blob = download(url, params)
        except DataUnavailable as exc:
            print(f"  arrival-times {kind:10} {params}: {exc}")
            continue
        path = out / f"arrival_{args.site}_{start:%Y%m%dT%H%M}Z_{kind}.bin"
        path.write_bytes(blob)
        text = blob[:200000].decode("utf-8", "replace")
        try:
            data = json.loads(blob)
            keys = list(data)[:15] if isinstance(data, dict) else f"list of {len(data)}"
        except ValueError:
            keys = "not JSON (first bytes: " + repr(blob[:12]) + ")"
        print(f"  arrival-times {kind:10} {params}: OK {len(blob)} bytes, top-level {keys}, "
              f"mentions queue: {'queue' in text.lower()}  -> saved {path}")
    print("Send the saved file(s); they hold no API key.")


def cmd_audit_reports(args):
    """Every Red report and Amber evidence page of several periods, with an index for a full review."""
    from diagnostics.local import report_audit
    svc = make_service(args, fake=args.fake)
    periods = report_audit.parse_periods(args.end)
    batch = report_audit.run(svc, periods, args.out_dir, amber_speed=not args.no_amber_speed, resume=args.resume,
                             rescreen=args.rescreen)
    print("Saved:", batch)
    return 0


def cmd_contract_report(args):
    """The production contract's SiteReport for Red/Amber sites of a stored run, as JSON and as a page view."""
    from diagnostics.local import contract_view
    svc = make_service(args, fake=args.fake)
    run_id = args.run or next((r["run_id"] for r in svc.store.list_runs(50) if r["status"] == "complete"), None)
    if not run_id:
        print("No complete screening run in the store; run `python main.py screen` first.")
        return 1
    for site in args.site:
        try:
            report = contract_view.site_report(svc, run_id, site)
        except Exception as exc:  # noqa: BLE001 - e.g. a Normal or Grey site has no report
            print(f"SCATS {site}: no SiteReport ({exc})")
            continue
        for path in contract_view.save(report, run_id, args.out_dir):
            print("Saved:", path)
    return 0


def cmd_contract_check(args):
    """Every site of a stored run through the production contract's models and validators."""
    from collections import Counter
    from diagnostics.contract import adapter
    svc = make_service(args, fake=args.fake)
    run_id = args.run or next((r["run_id"] for r in svc.store.list_runs(50) if r["status"] == "complete"), None)
    if not run_id:
        print("No complete screening run in the store; run `python main.py screen` first.")
        return 1
    payload = svc.store.get_run(run_id)["payload"]
    result = adapter.screening_result(payload, svc.settings, run=run_id)
    S = adapter.S
    counts = Counter(s.category.value for s in result.sites)
    print(f"Run {run_id}  {payload['period']['local']}: {len(result.sites)} of {len(payload['sites'])} sites valid "
          f"under the contract, {len(result.errors)} not representable")
    print("  categories:", dict(counts))
    grey = [s for s in result.sites if s.category == S.SiteCategory.GREY]
    print(f"  Grey with insufficient_data_reason: {sum(bool(s.insufficient_data_reason) for s in grey)} of {len(grey)}")
    print(f"  Grey because of no green (site_grey_no_green): "
          f"{sum(bool(s.q3 and s.q3.phase_service and s.q3.phase_service.site_grey_no_green) for s in grey)}")
    for site, error in list(result.errors.items())[:20]:
        print(f"  ERROR {site}: {error}")
    log = S.ScreeningLog.from_run(S.ScreeningRun(
        run_id=run_id, status=S.RunStatus.COMPLETED, started_at=result.completed_at, result=result,
        key=S.ScreeningCacheKey(region=result.region, period_end=result.period.end, baseline_version=result.baseline_version)))
    print(f"  ScreeningLog summary: {log.summary.model_dump()}  ({len(log.model_dump_json()) / 1e6:.1f} MB as JSON)")
    return 1 if result.errors else 0


def cmd_archive(args):
    svc = make_service(args)
    key = svc.archive_run(args.run)
    print(f"{svc.archive}: {key}" if key else "Not written (see the warning above, or no archive configured).")


def cmd_export_run(args):
    from diagnostics.archive import read_json
    svc = make_service(args)
    if svc.archive is None:
        print("No archive configured (DIAGNOSTICS_ARCHIVE=off).")
        return 1
    run_id = args.run or next((r["run_id"] for r in svc.store.list_runs(50) if r["status"] == "complete"), None)
    find = lambda: [k for k in svc.archive.keys("screening-logs/") if k.endswith(f"_{run_id}.json")]
    keys = find() or ([svc.archive_run(run_id)] if svc.store.get_run(run_id) else [])
    keys = [k for k in keys if k]
    if not keys:
        print(f"No screening log for run {run_id} in {svc.archive}.")
        return 1
    log = read_json(svc.archive, keys[0])
    out = Path(args.out_dir) / f"export_{run_id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "screening_log.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    print(f"Screening log  {keys[0]} -> {out / 'screening_log.json'}")
    snap_key = (log.get("metadata") or {}).get("baseline_snapshot") or log.get("baseline_snapshot")
    snap = read_json(svc.archive, snap_key) if snap_key else None
    if snap is None:
        print(f"Baseline snapshot {snap_key or '(not referenced by the log)'} not found in {svc.archive}.")
        return 1
    (out / "baseline_snapshot.json").write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    print(f"Baseline snapshot {snap_key} -> {out / 'baseline_snapshot.json'}")
    return 0


def cmd_audit(args):
    from diagnostics.local import audit
    svc = make_service(args, fake=args.fake)
    result = audit.run(svc, args.end, args.run)
    stamp = svc.period(args.end).key.replace(":", "")
    for path in audit.save(result, args.out_dir, stamp):
        print("Saved:", path)
    print(audit.markdown(result)[:4000])


def cmd_stats(args):
    from diagnostics.local import independent
    svc = make_service(args, fake=args.fake)
    summary, rows = independent.run(svc, args.end)
    print(independent.text(summary))
    stamp = svc.period(args.end).key.replace(":", "")
    for path in independent.save(summary, rows, args.out_dir, stamp):
        print("Saved:", path)


def cmd_kpi_check(args):
    from diagnostics.local import inspect_data
    from diagnostics.settings import Settings
    from diagnostics.sources.live import LiveSource
    settings = Settings()
    k = inspect_data.kpi_check(LiveSource(settings), settings, args.site, args.end, args.references)
    print(inspect_data.kpi_check_text(k))
    path = Path(args.out_dir) / f"kpi_check_{k['site']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(k, indent=2, default=str), encoding="utf-8")
    print("Saved:", path)


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

    p = sub.add_parser("queue-probe", help="which TomTom queue-archive request works for a site and period")
    p.add_argument("--site", required=True)
    p.add_argument("--end", required=True, help="period end, e.g. 2026-11-02T15:30")
    p.add_argument("--arrival", action="store_true", help="try the raw-data arrival-times archive instead")
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_queue_probe)

    p = sub.add_parser("examples", help="example outputs per category (Markdown + HTML) for review")
    p.add_argument("--run", help="run id (default: the latest complete run)")
    p.add_argument("--end", help="screen this period first (e.g. 2026-11-02T15:30) and use it")
    p.add_argument("--red", type=int, default=2, help="number of Red reports")
    p.add_argument("--site", nargs="*", help="prefer these sites as the examples")
    p.add_argument("--fake", action="store_true", help="use the demo store")
    p.add_argument("--sites", type=int, default=48)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_examples)

    p = sub.add_parser("audit-reports", help="every Red/Amber report of several periods, for a full review")
    p.add_argument("--end", nargs="+", required=True,
                   help='period ends, optionally labelled: "AM peak=2026-11-10T08:30" "Weekend midday=2026-11-08T12:30"')
    p.add_argument("--no-amber-speed", action="store_true", help="skip link speed on Amber pages (much faster)")
    p.add_argument("--resume", action="store_true", help="reuse Red reports already saved for the same run")
    p.add_argument("--rescreen", action="store_true", help="screen the periods again instead of reusing stored runs")
    p.add_argument("--fake", action="store_true", help="use the demo store")
    p.add_argument("--sites", type=int, default=48)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_audit_reports)

    p = sub.add_parser("contract-report", help="the production SiteReport for sites of a stored run (JSON + page view)")
    p.add_argument("--site", nargs="+", required=True, help="Red or Amber SCATS site numbers")
    p.add_argument("--run", help="run id (default: the latest complete run)")
    p.add_argument("--fake", action="store_true", help="read the demo store")
    p.add_argument("--sites", type=int, default=48)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_contract_report)

    p = sub.add_parser("contract-check", help="validate a stored run against the production contract")
    p.add_argument("--run", help="run id (default: the latest complete run)")
    p.add_argument("--fake", action="store_true", help="read the demo store")
    p.add_argument("--sites", type=int, default=48)
    p.set_defaults(func=cmd_contract_check)

    p = sub.add_parser("archive", help="write a run's screening JSON log if it is missing")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("export-run", help="a run's screening log and baseline snapshot as plain JSON files")
    p.add_argument("--run")
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_export_run)

    p = sub.add_parser("audit", help="Q1-Q3 input audit with problem types and example intersections (read only)")
    p.add_argument("--end", help="period end (default: the latest completed period)")
    p.add_argument("--run", help="screening run of that period (default: the latest one)")
    p.add_argument("--fake", action="store_true", help="use the synthetic network")
    p.add_argument("--sites", type=int, default=48, help=argparse.SUPPRESS)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("stats", help="every check counted on its own for every site (no gates)")
    p.add_argument("--end", help="period end (default: the latest completed period)")
    p.add_argument("--fake", action="store_true", help="use the synthetic network")
    p.add_argument("--sites", type=int, default=48, help=argparse.SUPPRESS)
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("kpi-check", help="every stored IntersectionPerfKpi / IntersectionPerfApproach field for a site")
    p.add_argument("--site", required=True)
    p.add_argument("--end")
    p.add_argument("--references", type=int, default=0, help="also show this many reference periods")
    p.add_argument("--out-dir", default=str(ROOT / "out"))
    p.set_defaults(func=cmd_kpi_check)

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
