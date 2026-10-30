"""Host integration for the production backend.

    from dash_backend.ai_brains.intersections.diagnostics.host import service_for_bot
    svc = service_for_bot(bot)            # bot = the SCATSQaBot instance (its llm is reused)
    view = svc.screen()                   # layer activation / refresh: latest completed 30 minutes
    result = svc.diagnose(view["run_id"], "4397")   # map click

One service per process is enough; screen() is safe to call from several request threads at once.

With the production contract (contract/intersections_diagnostics_schemas.py), the Dash callbacks call
run_screening(ScreeningInput) and run_diagnosis(DiagnosisInput) instead and keep the run store themselves.
"""
from __future__ import annotations

import threading

from . import archive as history
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
            _service = DiagnosticsService(LiveSource(settings), settings, SQLiteStore(settings.db_path), llm,
                                          archive=history.open_archive(settings.archive_location))
        return _service


def run_screening(screening_input, settings: Settings | None = None):
    """Contract entry for the Dash background callback: ScreeningInput -> ScreeningResult.
    The callback keeps the shared ScreeningRun record (RUNNING / COMPLETED); this only computes."""
    from .contract import core
    settings = settings or Settings()
    store = SQLiteStore(settings.db_path)
    return core.run_screening(screening_input, LiveSource(settings), settings, store, audit_store=store,
                              archive=history.open_archive(settings.archive_location))


def run_diagnosis(diagnosis_input, bot=None, settings: Settings | None = None):
    """Contract entry for a click on a Red site: DiagnosisInput -> DiagnosisResult (the chatbot's LLM words it)."""
    from .contract import core
    settings = settings or Settings()
    llm = HostLLM(bot.llm) if bot is not None and getattr(bot, "llm", None) is not None else None
    return core.run_diagnosis(diagnosis_input, LiveSource(settings), settings, llm,
                              audit_store=SQLiteStore(settings.db_path))
