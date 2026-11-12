from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    CycleConfig,
    Event,
    EventCycle,
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

# element_ref des einzigen Elements einer manuellen Abgabe (weder Termin noch Listen-Eintrag).
MANUAL_ELEMENT_REF = "manual"


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

    def get_cycle_config(self, db: Session, cycle_config_id: int) -> CycleConfig | None:
        return db.get(CycleConfig, cycle_config_id)

    def list_events_by_tag(
        self,
        db: Session,
        *,
        tenant_id: int,
        tag: str,
        cycle_config_id: int | None = None,
        cycle_years: set[int] | None = None,
    ) -> list[Event]:
        statement = select(Event).where(Event.tenant_id == tenant_id, Event.tag == tag)
        if cycle_config_id is not None:
            statement = statement.where(
                Event.id.in_(
                    select(EventCycle.event_id).where(
                        EventCycle.cycle_config_id == cycle_config_id,
                        EventCycle.cycle_year.in_(cycle_years or set()),
                    )
                )
            )
        return list(db.scalars(statement.order_by(Event.event_date.asc(), Event.id.asc())))

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

    def list_files_for_uploads(self, db: Session, *, upload_ids: list[int]) -> dict[int, list[StoredFile]]:
        """Dateien mehrerer Einreichungen in einer Abfrage (statt list_upload_files je Zeile)."""
        if not upload_ids:
            return {}
        files: dict[int, list[StoredFile]] = {}
        for upload_id, stored_file in db.execute(
            select(SubmissionUploadFile.upload_id, StoredFile)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(SubmissionUploadFile.upload_id.in_(upload_ids))
            .order_by(SubmissionUploadFile.upload_id, SubmissionUploadFile.sort_index.asc())
        ):
            files.setdefault(upload_id, []).append(stored_file)
        return files

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
        # Lazy: document_service -> app.core.storage; Repositories bleiben sonst importfrei.
        from app.services import document_service

        document_service.release_original(db, stored_file.id)
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
        """Return (stored_file, element_ref) for all pending files of an assignment. Die Referenz
        trägt wie überall die öffentliche ID (``event-<public_id>``), sonst fänden die Einträge des
        Upload-Logs ihr Element nicht."""
        statement = (
            select(StoredFile, Event.public_id.label("event_public_id"), ListEntry.public_id.label("entry_public_id"))
            .join(SubmissionUploadFile, SubmissionUploadFile.stored_file_id == StoredFile.id)
            .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
            .outerjoin(Event, Event.id == SubmissionUpload.event_id)
            .outerjoin(ListEntry, ListEntry.id == SubmissionUpload.list_entry_id)
            .where(
                SubmissionUpload.assignment_id == assignment_id,
                StoredFile.scan_status == "pending",
            )
        )
        result = []
        for row in db.execute(statement):
            if row.event_public_id is not None:
                element_ref = f"event-{row.event_public_id}"
            elif row.entry_public_id is not None:
                element_ref = f"entry-{row.entry_public_id}"
            else:
                element_ref = MANUAL_ELEMENT_REF
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

    def element_states(self, db: Session, *, assignment_ids: list[int]) -> dict[int, dict[str, dict]]:
        """Zustand je Element für mehrere Abgaben in drei Abfragen (Fortschritt der Abgaben-Liste):
        {assignment_id: {element_ref: {"scan": {scan_status, ...}, "latest": status der jüngsten Zeile}}}.
        Umfasst Einreichungen der Abgabebox und in der App verknüpfte Dateien."""
        if not assignment_ids:
            return {}
        states: dict[int, dict[str, dict]] = {}

        def entry(assignment_id: int, ref: str) -> dict:
            return states.setdefault(assignment_id, {}).setdefault(ref, {"scan": set(), "latest": None})

        def ref_of(event_id, entry_id) -> str:
            return f"event-{event_id}" if event_id else f"entry-{entry_id}" if entry_id else "manual"

        for assignment_id, event_id, entry_id, status in db.execute(
            select(SubmissionUpload.assignment_id, Event.public_id, ListEntry.public_id, StoredFile.scan_status)
            .select_from(SubmissionUpload)
            .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .outerjoin(Event, Event.id == SubmissionUpload.event_id)
            .outerjoin(ListEntry, ListEntry.id == SubmissionUpload.list_entry_id)
            .where(SubmissionUpload.assignment_id.in_(assignment_ids))
        ):
            entry(assignment_id, ref_of(event_id, entry_id))["scan"].add(status)
        for assignment_id, ref, status in db.execute(
            select(GalleryImage.submission_assignment_id, GalleryImage.submission_element_ref, StoredFile.scan_status)
            .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
            .join(SubmissionAssignment, SubmissionAssignment.id == GalleryImage.submission_assignment_id)
            .where(
                GalleryImage.submission_assignment_id.in_(assignment_ids),
                GalleryImage.tenant_id == SubmissionAssignment.tenant_id,
                StoredFile.tenant_id == SubmissionAssignment.tenant_id,
            )
        ):
            if ref:
                entry(assignment_id, ref)["scan"].add(status)
        # Von Hand geschlossen: jüngste Zeile des Elements ist «closed» (siehe get_assignment_elements)
        for assignment_id, event_id, entry_id, status in db.execute(
            select(SubmissionUpload.assignment_id, Event.public_id, ListEntry.public_id, SubmissionUpload.status)
            .select_from(SubmissionUpload)
            .outerjoin(Event, Event.id == SubmissionUpload.event_id)
            .outerjoin(ListEntry, ListEntry.id == SubmissionUpload.list_entry_id)
            .where(SubmissionUpload.assignment_id.in_(assignment_ids))
            .order_by(SubmissionUpload.id)
        ):
            entry(assignment_id, ref_of(event_id, entry_id))["latest"] = status
        return states

    @staticmethod
    def summarize_states(states: dict[str, dict], element_refs: list[str]) -> dict:
        """Fortschritt einer Abgabe. Jedes Element zählt genau einmal, in der ersten passenden
        Gruppe: geprüfte Datei → Quarantäne (im Scan oder Scanfehler) → nur infiziert → von Hand
        geschlossen → offen. Nur Elemente, die heute zur Abgabe gehören (gelöschte Termine,
        andere Zyklen fallen weg), daher nie mehr als `total`."""
        counts = {"submitted": 0, "quarantine": 0, "infected": 0, "closed": 0}
        for ref in element_refs:
            state = states.get(ref)
            if state is None:
                continue
            scan = state["scan"]
            if "clean" in scan:
                counts["submitted"] += 1
            elif scan & {"pending", "error"}:
                counts["quarantine"] += 1
            elif "infected" in scan:
                counts["infected"] += 1
            elif state["latest"] == "closed":
                counts["closed"] += 1
        return {**counts, "total": len(element_refs)}

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
