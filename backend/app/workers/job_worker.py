"""job-worker: schwere Hintergrundarbeit in einem eigenen Container (Concurrency-Audit Paket 10).

Vorher liefen Galerie-Ingest, Qualitäts-Backfill, Vereinsexport, Rescans, Album-Sync und die
grossen Aufräumjobs in jedem uvicorn-Worker des Backends mit - und konkurrierten dort mit allen
Requests aller Mandanten um CPU, RAM, Threadpool und DB-Pool. Hier laufen sie in einem eigenen
Prozess mit eigenem Ressourcenbudget (docker-compose*.yml), über denselben
run_advisory_locked_loop wie bisher (Singleton per Advisory Lock, Meldung an /admin/jobs).
Dazu die Aufträge "PDF erzeugen" (document_render_jobs, app/services/document_render_jobs.py).

Überwachung: Heartbeat als Worker-Job "job_worker" (job_registry.py), Laufzeitkennzahlen
(Event-Loop, Pool, Threadpool) unter /admin/system, Container im Systemstatus.

Start: python -m app.workers.job_worker
"""

from __future__ import annotations

import asyncio
import logging
import signal

from sqlalchemy import text

from app.core import runtime_metrics
from app.core.config import settings
from app.core.db import engine
from app.core.loops import JOB_WORKER_LOOPS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_logger = logging.getLogger("hocx.job_worker")

JOB_NAME = "job_worker"
HEARTBEAT_SECONDS = 60


def _heartbeat() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT record_job_heartbeat(:job_name)"), {"job_name": JOB_NAME})
    except Exception:
        _logger.warning("Heartbeat konnte nicht gemeldet werden", exc_info=True)


async def _heartbeat_loop() -> None:
    while True:
        await asyncio.to_thread(_heartbeat)
        await asyncio.sleep(HEARTBEAT_SECONDS)


def loop_factories() -> list:
    from app.services.document_render_jobs import document_render_loop

    return [*JOB_WORKER_LOOPS, document_render_loop]


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    tasks = [asyncio.create_task(factory()) for factory in loop_factories()]
    tasks.append(asyncio.create_task(_heartbeat_loop()))
    tasks.append(
        asyncio.create_task(
            runtime_metrics.run_monitor(runtime_metrics.RuntimeReporter(settings.app_database_url or settings.database_url, settings.process_kind), engine)
        )
    )
    _logger.info("job-worker gestartet: %d Loops", len(tasks) - 2)
    await stop.wait()
    _logger.info("job-worker beendet sich")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    from app.documents.renderer import shutdown_renderer

    shutdown_renderer()


if __name__ == "__main__":
    asyncio.run(main())
