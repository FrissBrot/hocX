"""document-worker: arbeitet document_job-Aufträge ab (PDF-Konvertierung, Textextraktion).

Eigener Container mit Backend-Image (docker-compose*.yml), eigenem Ressourcenbudget und ohne
eingehende Ports. Mehrere Instanzen sind sicher (FOR UPDATE SKIP LOCKED + Lease, siehe
app/services/document_processing_service.py). Während voller Wartung werden keine Aufträge
übernommen. Lebenszeichen und Läufe erscheinen unter /admin/jobs (Job document_worker)."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.error_log import record_system_error
from app.core.job_runs import format_job_error, record_job_run
from app.services import document_processing_service as processing
from app.services.maintenance_service import current_effective_state

_logger = logging.getLogger("hocx.document_worker")

JOB_NAME = "document_worker"
HEARTBEAT_SECONDS = 60


def _heartbeat() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT record_job_heartbeat(:job_name)"), {"job_name": JOB_NAME})
    except Exception:  # noqa: BLE001 - Lebenszeichen ist best effort, fehlt es, meldet /admin/jobs das
        _logger.warning("Heartbeat konnte nicht gemeldet werden", exc_info=True)


class _LeaseKeeper(threading.Thread):
    """Verlängert die Lease eines laufenden Auftrags, solange er bearbeitet wird - lange OCR- oder
    Konvertierungsläufe sollen nicht von einem zweiten Worker übernommen werden."""

    def __init__(self, job_id: int, owner: str) -> None:
        super().__init__(daemon=True)
        self.job_id = job_id
        self.owner = owner
        self.stop = threading.Event()

    def run(self) -> None:
        interval = max(settings.document_job_lease_seconds / 3, 10)
        while not self.stop.wait(interval):
            _heartbeat()
            try:
                with SessionLocal() as db:
                    if not processing.renew_lease(db, self.job_id, self.owner):
                        return
            except Exception:  # noqa: BLE001 - nächster Versuch beim nächsten Intervall
                _logger.warning("Lease von Auftrag %s konnte nicht verlängert werden", self.job_id, exc_info=True)


def run_once(owner: str) -> bool:
    """Bearbeitet höchstens einen Auftrag. True, wenn einer bearbeitet wurde."""
    if current_effective_state().full_active:
        return False
    with SessionLocal() as db:
        job_id = processing.claim_next_job(db, owner)
    if job_id is None:
        return False
    keeper = _LeaseKeeper(job_id, owner)
    keeper.start()
    started_at = datetime.now(UTC)
    try:
        with SessionLocal() as db:
            outcome = processing.process_job(db, job_id, owner)
        _logger.info("document job %s: %s (%s)", job_id, outcome.status, outcome.result)
        status = "failure" if outcome.status == "failed" else "success"
        record_job_run(
            JOB_NAME, status=status, started_at=started_at, finished_at=datetime.now(UTC),
            error=f"Auftrag {job_id}: {outcome.error}"[:4000] if status == "failure" else None, keep_history=False,
        )
    except Exception as exc:
        # Unerwartet (Fehler ausserhalb der Auftragsbehandlung, z. B. DB weg): protokollieren,
        # der Auftrag wird nach Ablauf der Lease erneut übernommen.
        _logger.exception("document job %s: unerwarteter Fehler", job_id)
        with SessionLocal() as db:
            record_system_error(db, exc=exc)
        record_job_run(
            JOB_NAME, status="failure", started_at=started_at, finished_at=datetime.now(UTC),
            error=format_job_error(exc), keep_history=False,
        )
    finally:
        keeper.stop.set()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    _logger.info("document-worker %s gestartet", owner)
    last_heartbeat = 0.0
    while not stopping.is_set():
        now = datetime.now(UTC).timestamp()
        if now - last_heartbeat >= HEARTBEAT_SECONDS:
            _heartbeat()
            last_heartbeat = now
        try:
            worked = run_once(owner)
        except Exception as exc:  # noqa: BLE001 - z. B. DB nicht erreichbar: weiter versuchen
            _logger.exception("document-worker: Durchlauf fehlgeschlagen")
            try:
                with SessionLocal() as db:
                    record_system_error(db, exc=exc)
            except Exception:  # noqa: BLE001
                pass
            worked = False
        if not worked:
            stopping.wait(settings.document_worker_poll_seconds)


if __name__ == "__main__":
    main()
