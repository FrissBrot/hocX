"""Abarbeitung der document_job-Aufträge (PDF-Konvertierung, Textextraktion) im document-worker.

Ablauf je Auftrag:
1. claim_next_job: atomar per FOR UPDATE SKIP LOCKED, mit Lease. Ein Auftrag, dessen Lease
   abgelaufen ist (Worker abgestürzt/hängt), wird erneut übernommen. Überschreitet er dabei
   max_attempts, wird er als fehlgeschlagen markiert statt endlos neu zu starten.
2. Freigabe prüfen: nur Originale mit scan_status 'clean' werden verarbeitet; 'pending'/'error'
   warten (ohne Versuch zu zählen), 'infected' sperrt den Auftrag endgültig.
3. Verarbeitung im Sandbox-Kindprozess (app/services/documents/), Eingabe nur über den Objekt-Key
   der Originaldatei aus der Datenbank, Ausgabe in einen eigenen Arbeitsordner.
4. Ergebnis speichern - nur wenn der Auftrag noch diesem Worker gehört (Lease-Prüfung unter
   Zeilensperre), sonst wird das Ergebnis verworfen.

PDF-Konvertierung und Extraktion sind getrennte Aufträge: ein Fehler im einen blockiert den
anderen nicht. Protokolliert werden nur IDs, Status und Fehlertypen - nie Dokumentinhalte oder
Dateinamen."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.objstore_client import ObjectNotFound, StorageError, StorageUnavailable, StorageWriteFenced
from app.core.storage import MAIN, get_object_store, storage_work_dir
from app.models import StoredFile
from app.models.document_entities import (
    FILE_ROLE_ORIGINAL,
    FILE_ROLE_PDF,
    JOB_KIND_EXTRACT,
    JOB_KIND_PDF,
    Document,
    DocumentExtraction,
    DocumentFile,
    DocumentJob,
    DocumentVersion,
)
from app.services import document_service
from app.services.documents import convert as convert_module
from app.services.documents import formats, ocr, sandbox
from app.services.documents.content import ParsedContent, build_content, to_plain_text
from app.services.stored_file_location import namespace_for_stored_file

_logger = logging.getLogger("hocx.document_worker")

MB = 1024 * 1024
# Wartezeit, wenn die Virenprüfung der Originaldatei noch aussteht.
SCAN_PENDING_DELAY = timedelta(minutes=10)
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600


class JobLeaseLost(Exception):
    """Ein anderer Worker hat den Auftrag übernommen (Lease abgelaufen)."""


class TransientJobError(Exception):
    """Vorübergehendes Problem (Speicher gesperrt/nicht erreichbar) - später erneut versuchen."""


@dataclass
class JobOutcome:
    status: str
    result: str | None = None
    error: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_SECONDS * 2 ** max(attempt - 1, 0), BACKOFF_CAP_SECONDS))


# ── Auftragsverwaltung ────────────────────────────────────────────────────────


def claim_next_job(db: Session, owner: str) -> int | None:
    """Übernimmt den nächsten fälligen Auftrag (oder einen mit abgelaufener Lease) und gibt seine ID
    zurück. Commit erfolgt hier, damit die Lease sofort für andere Worker sichtbar ist."""
    row = db.execute(
        text(
            """
            UPDATE document_job SET
                status = 'running', lease_owner = :owner,
                lease_expires_at = NOW() + make_interval(secs => :lease),
                attempts = attempts + 1, started_at = NOW(), finished_at = NULL, updated_at = NOW()
            WHERE id = (
                SELECT id FROM document_job
                WHERE (status = 'queued' AND run_after <= NOW())
                   OR (status = 'running' AND lease_expires_at < NOW())
                ORDER BY run_after, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """
        ),
        {"owner": owner, "lease": settings.document_job_lease_seconds},
    ).first()
    db.commit()
    return row[0] if row else None


def renew_lease(db: Session, job_id: int, owner: str) -> bool:
    result = db.execute(
        text(
            "UPDATE document_job SET lease_expires_at = NOW() + make_interval(secs => :lease), updated_at = NOW() "
            "WHERE id = :id AND lease_owner = :owner AND status = 'running'"
        ),
        {"id": job_id, "owner": owner, "lease": settings.document_job_lease_seconds},
    )
    db.commit()
    return result.rowcount == 1


def _lock_owned_job(db: Session, job_id: int, owner: str) -> DocumentJob:
    job = db.scalar(select(DocumentJob).where(DocumentJob.id == job_id).with_for_update())
    if job is None or job.status != "running" or job.lease_owner != owner:
        raise JobLeaseLost(f"Auftrag {job_id} gehört nicht mehr diesem Worker")
    return job


def _finish(db: Session, job: DocumentJob, outcome: JobOutcome) -> None:
    job.status = outcome.status
    job.result = outcome.result
    job.last_error = outcome.error
    job.lease_owner = None
    job.lease_expires_at = None
    job.finished_at = _now()
    job.updated_at = _now()


def _defer(db: Session, job: DocumentJob, *, delay: timedelta, count_attempt: bool, error: str | None) -> None:
    job.status = "queued"
    job.run_after = _now() + delay
    if not count_attempt:
        job.attempts = max(job.attempts - 1, 0)
    job.last_error = error
    job.lease_owner = None
    job.lease_expires_at = None
    job.updated_at = _now()


# ── Verarbeitung ──────────────────────────────────────────────────────────────


@dataclass
class _JobContext:
    job: DocumentJob
    version: DocumentVersion
    document: Document
    original: StoredFile


def _load_context(db: Session, job: DocumentJob) -> _JobContext | None:
    version = db.get(DocumentVersion, job.document_version_id)
    document = db.get(Document, version.document_id) if version is not None else None
    original = db.scalar(
        select(StoredFile)
        .join(DocumentFile, DocumentFile.stored_file_id == StoredFile.id)
        .where(DocumentFile.document_version_id == job.document_version_id, DocumentFile.role == FILE_ROLE_ORIGINAL)
    )
    if version is None or document is None or original is None:
        return None
    # Mandantentrennung: Auftrag, Dokument und Datei müssen demselben Mandanten gehören.
    if not (job.tenant_id == document.tenant_id == original.tenant_id):
        raise ValueError("Mandant von Auftrag, Dokument und Datei stimmt nicht überein")
    return _JobContext(job=job, version=version, document=document, original=original)


def process_job(db: Session, job_id: int, owner: str) -> JobOutcome:
    """Verarbeitet einen übernommenen Auftrag vollständig und committet das Ergebnis."""
    job = db.get(DocumentJob, job_id)
    if job is None or job.lease_owner != owner:
        return JobOutcome(status="skipped")
    if job.attempts > job.max_attempts:
        # Ein Auftrag, der den Worker wiederholt abstürzen lässt, darf ihn nicht endlos blockieren.
        _finish(db, job, JobOutcome(status="failed", result="too_many_attempts", error=job.last_error or "Worker abgebrochen"))
        if job.kind == JOB_KIND_EXTRACT:
            _store_failed_extraction(db, job.document_version_id, "too_many_attempts")
        db.commit()
        return JobOutcome(status="failed", result="too_many_attempts")

    try:
        context = _load_context(db, job)
    except ValueError as exc:
        db.rollback()
        return _handle_failure(db, job_id, owner, exc, transient=False)
    if context is None:
        # Dokument/Version/Original inzwischen gelöscht - nichts mehr zu tun.
        _finish(db, job, JobOutcome(status="done", result="gone"))
        db.commit()
        return JobOutcome(status="done", result="gone")

    scan_status = context.original.scan_status
    if scan_status == "infected":
        outcome = JobOutcome(status="blocked", result="infected")
        _finish(db, job, outcome)
        db.commit()
        return outcome
    if scan_status != "clean":
        _defer(db, job, delay=SCAN_PENDING_DELAY, count_attempt=False, error=f"scan_status={scan_status}")
        db.commit()
        return JobOutcome(status="queued", result="scan_pending")

    work_dir = storage_work_dir("documents", f"job-{job.id}-{uuid.uuid4().hex[:8]}")
    try:
        if job.kind == JOB_KIND_PDF:
            outcome = _run_pdf(db, context, owner, work_dir)
        elif job.kind == JOB_KIND_EXTRACT:
            outcome = _run_extract(db, context, owner, work_dir)
        else:
            outcome = JobOutcome(status="failed", result="unknown_kind")
            job = _lock_owned_job(db, job_id, owner)
            _finish(db, job, outcome)
            db.commit()
        return outcome
    except JobLeaseLost:
        db.rollback()
        _logger.warning("document job %s: Lease verloren, Ergebnis verworfen", job_id)
        return JobOutcome(status="lost")
    except (StorageWriteFenced, StorageUnavailable, TransientJobError) as exc:
        db.rollback()
        return _handle_failure(db, job_id, owner, exc, transient=True)
    except Exception as exc:  # noqa: BLE001 - jeder Fehler wird am Auftrag vermerkt
        db.rollback()
        return _handle_failure(db, job_id, owner, exc, transient=False)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


def _handle_failure(db: Session, job_id: int, owner: str, exc: BaseException, *, transient: bool) -> JobOutcome:
    try:
        job = _lock_owned_job(db, job_id, owner)
    except JobLeaseLost:
        db.rollback()
        return JobOutcome(status="lost")
    error = _error_text(exc)
    if transient:
        _defer(db, job, delay=backoff(1), count_attempt=False, error=error)
        db.commit()
        return JobOutcome(status="queued", result="transient", error=error)
    if job.attempts >= job.max_attempts:
        _finish(db, job, JobOutcome(status="failed", result="error", error=error))
        if job.kind == JOB_KIND_EXTRACT:
            _store_failed_extraction(db, job.document_version_id, error)
        db.commit()
        return JobOutcome(status="failed", result="error", error=error)
    _defer(db, job, delay=backoff(job.attempts), count_attempt=True, error=error)
    db.commit()
    return JobOutcome(status="queued", result="retry", error=error)


def _read_original(db: Session, original: StoredFile) -> bytes:
    limit = settings.document_max_input_mb * MB
    namespace = namespace_for_stored_file(db, original)
    try:
        return get_object_store().get_bytes(namespace, original.storage_path, max_bytes=limit)
    except (StorageUnavailable, StorageWriteFenced):
        raise
    except ObjectNotFound as exc:
        # Dauerhaft: zählt als Versuch und endet nach max_attempts als Fehler.
        raise ValueError("Originaldatei fehlt im Speicher") from exc
    except StorageError as exc:
        raise TransientJobError(f"Originaldatei nicht lesbar: {type(exc).__name__}") from exc


def _too_large(original: StoredFile) -> bool:
    return (original.file_size_bytes or 0) > settings.document_max_input_mb * MB


def _run_pdf(db: Session, context: _JobContext, owner: str, work_dir: Path) -> JobOutcome:
    original = context.original
    existing_pdf = db.scalar(
        select(DocumentFile).where(DocumentFile.document_version_id == context.version.id, DocumentFile.role == FILE_ROLE_PDF)
    )
    if original.mime_type == formats.PDF or (existing_pdf is not None and not existing_pdf.is_generated):
        outcome = JobOutcome(status="done", result="already_pdf")
    elif not formats.needs_conversion(original.mime_type):
        outcome = JobOutcome(status="done", result="unsupported")
    elif _too_large(original):
        outcome = JobOutcome(status="done", result="too_large")
    else:
        data = _read_original(db, original)
        pdf = convert_module.convert(
            data, original.mime_type, target="pdf", work_dir=work_dir,
            limits=sandbox.Limits(
                timeout_seconds=settings.document_convert_timeout_seconds,
                memory_bytes=settings.document_convert_memory_mb * MB,
            ),
        )
        _store_generated_pdf(db, context, owner, pdf)
        return JobOutcome(status="done", result="converted")
    job = _lock_owned_job(db, context.job.id, owner)
    _finish(db, job, outcome)
    db.commit()
    return outcome


def _store_generated_pdf(db: Session, context: _JobContext, owner: str, pdf: bytes) -> None:
    job = _lock_owned_job(db, context.job.id, owner)
    key = document_service.generated_key(context.document.tenant_id, context.document, context.version, f"{uuid.uuid4().hex}.pdf")
    store = get_object_store()
    info = store.put_bytes(db, MAIN, key, pdf, content_type=formats.PDF)
    try:
        stem = Path(context.original.original_name).stem or "dokument"
        generated = StoredFile(
            tenant_id=context.document.tenant_id,
            original_name=f"{stem}.pdf",
            mime_type=formats.PDF,
            storage_path=key,
            file_size_bytes=info.size,
            checksum_sha256=info.sha256,
            # Aus einer bereits als sauber geprüften Datei in der Sandbox erzeugt.
            scan_status="clean",
            created_by=None,
        )
        db.add(generated)
        db.flush()
        previous = list(
            db.scalars(
                select(DocumentFile).where(
                    DocumentFile.document_version_id == context.version.id,
                    DocumentFile.role == FILE_ROLE_PDF,
                    DocumentFile.is_generated.is_(True),
                )
            )
        )
        previous_ids = [row.stored_file_id for row in previous]
        for row in previous:
            db.delete(row)
        db.flush()
        db.add(DocumentFile(document_version_id=context.version.id, stored_file_id=generated.id, role=FILE_ROLE_PDF, is_generated=True))
        _finish(db, job, JobOutcome(status="done", result="converted"))
        document_service._delete_generated_files(db, previous_ids)
        db.commit()
    except Exception:
        db.rollback()
        try:
            store.delete(db, MAIN, key)
            db.commit()
        except Exception:  # noqa: BLE001 - Rest räumt remove_orphaned_generated_files nicht auf (kein Row), Objekt bleibt
            db.rollback()
            _logger.warning("document job %s: erzeugtes PDF konnte nach Fehler nicht entfernt werden", context.job.id)
        raise


def _extraction_limits() -> sandbox.Limits:
    return sandbox.Limits(
        timeout_seconds=settings.document_extract_timeout_seconds, memory_bytes=settings.document_extract_memory_mb * MB
    )


def _run_parser_sandboxed(parser: str, mime_type: str, data: bytes, work_dir: Path) -> dict:
    source = work_dir / "input.bin"
    source.write_bytes(data)
    output = work_dir / "content.json"
    sandbox.run(
        sandbox.python_entry_args("extract", parser, mime_type, str(source), str(output)),
        work_dir=work_dir, limits=_extraction_limits(),
    )
    return json.loads(output.read_text(encoding="utf-8"))


def _extract_content(db: Session, context: _JobContext, work_dir: Path) -> tuple[str, dict | None, str | None]:
    """(Status, Inhalt, Fehler) - Status wie document_extraction.status."""
    original = context.original
    parser = formats.extraction_parser(original.mime_type)
    if parser is None:
        return "unsupported", None, None
    if _too_large(original):
        return "failed", None, "input_too_large"
    data = _read_original(db, original)
    if parser == "doc":
        # Kein Python-Parser für das alte Word-Binärformat: im Sandbox-LibreOffice nach DOCX
        # umwandeln (unabhängig vom PDF-Auftrag) und den DOCX-Parser verwenden.
        doc_dir = work_dir / "doc"
        doc_dir.mkdir(parents=True, exist_ok=True)
        docx = convert_module.convert(
            data, original.mime_type, target="docx", work_dir=doc_dir,
            limits=sandbox.Limits(
                timeout_seconds=settings.document_convert_timeout_seconds,
                memory_bytes=settings.document_convert_memory_mb * MB,
            ),
        )
        content = _run_parser_sandboxed("docx", original.mime_type, docx, work_dir)
        content["source"]["parser"] = "doc+libreoffice"
    else:
        content = _run_parser_sandboxed(parser, original.mime_type, data, work_dir)
    needs_ocr = bool(content.pop("needs_ocr", False))
    if needs_ocr:
        page_count = content.get("page_count") or 0
        if not ocr.ocr_available():
            return "ocr_required", content, "ocr_unavailable"
        if page_count > settings.document_ocr_max_pages:
            return "ocr_required", content, "too_many_pages_for_ocr"
        ocr_dir = work_dir / "ocr"
        ocr_dir.mkdir(exist_ok=True)
        parsed: ParsedContent = ocr.ocr_pdf(
            data, page_count=page_count, work_dir=ocr_dir,
            limits=sandbox.Limits(
                timeout_seconds=settings.document_ocr_timeout_seconds, memory_bytes=settings.document_extract_memory_mb * MB
            ),
        )
        content = build_content(parsed, mime_type=original.mime_type)
    if not any(block["type"] in ("heading", "paragraph", "list", "table") for block in content.get("blocks") or []):
        return "empty", content, None
    return "ready", content, None


def _upsert_extraction(db: Session, version_id: int, **values) -> None:
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == version_id))
    if extraction is None:
        extraction = DocumentExtraction(document_version_id=version_id)
        db.add(extraction)
    for key, value in values.items():
        setattr(extraction, key, value)
    extraction.updated_at = _now()


def _store_failed_extraction(db: Session, version_id: int, error: str) -> None:
    _upsert_extraction(
        db, version_id, status="failed", parser=None, parser_version=None, content=None, plain_text=None,
        page_count=None, char_count=None, ocr_applied=False, warnings=[], error=error[:2000],
    )


def _run_extract(db: Session, context: _JobContext, owner: str, work_dir: Path) -> JobOutcome:
    status, content, error = _extract_content(db, context, work_dir)
    plain_text = to_plain_text(content) if content else None
    if plain_text is not None and len(plain_text) > settings.document_max_text_chars:
        status, content, plain_text, error = "failed", None, None, "text_too_large"
    job = _lock_owned_job(db, context.job.id, owner)
    source = (content or {}).get("source") or {}
    _upsert_extraction(
        db,
        context.version.id,
        status=status,
        parser=source.get("parser"),
        parser_version=source.get("parser_version"),
        schema_version=(content or {}).get("schema_version") or 1,
        content=content,
        plain_text=plain_text,
        page_count=(content or {}).get("page_count"),
        char_count=len(plain_text) if plain_text is not None else None,
        ocr_applied=bool((content or {}).get("ocr_applied")),
        warnings=list((content or {}).get("warnings") or []),
        error=error,
    )
    outcome = JobOutcome(status="done", result={"ready": "extracted"}.get(status, status), error=None)
    _finish(db, job, outcome)
    db.commit()
    return outcome
