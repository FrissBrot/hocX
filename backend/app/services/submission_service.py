from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from pathlib import Path

from app.core.config import settings
from app import scanner
from app.models import Event, Participant, ProtocolTodo, SubmissionAssignment, SubmissionUpload
from app.repositories.submission_repository import SubmissionRepository
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentRead,
    SubmissionAssignmentUpdate,
    SubmissionElementRead,
    SubmissionFileRead,
    SubmissionUploadLogEntry,
)
from app.services.file_service import _safe_storage_path


def _move_from_quarantine(quarantine_rel_path: str, storage_root: str) -> str:
    """Move a quarantined file to regular storage. Returns the new relative path."""
    q_full = Path(storage_root) / quarantine_rel_path
    # quarantine/tenant-1/assignment-2/abc.pdf -> tenant-1/assignment-2/abc.pdf
    parts = Path(quarantine_rel_path).parts
    new_rel = str(Path(*parts[1:]))
    new_full = Path(storage_root) / new_rel
    new_full.parent.mkdir(parents=True, exist_ok=True)
    q_full.rename(new_full)
    return new_rel


def _element_ref(*, event_id: int | None, list_entry_id: int | None) -> str:
    if event_id is not None:
        return f"event-{event_id}"
    return f"entry-{list_entry_id}"


def _resolve_event_responsible(event: Event, source: str | None) -> int | None:
    if not source:
        return None
    ids: list[int] = getattr(event, source, None) or []
    return ids[0] if len(ids) == 1 else None


def _resolve_list_responsible(entry: object, source: str | None) -> int | None:
    if not source:
        return None
    value_json: dict = (
        getattr(entry, "column_one_value_json", {}) if source == "column_one"
        else getattr(entry, "column_two_value_json", {})
    )
    pid = value_json.get("participant_id")
    return int(pid) if pid else None


def _parse_element_ref(element_ref: str) -> tuple[int | None, int | None]:
    kind, _, raw_id = element_ref.partition("-")
    if kind == "event" and raw_id.isdigit():
        return int(raw_id), None
    if kind == "entry" and raw_id.isdigit():
        return None, int(raw_id)
    raise ValueError("Ungueltige Element-Referenz")


def _value_label(
    value_type: str,
    value_json: dict,
    *,
    participants_by_id: dict[int, Participant],
    events_by_id: dict[int, Event],
) -> str:
    if value_type == "text":
        return str(value_json.get("text_value") or "—")
    if value_type == "participant":
        participant = participants_by_id.get(int(value_json.get("participant_id") or 0))
        return participant.display_name if participant else "—"
    if value_type == "participants":
        names = [
            participants_by_id[int(pid)].display_name
            for pid in value_json.get("participant_ids", [])
            if int(pid) in participants_by_id
        ]
        return ", ".join(names) if names else "—"
    if value_type == "event":
        event = events_by_id.get(int(value_json.get("event_id") or 0))
        return event.title if event else "—"
    return "—"


