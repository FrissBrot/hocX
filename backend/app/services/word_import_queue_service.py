from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template, WordImportDocument
from app.schemas.word_import import WordImportAnalysis, WordImportCommit, WordImportCommitResult
from app.services.file_service import FileService
from app.services.protocol_service import ProtocolService
from app.services.word_import_service import WordImportService, _normalize

logger = logging.getLogger(__name__)

# Low enough to be useful for a modest batch (e.g. one department's 5-10 monthly
# protocols uploaded together), high enough that a single anomalous document's own
# idiosyncratic (mis-)match can't skew every other document in the batch.
_BATCH_CONSENSUS_MIN_DOCS = 3


def _header_signature(header_cells: list[str]) -> str:
    return _normalize(" | ".join(header_cells))


def _build_batch_consensus_hint(analyses: list[WordImportAnalysis]) -> dict:
    """Pure, DB-free: scans this batch's own already-computed analyses (NOT persisted
    WordImportProfile data, and never the opaque review_draft_json) for names/table-
    roles that were confidently resolved the same way in at least
    _BATCH_CONSENSUS_MIN_DOCS of them, and returns them in the same shape
    WordImportProfile.mapping_config_json uses - see
    WordImportService.analyze's `in_memory_profile_hints` parameter, which merges this
    on top of (never persists it into) the real profile for one re-analysis call.
    "Confidently resolved" reuses signals analyze() itself already exposes rather than
    re-scoring anything: an attendance row's suggested_participant_id being set at all
    (already gated on _PARTICIPANT_MATCH_THRESHOLD/the adaptive equivalent), and a
    table's role_is_explicit flag (came from an override/learned profile match, not a
    heuristic guess)."""
    name_votes: dict[str, Counter] = defaultdict(Counter)
    table_role_votes: dict[str, Counter] = defaultdict(Counter)
    for analysis in analyses:
        for mapping in analysis.attendance_mappings:
            if mapping.suggested_participant_id is not None and mapping.raw_name:
                name_votes[_normalize(mapping.raw_name)][mapping.suggested_participant_id] += 1
        for table in analysis.tables:
            if table.role_is_explicit:
                signature = _header_signature(table.header_cells)
                table_role_votes[signature][(table.role, table.list_definition_id, table.matrix_key)] += 1

    name_hints = {
        key: votes.most_common(1)[0][0] for key, votes in name_votes.items() if votes.most_common(1)[0][1] >= _BATCH_CONSENSUS_MIN_DOCS
    }
    table_role_hints: dict[str, dict] = {}
    for key, votes in table_role_votes.items():
        winner, count = votes.most_common(1)[0]
        if count >= _BATCH_CONSENSUS_MIN_DOCS:
            role, list_definition_id, matrix_key = winner
            table_role_hints[key] = {"role": role, "list_definition_id": list_definition_id, "matrix_key": matrix_key}

    if not name_hints and not table_role_hints:
        return {}
    return {"participant_name_overrides": name_hints, "table_roles_by_signature": table_role_hints}


