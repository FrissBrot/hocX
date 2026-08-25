from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Event,
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    ProtocolImage,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    Tenant,
    WordImportDocument,
)
from app.schemas.admin import TenantCleanupCategory, TenantCleanupCounts
from app.services.file_service import _safe_storage_path


class TenantCleanupService:
    """Selective per-category data wipe for the admin 'Mandant aufräumen' panel.

    Unlike AdminTenantService.delete_tenant, this keeps the tenant and its structure
    (templates, user access, and - unless "lists_full" is picked - list definitions
    themselves) intact and only clears the operational data an admin opted into.
    Categories are independent and safe to combine in any subset within one call; see the
    inline notes below for the few cross-category ordering/FK details that matter when they
    are.
    """

    def preview(self, db: Session, tenant_id: int) -> TenantCleanupCounts:
        list_entries = int(
            db.scalar(
                select(func.count(ListEntry.id))
                .join(ListDefinition, ListDefinition.id == ListEntry.list_definition_id)
                .where(ListDefinition.tenant_id == tenant_id)
            )
            or 0
        )
        documents = int(
            db.scalar(select(func.count(WordImportDocument.id)).where(WordImportDocument.tenant_id == tenant_id)) or 0
        ) + int(
            db.scalar(
                select(func.count(SubmissionUpload.id))
                .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
                .where(SubmissionAssignment.tenant_id == tenant_id)
            )
            or 0
        )
        # _cleanup_documents also deletes every stored_file row this newly orphans (RESTRICT
        # into stored_file means the row survives the WordImportDocument/SubmissionUploadFile
        # delete on its own) - preview() previously never counted those at all, understating
        # how much "documents" actually removes (audit finding, 2026-08-25).
        documents += int(
            db.scalar(
                select(func.count(StoredFile.id.distinct())).where(
                    StoredFile.tenant_id == tenant_id,
                    ~select(ProtocolImage.id).where(ProtocolImage.stored_file_id == StoredFile.id).exists(),
                    or_(
                        select(WordImportDocument.id)
                        .where(WordImportDocument.stored_file_id == StoredFile.id, WordImportDocument.tenant_id == tenant_id)
                        .exists(),
                        select(SubmissionUploadFile.id)
                        .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
                        .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
                        .where(SubmissionUploadFile.stored_file_id == StoredFile.id, SubmissionAssignment.tenant_id == tenant_id)
                        .exists(),
                    ),
                )
            )
            or 0
        )
        return TenantCleanupCounts(
            protocols=self._count(db, Protocol, tenant_id),
            list_entries=list_entries,
            lists_full=self._count(db, ListDefinition, tenant_id),
            events=self._count(db, Event, tenant_id),
            todos=self._count(db, ProtocolTodo, tenant_id),
            participants=self._count(db, Participant, tenant_id),
            documents=documents,
        )

    def cleanup(self, db: Session, tenant_id: int, categories: list[TenantCleanupCategory]) -> TenantCleanupCounts | None:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        selected = set(categories)
        counts = TenantCleanupCounts()

        if "list_entries" in selected:
            result = db.execute(
                delete(ListEntry).where(
                    ListEntry.list_definition_id.in_(select(ListDefinition.id).where(ListDefinition.tenant_id == tenant_id))
                )
            )
            counts.list_entries = result.rowcount or 0

        if "lists_full" in selected:
            list_definition_ids = select(ListDefinition.id).where(ListDefinition.tenant_id == tenant_id)
            # submission_assignment.list_definition_id is ondelete=RESTRICT - an Abgabebox
            # box configured against one of these lists would otherwise block the delete.
            db.execute(delete(SubmissionAssignment).where(SubmissionAssignment.list_definition_id.in_(list_definition_ids)))
            result = db.execute(delete(ListDefinition).where(ListDefinition.tenant_id == tenant_id))
            counts.lists_full = result.rowcount or 0

        if "protocols" in selected:
            # Mirrors AdminTenantService.delete_tenant's ordering: word_import_document's
            # protocol_id FK is SET NULL rather than CASCADE, so it wouldn't otherwise follow
            # the protocols it points at, leaving dangling import-queue rows behind.
            db.execute(delete(WordImportDocument).where(WordImportDocument.tenant_id == tenant_id))
            result = db.execute(delete(Protocol).where(Protocol.tenant_id == tenant_id))
            counts.protocols = result.rowcount or 0

        if "events" in selected:
            result = db.execute(delete(Event).where(Event.tenant_id == tenant_id))
            counts.events = result.rowcount or 0

        if "todos" in selected:
            # Only standalone todos carry tenant_id directly - todos attached to a protocol
            # block are scoped through their protocol instead (see
            # block_field_sync._todo_tenant_id) and already cascade away with it whenever
            # "protocols" is selected too.
            result = db.execute(delete(ProtocolTodo).where(ProtocolTodo.tenant_id == tenant_id))
            counts.todos = result.rowcount or 0

        if "participants" in selected:
            result = db.execute(delete(Participant).where(Participant.tenant_id == tenant_id))
            counts.participants = result.rowcount or 0

        if "documents" in selected:
            counts.documents = self._cleanup_documents(db, tenant_id)

        db.commit()
        return counts

    def _count(self, db: Session, model, tenant_id: int) -> int:
        return int(db.scalar(select(func.count(model.id)).where(model.tenant_id == tenant_id)) or 0)

    def _cleanup_documents(self, db: Session, tenant_id: int) -> int:
        deleted = 0
        # No-op if "protocols" already cleared these in the same call.
        result = db.execute(delete(WordImportDocument).where(WordImportDocument.tenant_id == tenant_id))
        deleted += result.rowcount or 0

        upload_ids = list(
            db.scalars(
                select(SubmissionUpload.id)
                .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
                .where(SubmissionAssignment.tenant_id == tenant_id)
            )
        )
        # Captured before the SubmissionUpload delete below cascades SubmissionUploadFile
        # away with it (audit finding, 2026-08-25) - that join row is the only signal that
        # distinguishes an abgabebox-storage-root file from a regular app-storage-root one,
        # and the orphan sweep further down needs it to pick the correct root, same as the
        # three other places in this codebase that make this same distinction
        # (submission_service.py, tenant_export_service.py, tenant_clone_service.py).
        # Using settings.storage_root unconditionally here (as before this fix) meant
        # file_path.exists() was always false for an abgabebox upload, so the physical
        # file was silently never deleted even though the DB row was.
        abgabebox_stored_file_ids: set[int] = (
            set(db.scalars(select(SubmissionUploadFile.stored_file_id).where(SubmissionUploadFile.upload_id.in_(upload_ids))))
            if upload_ids
            else set()
        )
        if upload_ids:
            result = db.execute(delete(SubmissionUpload).where(SubmissionUpload.id.in_(upload_ids)))
            deleted += result.rowcount or 0

        # Sweep stored_file rows this tenant owns that nothing references anymore - includes
        # files newly orphaned above, plus e.g. protocol-image files left behind by a
        # "protocols" run earlier in this same call (protocol_image cascades away with its
        # protocol, but its RESTRICT into stored_file means the file row itself survives).
        orphaned = db.scalars(
            select(StoredFile).where(
                StoredFile.tenant_id == tenant_id,
                ~select(ProtocolImage.id).where(ProtocolImage.stored_file_id == StoredFile.id).exists(),
                ~select(WordImportDocument.id).where(WordImportDocument.stored_file_id == StoredFile.id).exists(),
                ~select(SubmissionUploadFile.id).where(SubmissionUploadFile.stored_file_id == StoredFile.id).exists(),
            )
        ).all()
        for stored_file in orphaned:
            root = settings.abgabebox_storage_root if stored_file.id in abgabebox_stored_file_ids else settings.storage_root
            file_path = _safe_storage_path(root, stored_file.storage_path)
            if file_path.exists():
                file_path.unlink()
            db.delete(stored_file)
            deleted += 1
        return deleted