class SubmissionService:
    def __init__(self, repository: SubmissionRepository | None = None) -> None:
        self.repository = repository or SubmissionRepository()

    def _assignment_read(self, assignment: SubmissionAssignment) -> SubmissionAssignmentRead:
        return SubmissionAssignmentRead.model_validate(assignment)

    def list_assignments(self, db: Session, *, tenant_id: int) -> list[SubmissionAssignmentRead]:
        return [self._assignment_read(item) for item in self.repository.list_assignments(db, tenant_id=tenant_id)]

    def get_assignment(self, db: Session, assignment_id: int) -> SubmissionAssignment | None:
        return self.repository.get_assignment(db, assignment_id)

    def create_assignment(
        self, db: Session, payload: SubmissionAssignmentCreate, *, tenant_id: int
    ) -> SubmissionAssignmentRead:
        self._validate_source_fields(payload)
        entity = SubmissionAssignment(tenant_id=tenant_id, **payload.model_dump())
        created = self.repository.create_assignment(db, entity)
        return self._assignment_read(created)

    def update_assignment(
        self, db: Session, assignment_id: int, payload: SubmissionAssignmentUpdate
    ) -> SubmissionAssignmentRead | None:
        assignment = self.repository.get_assignment(db, assignment_id)
        if assignment is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return self._assignment_read(assignment)
        merged = {
            "source_type": values.get("source_type", assignment.source_type),
            "tag_filter": values.get("tag_filter", assignment.tag_filter),
            "offset_days_before": values.get("offset_days_before", assignment.offset_days_before),
            "offset_days_after": values.get("offset_days_after", assignment.offset_days_after),
            "list_definition_id": values.get("list_definition_id", assignment.list_definition_id),
            "deadline": values.get("deadline", assignment.deadline),
        }
        self._validate_source_fields_dict(merged)
        updated = self.repository.update_assignment(db, assignment, values)
        return self._assignment_read(updated)

    def delete_assignment(self, db: Session, assignment_id: int) -> bool:
        assignment = self.repository.get_assignment(db, assignment_id)
        if assignment is None:
            return False
        self.repository.delete_assignment(db, assignment)
        return True

    def _validate_source_fields(self, payload: SubmissionAssignmentCreate) -> None:
        self._validate_source_fields_dict(payload.model_dump())

    def _validate_source_fields_dict(self, values: dict) -> None:
        if values["source_type"] == "events":
            if not values.get("tag_filter") or values.get("offset_days_before") is None or values.get("offset_days_after") is None:
                raise ValueError("tag_filter, offset_days_before und offset_days_after sind fuer Termin-Abgaben erforderlich")
            if values.get("list_definition_id") is not None or values.get("deadline") is not None:
                raise ValueError("list_definition_id/deadline duerfen bei Termin-Abgaben nicht gesetzt sein")
        else:
            if values.get("list_definition_id") is None or values.get("deadline") is None:
                raise ValueError("list_definition_id und deadline sind fuer Listen-Abgaben erforderlich")
            if values.get("tag_filter") is not None or values.get("offset_days_before") is not None or values.get("offset_days_after") is not None:
                raise ValueError("tag_filter/offset_days_* duerfen bei Listen-Abgaben nicht gesetzt sein")

    def _resolve_raw_elements(self, db: Session, assignment: SubmissionAssignment) -> list[dict]:
        source = assignment.responsible_participant_source
        if assignment.source_type == "events":
            events = self.repository.list_events_by_tag(db, tenant_id=assignment.tenant_id, tag=assignment.tag_filter or "")
            return [
                {
                    "event_id": event.id,
                    "list_entry_id": None,
                    "label": event.title,
                    "window_start": event.event_date - timedelta(days=assignment.offset_days_before or 0),
                    "window_end": (event.event_end_date or event.event_date) + timedelta(days=assignment.offset_days_after or 0),
                    "responsible_participant_id": _resolve_event_responsible(event, source),
                }
                for event in events
            ]

        definition = self.repository.get_list_definition(db, assignment.list_definition_id) if assignment.list_definition_id else None
        if definition is None:
            return []
        entries = self.repository.list_list_entries(db, list_definition_id=definition.id)
        participant_ids: set[int] = set()
        event_ids: set[int] = set()
        for entry in entries:
            self._collect_referenced_ids(definition.column_one_value_type, entry.column_one_value_json, participant_ids, event_ids)
        participants_by_id = self.repository.get_participants(db, participant_ids=list(participant_ids))
        events_by_id = {eid: event for eid in event_ids if (event := self.repository.get_event(db, eid)) is not None}

        return [
            {
                "event_id": None,
                "list_entry_id": entry.id,
                "label": _value_label(
                    definition.column_one_value_type,
                    entry.column_one_value_json,
                    participants_by_id=participants_by_id,
                    events_by_id=events_by_id,
                ),
                "window_start": None,
                "window_end": assignment.deadline,
                "responsible_participant_id": _resolve_list_responsible(entry, source),
            }
            for entry in entries
        ]

    @staticmethod
    def _collect_referenced_ids(value_type: str, value_json: dict, participant_ids: set[int], event_ids: set[int]) -> None:
        if value_type == "participant" and value_json.get("participant_id"):
            participant_ids.add(int(value_json["participant_id"]))
        elif value_type == "participants":
            participant_ids.update(int(pid) for pid in value_json.get("participant_ids", []))
        elif value_type == "event" and value_json.get("event_id"):
            event_ids.add(int(value_json["event_id"]))

    def get_assignment_elements(self, db: Session, assignment: SubmissionAssignment) -> list[SubmissionElementRead]:
        raw_elements = self._resolve_raw_elements(db, assignment)
        uploads = self.repository.list_uploads_for_assignment(db, assignment_id=assignment.id)
        latest_by_key: dict[tuple[int | None, int | None], SubmissionUpload] = {}
        for upload in uploads:
            latest_by_key[(upload.event_id, upload.list_entry_id)] = upload

        results: list[SubmissionElementRead] = []
        for raw in raw_elements:
            key = (raw["event_id"], raw["list_entry_id"])
            latest = latest_by_key.get(key)
            files: list[SubmissionFileRead] = []
            status: str = "open"
            submitted_at: datetime | None = None
            upload_id: int | None = None
            if latest is not None:
                status = latest.status
                submitted_at = latest.submitted_at
                upload_id = latest.id
                if latest.status == "submitted":
                    files = [
                        SubmissionFileRead(
                            id=stored_file.id,
                            original_name=stored_file.original_name,
                            mime_type=stored_file.mime_type,
                            file_size_bytes=stored_file.file_size_bytes,
                            content_url=f"/api/submission-uploads/{latest.id}/files/{stored_file.id}/content",
                            scan_status=stored_file.scan_status,
                        )
                        for _upload_file, stored_file in self.repository.list_upload_files(db, upload_id=latest.id)
                    ]
            results.append(
                SubmissionElementRead(
                    element_ref=_element_ref(event_id=raw["event_id"], list_entry_id=raw["list_entry_id"]),
                    label=raw["label"],
                    window_start=raw["window_start"],
                    window_end=raw["window_end"],
                    status=status,
                    submitted_at=submitted_at,
                    upload_id=upload_id,
                    files=files,
                    responsible_participant_id=raw.get("responsible_participant_id"),
                )
            )
        return results

    def reopen_element(self, db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionElementRead:
        event_id, list_entry_id = _parse_element_ref(element_ref)
        uploads = self.repository.list_uploads_for_assignment(db, assignment_id=assignment.id)
        matching = [u for u in uploads if u.event_id == event_id and u.list_entry_id == list_entry_id]
        latest = matching[-1] if matching else None
        if latest is None or latest.status != "submitted":
            raise ValueError("Element wurde noch nicht abgegeben")

        for upload_file, stored_file in self.repository.list_upload_files(db, upload_id=latest.id):
            file_path = _safe_storage_path(settings.abgabebox_storage_root, stored_file.storage_path)
            if file_path.exists():
                file_path.unlink()
            self.repository.delete_upload_file(db, upload_file)
            self.repository.delete_stored_file(db, stored_file)

        self.repository.create_upload(
            db,
            SubmissionUpload(
                assignment_id=assignment.id,
                event_id=event_id,
                list_entry_id=list_entry_id,
                status="reopened",
                submitted_at=None,
            ),
        )
        elements = self.get_assignment_elements(db, assignment)
        target_ref = _element_ref(event_id=event_id, list_entry_id=list_entry_id)
        return next(element for element in elements if element.element_ref == target_ref)

    def sync_todos_for_event(self, db: Session, event: Event) -> None:
        if not event.tag:
            return
        assignments = self.repository.list_assignments(db, tenant_id=event.tenant_id)
        for assignment in assignments:
            if (
                assignment.source_type == "events"
                and assignment.tag_filter == event.tag
                and assignment.responsible_participant_source
            ):
                try:
                    self.sync_submission_todos(db, assignment)
                except Exception:
                    pass

    def sync_submission_todos(self, db: Session, assignment: SubmissionAssignment) -> dict:
        tenant = self.repository.get_tenant(db, assignment.tenant_id)
        tenant_slug = tenant.public_slug if tenant else None
        if not tenant_slug:
            raise ValueError("Tenant hat keine öffentliche URL-Kennung (public_slug)")

        raw_elements = self._resolve_raw_elements(db, assignment)
        existing = self.repository.list_todos_for_submission_assignment(db, assignment.id)
        todos_by_ref: dict[str, ProtocolTodo] = {t.element_ref: t for t in existing if t.element_ref}

        created = 0
        updated = 0

        for raw in raw_elements:
            participant_id = raw.get("responsible_participant_id")
            if not participant_id:
                continue
            element_ref = _element_ref(event_id=raw["event_id"], list_entry_id=raw["list_entry_id"])
            url = f"{settings.abgabebox_base_url}/{tenant_slug}/{assignment.public_slug}/{element_ref}"
            task = f"{assignment.title}: {raw['label']}"
            due_date = raw.get("window_end")

            existing_todo = todos_by_ref.get(element_ref)
            if existing_todo is not None:
                existing_todo.task = task
                existing_todo.assigned_participant_id = participant_id
                existing_todo.due_date = due_date
                existing_todo.reference_link = url
                db.add(existing_todo)
                updated += 1
            else:
                todo = ProtocolTodo(
                    tenant_id=assignment.tenant_id,
                    protocol_element_block_id=None,
                    sort_index=0,
                    task=task,
                    assigned_participant_id=participant_id,
                    todo_status_id=1,
                    due_date=due_date,
                    reference_link=url,
                    tags=[],
                    submission_assignment_id=assignment.id,
                    element_ref=element_ref,
                )
                db.add(todo)
                created += 1

        db.commit()
        return {"created": created, "updated": updated}

    def get_upload_log(self, db: Session, *, assignment_id: int, element_ref: str) -> list[SubmissionUploadLogEntry]:
        rows = self.repository.list_upload_log(db, assignment_id=assignment_id, element_ref=element_ref)
        return [SubmissionUploadLogEntry.model_validate(row) for row in rows]

    def rescan_pending(self, db: Session, assignment_id: int) -> dict:
        """Rescan all pending files for an assignment via ClamAV. Returns scan summary."""
        pending = self.repository.list_pending_files_for_assignment(db, assignment_id=assignment_id)
        results = {"scanned": len(pending), "clean": 0, "infected": 0, "still_pending": 0}
        for stored_file, element_ref in pending:
            file_path = _safe_storage_path(settings.abgabebox_storage_root, stored_file.storage_path)
            result = scanner.scan_file(file_path, host=settings.clamav_host, port=settings.clamav_port)
            if result == "clean":
                new_path = _move_from_quarantine(stored_file.storage_path, settings.abgabebox_storage_root)
                self.repository.update_stored_file_scan(db, stored_file, scan_status="clean", storage_path=new_path)
                self.repository.create_upload_log(db, assignment_id=assignment_id, element_ref=element_ref, status="rescan_clean")
                results["clean"] += 1
            elif result == "infected":
                self.repository.update_stored_file_scan(db, stored_file, scan_status="infected")
                self.repository.create_upload_log(db, assignment_id=assignment_id, element_ref=element_ref, status="rescan_infected", error_message=stored_file.original_name)
                results["infected"] += 1
            else:
                self.repository.create_upload_log(db, assignment_id=assignment_id, element_ref=element_ref, status="rescan_pending", error_message="ClamAV nicht erreichbar")
                results["still_pending"] += 1
        return results

    def get_stored_file_for_upload(self, db: Session, *, upload_id: int, stored_file_id: int):
        upload = self.repository.get_upload(db, upload_id)
        if upload is None:
            return None, None
        for upload_file, stored_file in self.repository.list_upload_files(db, upload_id=upload_id):
            if stored_file.id == stored_file_id:
                return upload, stored_file
        return upload, None
