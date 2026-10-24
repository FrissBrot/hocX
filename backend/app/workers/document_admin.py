"""Betriebswerkzeug für die Dokumentverarbeitung (läuft im backend- oder document-worker-Container).

    python -m app.workers.document_admin status
    python -m app.workers.document_admin backfill [--batches N]
    python -m app.workers.document_admin requeue [--status failed|blocked] [--kind pdf|extract] [--tenant ID]
    python -m app.workers.document_admin reprocess --kind pdf|extract [--tenant ID]

- status:    Anzahl Dokumente, Aufträge je Status und Extraktionen je Status.
- backfill:  führt die Anlage aus document_sync sofort aus (bestehende Dateien und Exporte),
             wiederholbar ohne Duplikate. Standard: so lange, bis nichts mehr anzulegen ist.
- requeue:   fehlgeschlagene/gesperrte Aufträge erneut einreihen (z. B. nach Behebung einer Störung).
- reprocess: abgeschlossene Aufträge erneut einreihen, z. B. alle Extraktionen nach einem
             Parser-Update. Die Originale bleiben unverändert; Ergebnisse werden ersetzt.

Schreibt keine Dokumentinhalte aus."""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.document_entities import Document, DocumentExtraction, DocumentJob, DocumentVersion
from app.services import document_service, document_sync_service, protocol_export_document_service


def _status(db) -> None:
    print("Dokumente:", db.scalar(select(func.count()).select_from(Document)))
    for kind, status, count in db.execute(
        select(DocumentJob.kind, DocumentJob.status, func.count()).group_by(DocumentJob.kind, DocumentJob.status).order_by(DocumentJob.kind)
    ).all():
        print(f"Auftrag {kind:8} {status:8} {count}")
    for status, count in db.execute(select(DocumentExtraction.status, func.count()).group_by(DocumentExtraction.status)).all():
        print(f"Extraktion {status:13} {count}")


def _backfill(db, batches: int | None) -> None:
    total_files = total_exports = 0
    round_number = 0
    while batches is None or round_number < batches:
        round_number += 1
        files = document_sync_service.register_missing_documents(db, limit=settings.document_sync_batch_size)
        exports = protocol_export_document_service.backfill(db, limit=settings.document_sync_batch_size)
        db.commit()
        total_files += files
        total_exports += exports
        print(f"Durchgang {round_number}: {files} Dateien, {exports} Exportgruppen")
        if files == 0 and exports == 0:
            break
    print(f"Fertig: {total_files} Dokumente aus Dateien, {total_exports} Exportgruppen angelegt")


def _requeue(db, *, statuses: list[str], kind: str | None, tenant: int | None) -> None:
    query = select(DocumentJob, DocumentVersion).join(DocumentVersion, DocumentVersion.id == DocumentJob.document_version_id).where(
        DocumentJob.status.in_(statuses)
    )
    if kind:
        query = query.where(DocumentJob.kind == kind)
    if tenant:
        query = query.where(DocumentJob.tenant_id == tenant)
    count = 0
    for job, version in db.execute(query).all():
        document_service.enqueue_job(db, version, job.kind, tenant_id=job.tenant_id, reset=True)
        count += 1
    db.commit()
    print(f"{count} Aufträge neu eingereiht")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="document_admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--batches", type=int, default=None)
    requeue = sub.add_parser("requeue")
    requeue.add_argument("--status", choices=["failed", "blocked"], action="append")
    requeue.add_argument("--kind", choices=["pdf", "extract"])
    requeue.add_argument("--tenant", type=int)
    reprocess = sub.add_parser("reprocess")
    reprocess.add_argument("--kind", choices=["pdf", "extract"], required=True)
    reprocess.add_argument("--tenant", type=int)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        if args.command == "status":
            _status(db)
        elif args.command == "backfill":
            _backfill(db, args.batches)
        elif args.command == "requeue":
            _requeue(db, statuses=args.status or ["failed", "blocked"], kind=args.kind, tenant=args.tenant)
        elif args.command == "reprocess":
            _requeue(db, statuses=["done", "failed"], kind=args.kind, tenant=args.tenant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
