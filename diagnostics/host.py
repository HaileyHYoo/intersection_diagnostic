"""Host integration for the production backend.

    from dash_backend.ai_brains.intersections.diagnostics.host import service_for_bot
    svc = service_for_bot(bot)            # bot = the SCATSQaBot instance (its llm is reused)
    view = svc.screen()                   # layer activation / refresh: latest completed 30 minutes
    result = svc.diagnose(view["run_id"], "4397")   # map click

One service per process is enough; screen() is safe to call from several request threads at once.
"""
from __future__ import annotations

import threading

from .llm import HostLLM
from .service import DiagnosticsService
from .settings import Settings
from .sources.live import LiveSource
from .store import SQLiteStore

_service = None
_lock = threading.Lock()


def service_for_bot(bot=None, settings: Settings | None = None) -> DiagnosticsService:
    global _service
    with _lock:
        if _service is None:
            settings = settings or Settings()
            llm = HostLLM(bot.llm) if bot is not None and getattr(bot, "llm", None) is not None else None
            _service = DiagnosticsService(LiveSource(settings), settings, SQLiteStore(settings.db_path), llm)
        return _service
