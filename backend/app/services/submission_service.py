from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from pathlib import Path

from app.core.config import settings
from app import scanner
from app.models import Event, Participant, ProtocolTodo, SubmissionAssignment, SubmissionUpload, TenantDomain
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


def _abgabebox_base_url(db: Session, tenant_id: int) -> str:
    """Prefers the tenant's own verified Abgabebox domain, falls back to the shared default."""
    domain_row = (
        db.query(TenantDomain)
        .filter(TenantDomain.tenant_id == tenant_id, TenantDomain.purpose == "abgabebox", TenantDomain.status == "active")
        .one_or_none()
    )
    if domain_row is not None:
        return f"https://{domain_row.domain}"
    return settings.abgabebox_base_url


def _move_from_quarantine(quarantine_rel_path: str, storage_root: str) -> str:
    """Move a quarantined file to regular storage. Returns the new relative path."""
    q_full = _safe_storage_path(storage_root, quarantine_rel_path)
    # quarantine/tenant-1/assignment-2/abc.pdf -> tenant-1/assignment-2/abc.pdf
    parts = Path(quarantine_rel_path).parts
    if not parts or parts[0] != "quarantine":
        # Blindly dropping parts[0] on the (previously unchecked) assumption that it's
        # always "quarantine" silently moved the file to the wrong path - stripping a real
        # tenant-id/assignment-id segment instead - for any path that didn't start with it
        # (audit finding, 2026-08-25). Fail loudly instead.
        raise ValueError(f"Expected a quarantine-prefixed path, got {quarantine_rel_path!r}")
    new_rel = str(Path(*parts[1:]))
    new_full = _safe_storage_path(storage_root, new_rel)
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
        self._validate_list_definition_tenant(db, payload.list_definition_id, tenant_id=tenant_id)
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
        self._validate_list_definition_tenant(db, merged["list_definition_id"], tenant_id=assignment.tenant_id)
        updated = self.repository.update_assignment(db, assignment, values)
        return self._assignment_read(updated)

    def _validate_list_definition_tenant(self, db: Session, list_definition_id: int | None, *, tenant_id: int) -> None:
        # list_definition_id is client-supplied and only ever checked for existence, never
        # tenant ownership - without this, a writer could point a submission assignment at
        # another tenant's list, exposing its entries both in the admin UI and in the public
        # Abgabebox (audit finding, 2026-08-25).
        if list_definition_id is None:
            return
        definition = self.repository.get_list_definition(db, list_definition_id)
        if definition is None or definition.tenant_id != tenant_id:
            raise ValueError("list_definition_id not found")

    def delete_assignment(self, db: Session, assignment_id: int) -> bool:
        assignment = self.repository.get_assignment(db, assignment_id)
        if assignment is None:
            return False
        self.repository.delete_assignment(db, assignment)
        return True

    def _validate_source_fields(self, payload: SubmissionAssignmentCreate) -> None:
        self._validate_source_fields_dict(payload.model_dump())

    def _validate_source_fields_dict(self, values: dict) -> None:
        # offset_days_before/after (Termine) und deadline (Liste) sind bewusst optional: eine
        # Abgabe ohne diese Werte bleibt offen, bis sie manuell geschlossen wird (siehe
        # close_element/reopen_element), statt an ein festes Zeitfenster gebunden zu sein.
        if values["source_type"] == "events":
            if not values.get("tag_filter"):
                raise ValueError("tag_filter ist fuer Termin-Abgaben erforderlich")
            if values.get("list_definition_id") is not None or values.get("deadline") is not None:
                raise ValueError("list_definition_id/deadline duerfen bei Termin-Abgaben nicht gesetzt sein")
        else:
            if values.get("list_definition_id") is None:
                raise ValueError("list_definition_id ist fuer Listen-Abgaben erforderlich")
            if values.get("tag_filter") is not None or values.get("offset_days_before") is not None or values.get("offset_days_after") is not None:
                raise ValueError("tag_filter/offset_days_* duerfen bei Listen-Abgaben nicht gesetzt sein")

    def _resolve_raw_elements(self, db: Session, assignment: SubmissionAssignment) -> list[dict]:
        source = assignment.responsible_participant_source
        if assignment.source_type == "events":
            events = self.repository.list_events_by_tag(db, tenant_id=assignment.tenant_id, tag=assignment.tag_filter or "")
            raw = [
                {
                    "event_id": event.id,
                    "list_entry_id": None,
                    "label": event.title,
                    "sort_date": event.event_date,
                    # None (kein Offset gesetzt) = kein Zeitfenster auf dieser Seite - die
                    # Abgabe bleibt offen, bis sie manuell geschlossen wird.
                    "window_start": (
                        event.event_date - timedelta(days=assignment.offset_days_before)
                        if assignment.offset_days_before is not None else None
                    ),
                    "window_end": (
                        (event.event_end_date or event.event_date) + timedelta(days=assignment.offset_days_after)
                        if assignment.offset_days_after is not None else None
                    ),
                    "responsible_participant_id": _resolve_event_responsible(event, source),
                }
                for event in events
            ]
            return self._sort_raw_elements(raw, assignment.sort_order)

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

        raw = [
            {
                "event_id": None,
                "list_entry_id": entry.id,
                "label": _value_label(
                    definition.column_one_value_type,
                    entry.column_one_value_json,
                    participants_by_id=participants_by_id,
                    events_by_id=events_by_id,
                ),
                # Listen-Eintraege haben kein eigenes Datum - nur der (optionale) Stichtag der
                # ganzen Abgabe existiert, gleich fuer alle Eintraege. "date"/"proximity"-Sortierung
                # kann sie also nicht unterscheiden und faellt auf die urspruengliche Reihenfolge zurueck.
                "sort_date": None,
                "window_start": None,
                "window_end": assignment.deadline,
                "responsible_participant_id": _resolve_list_responsible(entry, source),
            }
            for entry in entries
        ]
        return self._sort_raw_elements(raw, assignment.sort_order)

    @staticmethod
    def _sort_raw_elements(raw: list[dict], sort_order: str) -> list[dict]:
        """Reihenfolge, in der Elemente sowohl im Admin-Bereich als auch (unveraendert
        uebernommen) in der oeffentlichen Abgabebox erscheinen - siehe sort_order auf
        SubmissionAssignment. Python's sort ist stabil, daher bleibt bei Gleichstand
        (z.B. "proximity" bei gleichem Datum, oder "date"/"proximity" bei Listen-Eintraegen
        ohne eigenes Datum) die urspruengliche Reihenfolge erhalten."""
        if sort_order == "alphabetical":
            return sorted(raw, key=lambda item: item["label"].lower())
        if sort_order == "proximity":
            today = date.today()
            return sorted(
                raw,
                key=lambda item: abs((item["sort_date"] - today).days) if item["sort_date"] is not None else float("inf"),
            )
        # "date" (Default): chronologisch, Elemente ohne eigenes Datum (Listen-Eintraege) zuletzt.
        return sorted(
            raw,
            key=lambda item: (item["sort_date"] is None, item["sort_date"] or date.min),
        )

    @staticmethod
    def _collect_referenced_ids(value_type: str, value_json: dict, participant_ids: set[int], event_ids: set[int]) -> None:
        if value_type == "participant" and value_json.get("participant_id"):
            participant_ids.add(int(value_json["participant_id"]))
        elif value_type == "participants":
            participant_ids.update(int(pid) for pid in value_json.get("participant_ids", []))
        elif value_type == "event" and value_json.get("event_id"):
            event_ids.add(int(value_json["event_id"]))

    def get_assignment_elements(self, db: Session, assignment: SubmissionAssignment) -> list[SubmissionElementRead]:
        """Abgaben sind kumulativ (siehe 2026-08-17 Umstellung): jede oeffentliche Einreichung
        legt eine neue SubmissionUpload-Zeile mit ihren eigenen Dateien an, statt eine
        vorherige zu ersetzen. Der sichtbare Zustand eines Elements ergibt sich daher aus ALLEN
        Zeilen dieses Elements, nicht nur der letzten:
        - status = 'closed', wenn die juengste Zeile status='closed' hat (explizit geschlossen,
          siehe close_element) - unabhaengig davon, ob vorher schon Dateien eingegangen sind.
        - sonst 'submitted', wenn irgendeine Zeile Dateien beigetragen hat (weiterhin offen fuer
          weitere Uploads).
        - sonst 'open' (noch nie etwas eingereicht).
        Dateien = Vereinigung aller Zeilen, mit dem tatsaechlichen Owner-Upload pro Datei (fuer
        content_url), nicht der Datei-Liste der juengsten Zeile allein.
        """
        raw_elements = self._resolve_raw_elements(db, assignment)
        uploads = self.repository.list_uploads_for_assignment(db, assignment_id=assignment.id)
        uploads_by_key: dict[tuple[int | None, int | None], list[SubmissionUpload]] = {}
        for upload in uploads:
            uploads_by_key.setdefault((upload.event_id, upload.list_entry_id), []).append(upload)

        results: list[SubmissionElementRead] = []
        for raw in raw_elements:
            key = (raw["event_id"], raw["list_entry_id"])
            element_uploads = uploads_by_key.get(key, [])

            files: list[SubmissionFileRead] = []
            submitted_at: datetime | None = None
            for upload in element_uploads:
                if upload.submitted_at is not None and (submitted_at is None or upload.submitted_at > submitted_at):
                    submitted_at = upload.submitted_at
                for _upload_file, stored_file in self.repository.list_upload_files(db, upload_id=upload.id):
                    files.append(
                        SubmissionFileRead(
                            id=stored_file.id,
                            original_name=stored_file.original_name,
                            mime_type=stored_file.mime_type,
                            file_size_bytes=stored_file.file_size_bytes,
                            content_url=f"/api/submission-uploads/{upload.id}/files/{stored_file.id}/content",
                            scan_status=stored_file.scan_status,
                        )
                    )

            if not element_uploads:
                status = "open"
            elif element_uploads[-1].status == "closed":
                status = "closed"
            elif files:
                status = "submitted"
            else:
                status = "open"

            results.append(
                SubmissionElementRead(
                    element_ref=_element_ref(event_id=raw["event_id"], list_entry_id=raw["list_entry_id"]),
                    label=raw["label"],
                    window_start=raw["window_start"],
                    window_end=raw["window_end"],
                    status=status,
                    submitted_at=submitted_at,
                    upload_id=element_uploads[-1].id if element_uploads else None,
                    files=files,
                    responsible_participant_id=raw.get("responsible_participant_id"),
                )
            )
        return results

    def _latest_upload_for_element(
        self, db: Session, assignment: SubmissionAssignment, element_ref: str
    ) -> tuple[int | None, int | None, SubmissionUpload | None]:
        event_id, list_entry_id = _parse_element_ref(element_ref)
        uploads = self.repository.list_uploads_for_assignment(db, assignment_id=assignment.id)
        matching = [u for u in uploads if u.event_id == event_id and u.list_entry_id == list_entry_id]
        return event_id, list_entry_id, (matching[-1] if matching else None)

    def close_element(self, db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionElementRead:
        """Schliesst ein Element manuell (keine weiteren Uploads mehr moeglich), unabhaengig
        davon, ob schon Dateien eingegangen sind - das Gegenstueck zu reopen_element, seit
        Abgaben ohne Tage-Fenster sonst unbegrenzt offen blieben."""
        event_id, list_entry_id, latest = self._latest_upload_for_element(db, assignment, element_ref)
        if latest is not None and latest.status == "closed":
            raise ValueError("Element ist bereits geschlossen")

        self.repository.create_upload(
            db,
            SubmissionUpload(
                assignment_id=assignment.id,
                event_id=event_id,
                list_entry_id=list_entry_id,
                status="closed",
                submitted_at=None,
            ),
        )
        elements = self.get_assignment_elements(db, assignment)
        target_ref = _element_ref(event_id=event_id, list_entry_id=list_entry_id)
        return next(element for element in elements if element.element_ref == target_ref)

    def reopen_element(self, db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionElementRead:
        """Hebt eine manuelle Schliessung wieder auf. Bereits eingereichte Dateien bleiben
        erhalten (kumulatives Modell) - anders als vor der 2026-08-17 Umstellung, als reopen
        die bisherigen Dateien geloescht hat."""
        event_id, list_entry_id, latest = self._latest_upload_for_element(db, assignment, element_ref)
        if latest is None or latest.status != "closed":
            raise ValueError("Element ist nicht geschlossen")

        self.repository.create_upload(
            db,
            SubmissionUpload(
                assignment_id=assignment.id,
                event_id=event_id,
                list_entry_id=list_entry_id,
                status="submitted",
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
        base_url = _abgabebox_base_url(db, assignment.tenant_id)

        for raw in raw_elements:
            participant_id = raw.get("responsible_participant_id")
            if not participant_id:
                continue
            element_ref = _element_ref(event_id=raw["event_id"], list_entry_id=raw["list_entry_id"])
            url = f"{base_url}/{tenant_slug}/{assignment.public_slug}/{element_ref}"
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
                try:
                    new_path = _move_from_quarantine(stored_file.storage_path, settings.abgabebox_storage_root)
                except ValueError:
                    # _move_from_quarantine now rejects a storage_path that doesn't
                    # actually start with "quarantine/" instead of silently mismoving it
                    # (audit finding, 2026-08-25) - caught here specifically so one
                    # malformed row can't abort the whole rescan batch for every other
                    # still-pending file behind it in this loop.
                    self.repository.create_upload_log(
                        db, assignment_id=assignment_id, element_ref=element_ref,
                        status="rescan_pending", error_message="Ungültiger Quarantäne-Pfad",
                    )
                    results["still_pending"] += 1
                    continue
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

    def rescan_all_pending(self, db: Session) -> dict:
        """Periodic sweep (see main.py's abgabebox_rescan_loop) so files that were stuck
        `pending` because ClamAV was briefly unreachable at upload time get picked up
        automatically instead of staying invisible until an admin clicks the manual per-
        assignment rescan button."""
        assignment_ids = self.repository.list_assignment_ids_with_pending_files(db)
        totals = {"assignments": len(assignment_ids), "scanned": 0, "clean": 0, "infected": 0, "still_pending": 0}
        for assignment_id in assignment_ids:
            result = self.rescan_pending(db, assignment_id)
            for key in ("scanned", "clean", "infected", "still_pending"):
                totals[key] += result[key]
        return totals

    def get_stored_file_for_upload(self, db: Session, *, upload_id: int, stored_file_id: int):
        upload = self.repository.get_upload(db, upload_id)
        if upload is None:
            return None, None
        for upload_file, stored_file in self.repository.list_upload_files(db, upload_id=upload_id):
            if stored_file.id == stored_file_id:
                return upload, stored_file
        return upload, None
