from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    Event,
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

    def count_submissions_summary(self, db: Session, *, assignment_id: int) -> dict:
        """Count submitted elements and those in quarantine for an assignment.

        An element is identified by its (event_id, list_entry_id) pair - exactly one of the
        two is set per row (ck_submission_upload_exactly_one_target), so COUNT(DISTINCT ...)
        over both columns correctly counts distinct elements without colliding across the two
        id spaces.
        """
        element_key = (SubmissionUpload.event_id, SubmissionUpload.list_entry_id)

        submitted_stmt = (
            select(func.count(func.distinct(*element_key)))
            .where(SubmissionUpload.assignment_id == assignment_id)
        )
        submitted = db.scalar(submitted_stmt) or 0

        quarantine_stmt = (
            select(func.count(func.distinct(*element_key)))
            .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(SubmissionUpload.assignment_id == assignment_id, StoredFile.scan_status == "pending")
        )
        quarantine = db.scalar(quarantine_stmt) or 0

        infected_stmt = (
            select(func.count(func.distinct(*element_key)))
            .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(SubmissionUpload.assignment_id == assignment_id, StoredFile.scan_status == "infected")
        )
        infected = db.scalar(infected_stmt) or 0

        return {"submitted": submitted, "quarantine": quarantine, "infected": infected}

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