def _needs_consensus_rerun(analysis: WordImportAnalysis, hint: dict) -> bool:
    """True when this document itself failed to confidently resolve at least one name
    or table role that the batch's consensus DOES have an answer for - a document that
    already resolved everything on its own is never re-analyzed, so the batch consensus
    can only ever fill gaps, never override an individual document's own confident
    (possibly document-specific and correctly different) resolution."""
    unresolved_names = {
        _normalize(mapping.raw_name)
        for mapping in analysis.attendance_mappings
        if mapping.suggested_participant_id is None and mapping.raw_name
    }
    if unresolved_names & hint.get("participant_name_overrides", {}).keys():
        return True
    unresolved_signatures = {_header_signature(table.header_cells) for table in analysis.tables if not table.role_is_explicit}
    if unresolved_signatures & hint.get("table_roles_by_signature", {}).keys():
        return True
    return False


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
        analyses: list[WordImportAnalysis] = []
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
                analyses.append(analysis)
            except Exception as exc:
                db.rollback()
                detail = getattr(exc, "detail", None) or "Datei konnte nicht gelesen werden"
                errors.append(f"{filename}: {detail}")

        # Display-name second pass (audit D13, 2026-08-16): ingest() processes files
        # sequentially, so a document ingested early in the batch only saw whichever
        # siblings existed as committed rows *before it*, not ones that arrive later in the
        # same batch - an unsorted upload (e.g. March before January) could show "1." on
        # the March document until a sibling committed or it was manually reanalyzed.
        # Purely cosmetic (the real commit-time numbering via _renumber_later_siblings was
        # already correct) - recomputes display_name now that every document in this batch
        # is a committed row and _compute_display_name can see all of them.
        if len(documents) > 1:
            for document in documents:
                document.display_name = self._compute_display_name(
                    db,
                    tenant_id=tenant_id,
                    template_id=template_id,
                    protocol_date=document.protocol_date,
                    fallback=document.original_filename,
                    exclude_document_id=document.id,
                )
            db.commit()

        # Batch-consensus pass (see C.11 plan / _build_batch_consensus_hint) - a single,
        # fixed second pass over documents that failed to confidently resolve something
        # the rest of THIS batch agrees on, never fed back into itself for a third pass
        # (no while-loop here by design, not an oversight - a batch consensus converging
        # over multiple rounds is not a goal, and would risk instability).
        if len(documents) > 1:
            hint = _build_batch_consensus_hint(analyses)
            if hint:
                for document, analysis in zip(documents, analyses):
                    if not _needs_consensus_rerun(analysis, hint):
                        continue
                    try:
                        self._apply_batch_consensus(db, document=document, hint=hint)
                    except Exception:
                        db.rollback()
                        logger.exception(
                            "Batch-Konsens-Aktualisierung fehlgeschlagen für word_import_document id=%s", document.id
                        )
        return documents, errors

    def _apply_batch_consensus(self, db: Session, *, document: WordImportDocument, hint: dict) -> None:
        stored_file = self.file_service.get_stored_file(db, document.stored_file_id)
        if stored_file is None:
            return
        raw_bytes = self.file_service.read_stored_file_bytes(stored_file)
        refreshed = self.word_import_service.analyze(
            db,
            tenant_id=document.tenant_id,
            template_id=document.template_id,
            protocol_date_hint=document.protocol_date,
            raw_bytes=raw_bytes,
            in_memory_profile_hints=hint,
        )
        document.protocol_date = refreshed.protocol_date
        document.analysis_snapshot_json = refreshed.model_dump(mode="json")
        document.display_name = self._compute_display_name(
            db,
            tenant_id=document.tenant_id,
            template_id=document.template_id,
            protocol_date=refreshed.protocol_date,
            fallback=document.original_filename,
            exclude_document_id=document.id,
        )
        db.add(document)
        db.commit()

    def list_documents(
        self, db: Session, *, tenant_id: int, status: str | None = None
    ) -> list[tuple[WordImportDocument, str, list[WordImportDocument]]]:
        statement = (
            select(WordImportDocument, Template.name)
            .join(Template, Template.id == WordImportDocument.template_id)
            .where(WordImportDocument.tenant_id == tenant_id)
        )
        if status:
            statement = statement.where(WordImportDocument.status == status)
        statement = statement.order_by(WordImportDocument.created_at.desc())
        rows = [(row[0], row[1]) for row in db.execute(statement).all()]
        duplicate_map = self._duplicate_map(db, tenant_id=tenant_id)
        return [(document, template_name, duplicate_map.get(document.id, [])) for document, template_name in rows]

    def duplicates_for_document(self, db: Session, document: WordImportDocument) -> list[WordImportDocument]:
        """Other documents (open or already imported) of the same tenant+template sharing
        the same recognized protocol_date - a same protocol very likely uploaded twice,
        e.g. once as .docx and once as .pdf, or under a different filename."""
        if document.protocol_date is None:
            return []
        statement = select(WordImportDocument).where(
            WordImportDocument.tenant_id == document.tenant_id,
            WordImportDocument.template_id == document.template_id,
            WordImportDocument.protocol_date == document.protocol_date,
            WordImportDocument.id != document.id,
        )
        return list(db.execute(statement).scalars())

    def _duplicate_map(self, db: Session, *, tenant_id: int) -> dict[int, list[WordImportDocument]]:
        rows = list(
            db.execute(
                select(WordImportDocument).where(
                    WordImportDocument.tenant_id == tenant_id,
                    WordImportDocument.protocol_date.is_not(None),
                )
            ).scalars()
        )
        groups: dict[tuple[int, date], list[WordImportDocument]] = {}
        for doc in rows:
            groups.setdefault((doc.template_id, doc.protocol_date), []).append(doc)
        result: dict[int, list[WordImportDocument]] = {}
        for docs in groups.values():
            if len(docs) < 2:
                continue
            for doc in docs:
                result[doc.id] = [other for other in docs if other.id != doc.id]
        return result

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

    def save_draft(self, db: Session, *, document: WordImportDocument, draft: dict) -> None:
        if document.status != "eingelesen":
            raise ValueError("Dokument wurde bereits importiert")
        document.review_draft_json = draft
        db.add(document)
        db.commit()

    def commit_document(
        self,
        db: Session,
        *,
        document: WordImportDocument,
        tenant_id: int,
        user_id: int | None,
        payload: WordImportCommit,
    ) -> WordImportCommitResult:
        # Row-locks the document for the rest of this transaction (audit D11, 2026-08-16):
        # without this, two near-simultaneous commit requests for the same document (double-
        # click, two tabs, a client retry after a slow response) can both read
        # status == "eingelesen" before either has written "importiert", so both proceed and
        # each creates its own Protocol - one gets referenced by this document, the other
        # survives as an invisible orphaned duplicate. A concurrent SELECT ... FOR UPDATE on
        # this row now blocks until the first commit's transaction ends, so the second
        # request re-reads the now-"importiert" status and hits the check below instead.
        db.execute(
            select(WordImportDocument).where(WordImportDocument.id == document.id).with_for_update()
        ).scalar_one()
        if document.status == "importiert":
            raise ValueError("Dokument wurde bereits importiert")
        if payload.template_id != document.template_id:
            raise ValueError("Vorlage stimmt nicht mit dem Dokument überein")

        result = self.word_import_service.commit(db, tenant_id=tenant_id, user_id=user_id, payload=payload)

        document.status = "importiert"
        document.protocol_id = result.id
        document.imported_by = user_id
        document.imported_at = datetime.now(timezone.utc)
        db.add(document)
        db.commit()

        self._refresh_pending_siblings(db, tenant_id=tenant_id, template_id=document.template_id, exclude_id=document.id)
        return result

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
                    db,
                    document=sibling,
                    protocol_date=sibling.protocol_date,
                    table_role_overrides=None,
                    reset_draft=False,
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
        reset_draft: bool = True,
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
        if reset_draft:
            # Row indices/candidates the old draft refers to no longer match the freshly
            # regenerated mappings above - keeping it around would silently misapply stale
            # edits (e.g. an "approved" flag landing on an unrelated row) on next reload.
            # Only true for an explicit, user-triggered reanalysis (table role override
            # or a manual re-read) - _refresh_pending_siblings below reanalyzes the SAME
            # unchanged document bytes purely to pick up a just-learned WordImportProfile
            # entry, so row structure can't have changed and wiping a reviewer's
            # in-progress draft there would be pure collateral damage from someone else's
            # unrelated commit (see reset_draft=False there).
            document.review_draft_json = {}
        document.display_name = self._compute_display_name(
            db,
            tenant_id=document.tenant_id,
            template_id=document.template_id,
            protocol_date=analysis.protocol_date,
            fallback=document.original_filename,
            exclude_document_id=document.id,
        )
        db.add(document)
        return analysis

    def _compute_display_name(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_date: date | None,
        fallback: str,
        exclude_document_id: int | None = None,
    ) -> str:
        if protocol_date is None:
            return fallback
        # Other documents still sitting in the queue ("eingelesen", not yet committed) for the
        # same template aren't real Protocol rows yet, so preview_title's own DB counts can't
        # see them - without passing their dates in as extra_dates, every document uploaded
        # together in one batch would preview with the identical number (all "1." etc.) until
        # the first one actually gets committed. exclude_document_id skips the document being
        # previewed itself when it already exists as a row (reanalyze / batch-consensus paths).
        sibling_query = select(WordImportDocument.protocol_date).where(
            WordImportDocument.tenant_id == tenant_id,
            WordImportDocument.template_id == template_id,
            WordImportDocument.status == "eingelesen",
            WordImportDocument.protocol_date.is_not(None),
        )
        if exclude_document_id is not None:
            sibling_query = sibling_query.where(WordImportDocument.id != exclude_document_id)
        extra_dates = [d for (d,) in db.execute(sibling_query).all()]
        return self.protocol_service.preview_title(
            db,
            tenant_id=tenant_id,
            template_id=template_id,
            protocol_date=protocol_date,
            fallback=fallback,
            extra_dates=extra_dates,
        )
