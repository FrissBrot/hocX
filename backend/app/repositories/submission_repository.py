from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    Event,
    GalleryImage,
    ListDefinition,
    ListEntry,
    Participant,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    SubmissionUploadLog,
    Tenant,
)
from app.services import public_id_service


class SubmissionRepository:
    def list_assignments(self, db: Session, *, tenant_id: int) -> list[SubmissionAssignment]:
        statement = (
            select(SubmissionAssignment)
            .where(SubmissionAssignment.tenant_id == tenant_id)
            .order_by(SubmissionAssignment.title.asc(), SubmissionAssignment.id.asc())
        )
        return list(db.scalars(statement))

    def get_assignment(self, db: Session, assignment_id: int) -> SubmissionAssignment | None:
        return db.get(SubmissionAssignment, assignment_id)

    def get_assignment_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> SubmissionAssignment | None:
        return public_id_service.get_by_public_id(db, SubmissionAssignment, public_id, tenant_id=tenant_id)

    def create_assignment(self, db: Session, assignment: SubmissionAssignment) -> SubmissionAssignment:
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return assignment

    def update_assignment(self, db: Session, assignment: SubmissionAssignment, values: dict) -> SubmissionAssignment:
        for key, value in values.items():
            setattr(assignment, key, value)
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return assignment

    def delete_assignment(self, db: Session, assignment: SubmissionAssignment) -> None:
        db.delete(assignment)
        db.commit()

    def list_events_by_tag(self, db: Session, *, tenant_id: int, tag: str) -> list[Event]:
        statement = (
            select(Event)
            .where(Event.tenant_id == tenant_id, Event.tag == tag)
            .order_by(Event.event_date.asc(), Event.id.asc())
        )
        return list(db.scalars(statement))

    def get_event(self, db: Session, event_id: int) -> Event | None:
        return db.get(Event, event_id)

    def get_list_definition(self, db: Session, list_definition_id: int) -> ListDefinition | None:
        return db.get(ListDefinition, list_definition_id)

    def list_list_entries(self, db: Session, *, list_definition_id: int) -> list[ListEntry]:
        statement = (
            select(ListEntry)
            .where(ListEntry.list_definition_id == list_definition_id)
            .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
        )
        return list(db.scalars(statement))

    def get_list_entry(self, db: Session, list_entry_id: int) -> ListEntry | None:
        return db.get(ListEntry, list_entry_id)

    def get_participants(self, db: Session, *, participant_ids: list[int]) -> dict[int, Participant]:
        if not participant_ids:
            return {}
        statement = select(Participant).where(Participant.id.in_(participant_ids))
        return {participant.id: participant for participant in db.scalars(statement)}

    def list_uploads_for_assignment(self, db: Session, *, assignment_id: int) -> list[SubmissionUpload]:
        statement = (
            select(SubmissionUpload)
            .where(SubmissionUpload.assignment_id == assignment_id)
            .order_by(SubmissionUpload.id.asc())
        )
        return list(db.scalars(statement))

    def get_upload(self, db: Session, upload_id: int) -> SubmissionUpload | None:
        return db.get(SubmissionUpload, upload_id)

    def get_upload_by_public_id(self, db: Session, public_id: uuid.UUID) -> SubmissionUpload | None:
        # No tenant_id column of its own (scoped via assignment_id) - callers must verify
        # tenant/access on the resolved row's assignment.
        return public_id_service.get_by_public_id(db, SubmissionUpload, public_id)

    def create_upload(self, db: Session, upload: SubmissionUpload) -> SubmissionUpload:
        db.add(upload)
        db.commit()
        db.refresh(upload)
        return upload

    def list_upload_files(self, db: Session, *, upload_id: int) -> list[tuple[SubmissionUploadFile, StoredFile]]:
        statement = (
            select(SubmissionUploadFile, StoredFile)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(SubmissionUploadFile.upload_id == upload_id)
            .order_by(SubmissionUploadFile.sort_index.asc())
        )
        return [(row.SubmissionUploadFile, row.StoredFile) for row in db.execute(statement)]

    def get_upload_file(self, db: Session, upload_file_id: int) -> SubmissionUploadFile | None:
        return db.get(SubmissionUploadFile, upload_file_id)

    def get_upload_file_by_public_id(self, db: Session, public_id: uuid.UUID) -> SubmissionUploadFile | None:
        # No tenant_id column of its own (scoped via upload_id -> assignment) - callers
        # must verify tenant/access on the resolved row.
        return public_id_service.get_by_public_id(db, SubmissionUploadFile, public_id)

    def get_stored_file(self, db: Session, stored_file_id: int) -> StoredFile | None:
        return db.get(StoredFile, stored_file_id)

    def delete_upload_file(self, db: Session, upload_file: SubmissionUploadFile) -> None:
        db.delete(upload_file)
        db.commit()

    def delete_stored_file(self, db: Session, stored_file: StoredFile) -> None:
        db.delete(stored_file)
        db.commit()

    def list_upload_log(self, db: Session, *, assignment_id: int, element_ref: str) -> list[SubmissionUploadLog]:
        statement = (
            select(SubmissionUploadLog)
            .where(SubmissionUploadLog.assignment_id == assignment_id, SubmissionUploadLog.element_ref == element_ref)
            .order_by(SubmissionUploadLog.created_at.desc())
        )
        return list(db.scalars(statement))

    def get_tenant(self, db: Session, tenant_id: int) -> Tenant | None:
        return db.get(Tenant, tenant_id)

    def list_todos_for_submission_assignment(self, db: Session, submission_assignment_id: int) -> list[ProtocolTodo]:
        statement = select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == submission_assignment_id)
        return list(db.scalars(statement))

    def list_pending_files_for_assignment(
        self, db: Session, *, assignment_id: int
    ) -> list[tuple[StoredFile, str]]:
        """Return (stored_file, element_ref) for all pending files of an assignment."""
        statement = (
            select(StoredFile, SubmissionUpload.event_id, SubmissionUpload.list_entry_id)
            .join(SubmissionUploadFile, SubmissionUploadFile.stored_file_id == StoredFile.id)
            .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
            .where(
                SubmissionUpload.assignment_id == assignment_id,
                StoredFile.scan_status == "pending",
            )
        )
        result = []
        for row in db.execute(statement):
            event_id = row.event_id
            list_entry_id = row.list_entry_id
            element_ref = f"event-{event_id}" if event_id is not None else f"entry-{list_entry_id}"
            result.append((row.StoredFile, element_ref))
        return result

    def list_assignment_ids_with_pending_files(self, db: Session) -> list[int]:
        """Used by the periodic rescan job (main.py) - previously ClamAV-fail-open uploads only
        ever got rescanned if an admin happened to click the manual rescan button."""
        statement = (
            select(SubmissionUpload.assignment_id)
            .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(StoredFile.scan_status == "pending")
            .distinct()
        )
        return [row[0] for row in db.execute(statement)]

    def count_submissions_summary(self, db: Session, *, assignment_id: int) -> dict:
        """Count distinct elements across public submissions and linked in-app uploads."""
        public_files = db.execute(
            select(Event.public_id, ListEntry.public_id, StoredFile.scan_status)
            .select_from(SubmissionUpload)
            .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .outerjoin(Event, Event.id == SubmissionUpload.event_id)
            .outerjoin(ListEntry, ListEntry.id == SubmissionUpload.list_entry_id)
            .where(SubmissionUpload.assignment_id == assignment_id)
        )
        files = [
            (f"event-{event_id}" if event_id else f"entry-{entry_id}" if entry_id else "manual", status)
            for event_id, entry_id, status in public_files
        ]
        files.extend(db.execute(
            select(GalleryImage.submission_element_ref, StoredFile.scan_status)
            .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
            .join(SubmissionAssignment, SubmissionAssignment.id == GalleryImage.submission_assignment_id)
            .where(
                GalleryImage.submission_assignment_id == assignment_id,
                GalleryImage.tenant_id == SubmissionAssignment.tenant_id,
                StoredFile.tenant_id == SubmissionAssignment.tenant_id,
            )
        ).all())
        return {
            "submitted": len({ref for ref, _ in files}),
            "quarantine": len({ref for ref, status in files if status == "pending"}),
            "infected": len({ref for ref, status in files if status == "infected"}),
            "clean": len({ref for ref, status in files if status == "clean"}),
        }

    def count_list_entries(self, db: Session, *, list_definition_id: int) -> int:
        stmt = select(func.count()).where(ListEntry.list_definition_id == list_definition_id)
        return db.scalar(stmt) or 0

    def create_upload_log(
        self,
        db: Session,
        *,
        assignment_id: int,
        element_ref: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        log = SubmissionUploadLog(
            assignment_id=assignment_id,
            element_ref=element_ref,
            status=status,
            error_message=error_message,
        )
        db.add(log)
        db.commit()

    def update_stored_file_scan(
        self,
        db: Session,
        stored_file: StoredFile,
        *,
        scan_status: str,
        storage_path: str | None = None,
    ) -> None:
        stored_file.scan_status = scan_status
        if storage_path is not None:
            stored_file.storage_path = storage_path
        db.add(stored_file)
        db.commit()
