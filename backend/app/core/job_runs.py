"""Meldet Läufe periodischer Jobs an system_job_status/system_job_run (siehe job_registry.py und
Migration 0105). Best effort: ein Fehler beim Melden darf den Job selbst nie stören, landet aber
in system_error_log, statt still zu verschwinden."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.core.error_log import record_system_error

_logger = logging.getLogger(__name__)

_ERROR_MAX_LENGTH = 4000


def format_job_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_ERROR_MAX_LENGTH]


def record_job_run(
    job_name: str,
    *,
    status: Literal["success", "failure"],
    started_at: datetime,
    finished_at: datetime,
    error: str | None = None,
    keep_history: bool = True,
) -> None:
    try:
        # Eigene Verbindung/Transaktion: die Session des Jobs ist nach einem Fehler
        # zurückgerollt bzw. gehört dem Job - das Protokoll soll davon unabhängig committen.
        with engine.begin() as conn:
            conn.execute(
                text("SELECT record_job_run(:job_name, :status, :started_at, :finished_at, :error, :keep_history)"),
                {
                    "job_name": job_name,
                    "status": status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "error": error,
                    "keep_history": keep_history,
                },
            )
    except Exception as exc:
        _logger.exception("Lauf von Job %s konnte nicht protokolliert werden", job_name)
        with SessionLocal() as db:
            record_system_error(db, exc=exc)
