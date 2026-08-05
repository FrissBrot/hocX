from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template, WordImportDocument
from app.schemas.word_import import WordImportAnalysis, WordImportCommit
from app.services.file_service import FileService
from app.services.protocol_service import ProtocolService
from app.services.word_import_service import WordImportService

logger = logging.getLogger(__name__)


class WordImportQueueService:
    """Wraps WordImportService (unchanged, still used as-is by the single-document
    wizard) with a persistent queue: uploaded files are stored + analyzed immediately,
    kept as 'eingelesen' until manually reviewed and committed, and every commit
    refreshes the cached suggestions of the still-open siblings sharing the same
    template - the just-learned WordImportProfile mapping is picked up automatically
    by WordImportService.analyze(), no separate propagation mechanism needed."""

    def __init__(self) -> None:
        self.word_import_service = WordImportService()
        self.file_service = FileService()
        self.protocol_service = ProtocolService()

    def ingest(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        created_by: int | None,
        files: list[tuple[str, bytes]],
    ) -> tuple[list[WordImportDocument], list[str]]:
        template = db.get(Template, template_id)
        if template is None or template.tenant_id != tenant_id:
            raise ValueError("Vorlage nicht gefunden")

        documents: list[WordImportDocument] = []
        errors: list[str] = []
        for filename, content in files:
            try:
                stored_file = self.file_service.save_word_import_document(
                    db, tenant_id=tenant_id, filename=filename, content=content, created_by=created_by
                )
                analysis = self.word_import_service.analyze(
                    db,
                    tenant_id=tenant_id,
                    template_id=template_id,
                    protocol_date_hint=None,
                    raw_bytes=content,
                )
                document = WordImportDocument(
                    tenant_id=tenant_id,
                    template_id=template_id,
                    stored_file_id=stored_file.id,
                    original_filename=filename,
                    display_name=self._compute_display_name(
                        db,
                        tenant_id=tenant_id,
                        template_id=template_id,
                        protocol_date=analysis.protocol_date,
                        fallback=filename,
                    ),
                    protocol_date=analysis.protocol_date,
                    status="eingelesen",
                    analysis_snapshot_json=analysis.model_dump(mode="json"),
                    created_by=created_by,
                )
                db.add(document)
                db.commit()
                db.refresh(document)
                documents.append(document)
            except Exception as exc:
                db.rollback()
                detail = getattr(exc, "detail", None) or "Datei konnte nicht gelesen werden"
                errors.append(f"{filename}: {detail}")
        return documents, errors

    def list_documents(self, db: Session, *, tenant_id: int, status: str | None = None) -> list[tuple[WordImportDocument, str]]:
        statement = (
            select(WordImportDocument, Template.name)
            .join(Template, Template.id == WordImportDocument.template_id)
            .where(WordImportDocument.tenant_id == tenant_id)
        )
        if status:
            statement = statement.where(WordImportDocument.status == status)
        statement = statement.order_by(WordImportDocument.created_at.desc())
        return [(row[0], row[1]) for row in db.execute(statement).all()]

    def get_document(self, db: Session, *, tenant_id: int, document_id: int) -> WordImportDocument | None:
        document = db.get(WordImportDocument, document_id)
        if document is None or document.tenant_id != tenant_id:
            return None
        return document

    def reanalyze(
        self,
        db: Session,
        *,
        document: WordImportDocument,
        protocol_date: date | None,
        table_role_overrides: dict[int, dict] | None,
    ) -> WordImportAnalysis:
        analysis = self._reanalyze_document(
            db, document=document, protocol_date=protocol_date, table_role_overrides=table_role_overrides
        )
        db.commit()
        return analysis

    def commit_document(
        self,
        db: Session,
        *,
        document: WordImportDocument,
        tenant_id: int,
        user_id: int | None,
        payload: WordImportCommit,
    ) -> int:
        if document.status == "importiert":
            raise ValueError("Dokument wurde bereits importiert")
        if payload.template_id != document.template_id:
            raise ValueError("Vorlage stimmt nicht mit dem Dokument überein")

        protocol_id = self.word_import_service.commit(db, tenant_id=tenant_id, user_id=user_id, payload=payload)

        document.status = "importiert"
        document.protocol_id = protocol_id
        document.imported_by = user_id
        document.imported_at = datetime.now(timezone.utc)
        db.add(document)
        db.commit()

        self._refresh_pending_siblings(db, tenant_id=tenant_id, template_id=document.template_id, exclude_id=document.id)
        return protocol_id

    def delete_document(self, db: Session, *, tenant_id: int, document_id: int) -> bool:
        document = self.get_document(db, tenant_id=tenant_id, document_id=document_id)
        if document is None:
            return False
        if document.status != "eingelesen":
            raise ValueError("Nur noch nicht importierte Dokumente können entfernt werden")
        stored_file = self.file_service.get_stored_file(db, document.stored_file_id)
        db.delete(document)
        db.flush()
        if stored_file is not None:
            self.file_service.delete_stored_file(db, stored_file)
        db.commit()
        return True

    def _refresh_pending_siblings(self, db: Session, *, tenant_id: int, template_id: int, exclude_id: int) -> None:
        siblings = list(
            db.execute(
                select(WordImportDocument).where(
                    WordImportDocument.tenant_id == tenant_id,
                    WordImportDocument.template_id == template_id,
                    WordImportDocument.status == "eingelesen",
                    WordImportDocument.id != exclude_id,
                )
            ).scalars()
        )
        for sibling in siblings:
            try:
                self._reanalyze_document(
                    db, document=sibling, protocol_date=sibling.protocol_date, table_role_overrides=None
                )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Vorschlags-Aktualisierung fehlgeschlagen für word_import_document id=%s", sibling.id)

    def _reanalyze_document(
        self,
        db: Session,
        *,
        document: WordImportDocument,
        protocol_date: date | None,
        table_role_overrides: dict[int, dict] | None,
    ) -> WordImportAnalysis:
        stored_file = self.file_service.get_stored_file(db, document.stored_file_id)
        if stored_file is None:
            raise ValueError("Original-Datei nicht mehr vorhanden")
        raw_bytes = self.file_service.read_stored_file_bytes(stored_file)
        analysis = self.word_import_service.analyze(
            db,
            tenant_id=document.tenant_id,
            template_id=document.template_id,
            protocol_date_hint=protocol_date,
            raw_bytes=raw_bytes,
            table_role_overrides=table_role_overrides or {},
        )
        document.protocol_date = analysis.protocol_date
        document.analysis_snapshot_json = analysis.model_dump(mode="json")
        document.display_name = self._compute_display_name(
            db,
            tenant_id=document.tenant_id,
            template_id=document.template_id,
            protocol_date=analysis.protocol_date,
            fallback=document.original_filename,
        )
        db.add(document)
        return analysis

    def _compute_display_name(
        self, db: Session, *, tenant_id: int, template_id: int, protocol_date: date | None, fallback: str
    ) -> str:
        if protocol_date is None:
            return fallback
        return self.protocol_service.preview_title(
            db, tenant_id=tenant_id, template_id=template_id, protocol_date=protocol_date, fallback=fallback
        )
