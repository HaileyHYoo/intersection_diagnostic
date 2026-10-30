"""Local map viewer: a small HTTP server around DiagnosticsService, and a single-file HTML export.

    python main.py map            live data   ->  http://127.0.0.1:8765
    python main.py map --fake     synthetic network
    python main.py export-html    the screening run as one HTML file (evidence only, no D001/D002)

Only the standard library is used. The map tiles (CARTO dark) and Leaflet load from the internet.
"""
from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HTML = Path(__file__).resolve().parent / "map.html"


def _json(obj) -> bytes:
    return json.dumps(obj, default=str).encode("utf-8")


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("  " + fmt % args)

        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    return self._send(200, HTML.read_bytes(), "text/html")
                if url.path == "/api/screen":
                    view = service.screen(q.get("end") or None, force=q.get("force") == "1")
                    return self._send(200, _json(view))
                if url.path == "/api/site":
                    return self._send(200, _json(service.site_evidence(q["run"], q["site"])))
                if url.path == "/api/diagnose":
                    return self._send(200, _json(service.diagnose(q["run"], q["site"], reuse=q.get("reuse") != "0")))
                if url.path == "/api/runs":
                    return self._send(200, _json(service.store.list_runs()))
                return self._send(404, _json({"error": "not found"}))
            except (KeyError, ValueError) as exc:
                return self._send(400, _json({"error": str(exc)}))
            except Exception as exc:  # noqa: BLE001 - shown in the panel, full trace in the console
                traceback.print_exc()
                return self._send(500, _json({"error": f"{type(exc).__name__}: {exc}"}))

    return Handler


def serve(service, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(service))
    print(f"Intersection Diagnostics map: http://{host}:{port}   (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def export_html(service, run_id: str, out: str | Path) -> Path:
    run = service.store.get_run(run_id)
    if not run:
        raise KeyError(f"No run {run_id}.")
    view = service.map_view(run, cached=True)
    static = {"map": view, "evidence": {s["site"]: s for s in run["payload"]["sites"]}}
    script = "<script>window.__STATIC__ = " + json.dumps(static, default=str).replace("</", "<\\/") + ";</script>"
    html = HTML.read_text(encoding="utf-8").replace("<script>\nconst STATIC", script + "\n<script>\nconst STATIC", 1)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
