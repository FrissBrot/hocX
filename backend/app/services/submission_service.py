from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pathlib import Path

from app.core.config import settings
from app.core.error_log import record_system_error
from app.core.cycle_utils import cycle_years_for_offsets
from app import scanner
from app.core.features_generated import F
from app.models import CycleConfig, GalleryImage, Event, ListDefinition, ListEntry, Participant, ProtocolTodo, StoredFile, SubmissionAssignment, SubmissionUpload, TenantFeature, TodoStatus, ProtocolTodoFile
from app.repositories.submission_repository import MANUAL_ELEMENT_REF, SubmissionRepository
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentRead,
    SubmissionAssignmentUpdate,
    SubmissionElementRead,
    SubmissionFileRead,
    SubmissionUploadLogEntry,
)
from app.notifications import todos as todo_notifications
from app.services import public_id_service, submission_link_service, todo_fine_service
from app.services.task_package_service import set_todo_assignees, todo_assignee_ids
from app.core.storage import ABGABEBOX, ObjectNotFound, get_object_store, validate_key


def quarantine_target_key(quarantine_rel_path: str) -> str:
    """Pfad-Vertrag Quarantäne -> regulärer Speicher (geteilt mit abgabebox-backend, siehe
    tests/fixtures/quarantine_path_parity.json): das führende "quarantine"-Segment fällt weg."""
    validate_key(quarantine_rel_path)
    # quarantine/tenant-1/assignment-2/abc.pdf -> tenant-1/assignment-2/abc.pdf
    parts = Path(quarantine_rel_path).parts
    if not parts or parts[0] != "quarantine" or len(parts) < 2:
        # Blindly dropping parts[0] on the (previously unchecked) assumption that it's
        # always "quarantine" silently moved the file to the wrong path - stripping a real
        # tenant-id/assignment-id segment instead - for any path that didn't start with it
        # (audit finding, 2026-08-25). Fail loudly instead.
        raise ValueError(f"Expected a quarantine-prefixed path, got {quarantine_rel_path!r}")
    return validate_key(Path(*parts[1:]).as_posix())


def _move_from_quarantine(db: Session, quarantine_rel_path: str) -> str:
    """Move a quarantined file to regular storage (Namespace "abgabebox"). Returns the new key.
    Kopieren + Löschen über den Objektspeicher, beides im Journal der aufrufenden Transaktion."""
    new_rel = quarantine_target_key(quarantine_rel_path)
    get_object_store().move(db, ABGABEBOX, quarantine_rel_path, new_rel)
    return new_rel


def _element_ref(*, event_public_id: uuid.UUID | None, list_entry_public_id: uuid.UUID | None) -> str:
    if event_public_id is not None:
        return f"event-{event_public_id}"
    if list_entry_public_id is not None:
        return f"entry-{list_entry_public_id}"
    return MANUAL_ELEMENT_REF


def _resolve_event_responsible(event: Event, source: str | None) -> list[int]:
    """Alle Personen im Verantwortlichen-Feld des Termins (mehrere = gemeinsam verantwortlich)."""
    if not source:
        return []
    return list(dict.fromkeys(int(pid) for pid in (getattr(event, source, None) or []) if pid))


def _resolve_list_responsible(entry: object, source: str | None) -> list[int]:
    if not source:
        return []
    value_json: dict = (
        getattr(entry, "column_one_value_json", {}) if source == "column_one"
        else getattr(entry, "column_two_value_json", {})
    ) or {}
    ids = [value_json.get("participant_id")] + list(value_json.get("participant_ids") or [])
    return list(dict.fromkeys(int(pid) for pid in ids if pid))


def _parse_element_ref(db: Session, element_ref: str) -> tuple[int | None, int | None]:
    if element_ref == MANUAL_ELEMENT_REF:
        return None, None
    kind, _, raw_id = element_ref.partition("-")
    try:
        public_id = uuid.UUID(raw_id)
    except ValueError:
        raise ValueError("Ungueltige Element-Referenz") from None
    if kind == "event":
        internal_id = public_id_service.resolve_internal_id(db, Event, public_id)
        if internal_id is None:
            raise ValueError("Ungueltige Element-Referenz")
        return internal_id, None
    if kind == "entry":
        internal_id = public_id_service.resolve_internal_id(db, ListEntry, public_id)
        if internal_id is None:
            raise ValueError("Ungueltige Element-Referenz")
        return None, internal_id
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
        read = SubmissionAssignmentRead.model_validate(assignment)
        read.link_ids = [link.public_id for link in assignment.links]
        return read

    def list_assignments(self, db: Session, *, tenant_id: int) -> list[SubmissionAssignmentRead]:
        return [self._assignment_read(item) for item in self.repository.list_assignments(db, tenant_id=tenant_id)]

    def get_assignment(self, db: Session, assignment_id: int) -> SubmissionAssignment | None:
        return self.repository.get_assignment(db, assignment_id)

    def create_assignment(
        self, db: Session, payload: SubmissionAssignmentCreate, *, tenant_id: int
    ) -> SubmissionAssignmentRead:
        self._validate_source_fields(payload)
        list_definition_id = self._resolve_list_definition_tenant(db, payload.list_definition_id, tenant_id=tenant_id)
        values = payload.model_dump()
        link_ids = values.pop("link_ids")
        values["list_definition_id"] = list_definition_id
        values["cycle_config_id"] = self._resolve_cycle_config_tenant(db, payload.cycle_config_id, tenant_id=tenant_id)
        values["cycle_offsets"] = sorted(set(values["cycle_offsets"]), reverse=True)
        links = (
            submission_link_service.default_links(db, tenant_id)
            if link_ids is None
            else submission_link_service.resolve_links(db, link_ids, tenant_id=tenant_id)
        )
        entity = SubmissionAssignment(tenant_id=tenant_id, links=links, **values)
        created = self.repository.create_assignment(db, entity)
        self.sync_todos_if_tracked(db, created)
        return self._assignment_read(created)

    def update_assignment(
        self, db: Session, assignment_id: int, payload: SubmissionAssignmentUpdate
    ) -> SubmissionAssignmentRead | None:
        assignment = self.repository.get_assignment(db, assignment_id)
        if assignment is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        link_ids = values.pop("link_ids", None)
        if link_ids is not None:
            assignment.links = submission_link_service.resolve_links(db, link_ids, tenant_id=assignment.tenant_id)
        if not values:
            if link_ids is not None:
                db.add(assignment)
                db.commit()
                db.refresh(assignment)
                self.refresh_todo_links(db, assignment)
                self.sync_todos_if_tracked(db, assignment)
            return self._assignment_read(assignment)
        if "list_definition_id" in values:
            values["list_definition_id"] = self._resolve_list_definition_tenant(
                db, values["list_definition_id"], tenant_id=assignment.tenant_id
            )
        if "cycle_config_id" in values:
            values["cycle_config_id"] = self._resolve_cycle_config_tenant(
                db, values["cycle_config_id"], tenant_id=assignment.tenant_id
            )
        if values.get("cycle_offsets") is not None:
            values["cycle_offsets"] = sorted(set(values["cycle_offsets"]), reverse=True)
        merged = {
            "source_type": values.get("source_type", assignment.source_type),
            "tag_filter": values.get("tag_filter", assignment.tag_filter),
            "offset_days_before": values.get("offset_days_before", assignment.offset_days_before),
            "offset_days_after": values.get("offset_days_after", assignment.offset_days_after),
            "cycle_config_id": values.get("cycle_config_id", assignment.cycle_config_id),
            "cycle_offsets": values.get("cycle_offsets") if values.get("cycle_offsets") is not None else assignment.cycle_offsets,
            "list_definition_id": values.get("list_definition_id", assignment.list_definition_id),
            "deadline": values.get("deadline", assignment.deadline),
        }
        self._validate_source_fields_dict(merged)
        updated = self.repository.update_assignment(db, assignment, values)
        if link_ids is not None:
            self.refresh_todo_links(db, updated)
        self.sync_todos_if_tracked(db, updated)
        return self._assignment_read(updated)

    def _resolve_list_definition_tenant(self, db: Session, list_definition_public_id: uuid.UUID | None, *, tenant_id: int) -> int | None:
        # list_definition_id is client-supplied - without this, a writer could point a
        # submission assignment at another tenant's list, exposing its entries both in the
        # admin UI and in the public Abgabebox (audit finding, 2026-08-25). Resolving scoped
        # to tenant_id here is also the ownership check itself: a foreign id simply fails to
        # resolve.
        if list_definition_public_id is None:
            return None
        internal_id = public_id_service.resolve_internal_id(db, ListDefinition, list_definition_public_id, tenant_id=tenant_id)
        if internal_id is None:
            raise ValueError("list_definition_id not found")
        return internal_id

    def _resolve_cycle_config_tenant(self, db: Session, cycle_config_public_id: uuid.UUID | None, *, tenant_id: int) -> int | None:
        # Wie bei list_definition_id: client-geliefert, die tenant-gescopte Aufloesung ist zugleich
        # der Ownership-Check - eine fremde Zyklus-Konfiguration loest gar nicht erst auf.
        if cycle_config_public_id is None:
            return None
        internal_id = public_id_service.resolve_internal_id(db, CycleConfig, cycle_config_public_id, tenant_id=tenant_id)
        if internal_id is None:
            raise ValueError("cycle_config_id not found")
        return internal_id

    def list_assignment_events(self, db: Session, assignment: SubmissionAssignment) -> list[Event]:
        """Termine einer Termin-Abgabe: Tag-Filter, optional eingeschraenkt auf die Zyklen
        (cycle_config + cycle_offsets relativ zum heutigen Zyklus)."""
        cycle_years: set[int] | None = None
        if assignment.cycle_config_id is not None:
            config = self.repository.get_cycle_config(db, assignment.cycle_config_id)
            cycle_years = (
                cycle_years_for_offsets(date.today(), config.reset_month, config.reset_day, assignment.cycle_offsets)
                if config is not None else set()
            )
        return self.repository.list_events_by_tag(
            db,
            tenant_id=assignment.tenant_id,
            tag=assignment.tag_filter or "",
            cycle_config_id=assignment.cycle_config_id,
            cycle_years=cycle_years,
        )

    def delete_assignment(self, db: Session, assignment_id: int) -> bool:
        """Löscht die Abgabe samt aller eingereichten Dateien (deletion_service, PRIV-003)."""
        from app.services import deletion_service

        assignment = self.repository.get_assignment(db, assignment_id)
        if assignment is None:
            return False
        deletion_service.delete_assignment(db, assignment, delete_file_ids=None, actor_user_id=None)
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
            # Zyklus-Filter: Konfiguration und Zyklen gehoeren zusammen (ohne beides = alle Termine).
            if (values.get("cycle_config_id") is None) != (not values.get("cycle_offsets")):
                raise ValueError("cycle_config_id und cycle_offsets muessen zusammen gesetzt sein")
        elif values["source_type"] == "manual":
            if (
                values.get("tag_filter") is not None
                or values.get("list_definition_id") is not None
                or values.get("offset_days_before") is not None
                or values.get("offset_days_after") is not None
            ):
                raise ValueError("tag_filter/list_definition_id/offset_days_* duerfen bei manuellen Abgaben nicht gesetzt sein")
            if values.get("cycle_config_id") is not None or values.get("cycle_offsets"):
                raise ValueError("cycle_config_id/cycle_offsets duerfen bei manuellen Abgaben nicht gesetzt sein")
        else:
            if values.get("list_definition_id") is None:
                raise ValueError("list_definition_id ist fuer Listen-Abgaben erforderlich")
            if values.get("tag_filter") is not None or values.get("offset_days_before") is not None or values.get("offset_days_after") is not None:
                raise ValueError("tag_filter/offset_days_* duerfen bei Listen-Abgaben nicht gesetzt sein")
            if values.get("cycle_config_id") is not None or values.get("cycle_offsets"):
                raise ValueError("cycle_config_id/cycle_offsets duerfen bei Listen-Abgaben nicht gesetzt sein")

    def _resolve_raw_elements(self, db: Session, assignment: SubmissionAssignment) -> list[dict]:
        source = assignment.responsible_participant_source
        if assignment.source_type == "events":
            events = self.list_assignment_events(db, assignment)
            raw = [
                {
                    "event_id": event.id,
                    "event_public_id": event.public_id,
                    "list_entry_id": None,
                    "list_entry_public_id": None,
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
                    "responsible_participant_ids": _resolve_event_responsible(event, source),
                }
                for event in events
            ]
            return self._sort_raw_elements(raw, assignment.sort_order)

        if assignment.source_type == "manual":
            # Genau ein Element: die Abgabe selbst. Kein Event/Listen-Eintrag dahinter,
            # daher event_id = list_entry_id = None (siehe Migration 0080).
            return [
                {
                    "event_id": None,
                    "event_public_id": None,
                    "list_entry_id": None,
                    "list_entry_public_id": None,
                    "label": assignment.title,
                    "sort_date": None,
                    "window_start": None,
                    "window_end": assignment.deadline,
                    "responsible_participant_ids": [],
                }
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

        raw = [
            {
                "event_id": None,
                "event_public_id": None,
                "list_entry_id": entry.id,
                "list_entry_public_id": entry.public_id,
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
                "responsible_participant_ids": _resolve_list_responsible(entry, source),
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
        Verknuepfte Direkt-Uploads zaehlen ebenfalls als eingereichte Dateien; ihr
        Download bleibt beim internen Dateispeicher.
        Dateien = Vereinigung aller Zeilen, mit dem tatsaechlichen Owner-Upload pro Datei (fuer
        content_url), nicht der Datei-Liste der juengsten Zeile allein.
        """
        raw_elements = self._resolve_raw_elements(db, assignment)
        uploads = self.repository.list_uploads_for_assignment(db, assignment_id=assignment.id)
        uploads_by_key: dict[tuple[int | None, int | None], list[SubmissionUpload]] = {}
        for upload in uploads:
            uploads_by_key.setdefault((upload.event_id, upload.list_entry_id), []).append(upload)

        linked_files: dict[str, list[StoredFile]] = {}
        for gallery_image, stored_file in db.execute(
            select(GalleryImage, StoredFile)
            .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
            .where(
                GalleryImage.tenant_id == assignment.tenant_id,
                StoredFile.tenant_id == assignment.tenant_id,
                GalleryImage.submission_assignment_id == assignment.id,
            )
            .order_by(GalleryImage.id)
        ):
            linked_files.setdefault(gallery_image.submission_element_ref, []).append(stored_file)

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
                            id=stored_file.public_id,
                            original_name=stored_file.original_name,
                            mime_type=stored_file.mime_type,
                            file_size_bytes=stored_file.file_size_bytes,
                            content_url=f"/api/submission-uploads/{upload.public_id}/files/{stored_file.public_id}/content",
                            scan_status=stored_file.scan_status,
                        )
                    )

            element_ref = _element_ref(
                event_public_id=raw["event_public_id"], list_entry_public_id=raw["list_entry_public_id"]
            )
            known_file_ids = {file.id for file in files}
            for stored_file in linked_files.get(element_ref, []):
                if stored_file.public_id in known_file_ids:
                    continue
                known_file_ids.add(stored_file.public_id)
                files.append(SubmissionFileRead(
                    id=stored_file.public_id,
                    original_name=stored_file.original_name,
                    mime_type=stored_file.mime_type,
                    file_size_bytes=stored_file.file_size_bytes,
                    content_url=f"/api/stored-files/{stored_file.public_id}/content",
                    scan_status=stored_file.scan_status,
                ))
                if submitted_at is None or stored_file.created_at > submitted_at:
                    submitted_at = stored_file.created_at

            if element_uploads and element_uploads[-1].status == "closed":
                status = "closed"
            elif files:
                status = "submitted"
            else:
                status = "open"

            responsible_ids = raw.get("responsible_participant_ids") or []
            mapping = public_id_service.resolve_public_ids(db, Participant, responsible_ids) if responsible_ids else {}
            responsible_public_ids = [mapping[pid] for pid in responsible_ids if pid in mapping]
            results.append(
                SubmissionElementRead(
                    element_ref=element_ref,
                    label=raw["label"],
                    window_start=raw["window_start"],
                    window_end=raw["window_end"],
                    status=status,
                    submitted_at=submitted_at,
                    upload_id=element_uploads[-1].public_id if element_uploads else None,
                    files=files,
                    responsible_participant_id=responsible_public_ids[0] if responsible_public_ids else None,
                    responsible_participant_ids=responsible_public_ids,
                )
            )
        return results

    def _latest_upload_for_element(
        self, db: Session, assignment: SubmissionAssignment, element_ref: str
    ) -> tuple[int | None, int | None, SubmissionUpload | None]:
        event_id, list_entry_id = _parse_element_ref(db, element_ref)
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
        return next(element for element in elements if element.element_ref == element_ref)

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
        return next(element for element in elements if element.element_ref == element_ref)

    def sync_todos_for_event(self, db: Session, event: Event) -> None:
        """Nach Anlegen/Ändern eines Termins. Gleicht alle Abgaben des Mandanten ab, nicht nur
        die mit dem neuen Tag: bei einem Tag-Wechsel muss auch die Abgabe des alten Tags ihre
        Pendenz verlieren, und Listen-Abgaben zeigen Termintitel."""
        self.sync_todos_for_tenant(db, tenant_id=event.tenant_id)

    def sync_todos_for_list(self, db: Session, *, tenant_id: int, list_definition_id: int) -> None:
        """Nach Änderungen an Einträgen einer Liste: Todos der Listen-Abgaben nachführen, die
        diese Liste als Quelle haben (Verantwortliche je Eintrag)."""
        for assignment in self.repository.list_assignments(db, tenant_id=tenant_id):
            if assignment.source_type == "list" and assignment.list_definition_id == list_definition_id:
                self.sync_todos_if_tracked(db, assignment)

    def sync_todos_for_tenant(self, db: Session, *, tenant_id: int) -> None:
        """Alle Abgaben eines Mandanten abgleichen - nach Änderungen, die mehrere Abgaben treffen
        können (Termin gelöscht, Tag umbenannt, Import)."""
        for assignment in self.repository.list_assignments(db, tenant_id=tenant_id):
            if assignment.source_type != "manual":
                self.sync_todos_if_tracked(db, assignment)

    def sync_all_todos(self, db: Session) -> dict[str, int]:
        """Job submission_todo_sync: gleicht alle Abgaben aller Mandanten mit gebuchter Abgabebox
        ab. Fängt auf, was kein direkter Auslöser abdeckt (Zykluswechsel, verknüpfte Dateien aus
        dem Upload-Import, Änderungen an Wegen ohne eigenen Abgleich). Idempotent."""
        booked = select(TenantFeature.tenant_id).where(
            TenantFeature.feature_code == F.ABGABEBOX, TenantFeature.access == "full"
        )
        rows = db.execute(
            select(SubmissionAssignment.id, SubmissionAssignment.tenant_id)
            .where(SubmissionAssignment.tenant_id.in_(booked), SubmissionAssignment.source_type != "manual")
            .order_by(SubmissionAssignment.id)
        ).all()
        synced = failed = 0
        for assignment_id, tenant_id in rows:
            assignment = db.get(SubmissionAssignment, assignment_id)
            if assignment is None:
                continue
            if self.sync_todos_if_tracked(db, assignment):
                synced += 1
            else:
                failed += 1
        if failed:
            raise RuntimeError(f"{failed} Abgabe(n) konnten nicht abgeglichen werden")
        return {"assignments": synced}

    def sync_todos_if_tracked(self, db: Session, assignment: SubmissionAssignment) -> bool:
        """Automatischer Todo-Abgleich (FAR-010): nach Anlegen/Ändern einer Abgabe, eines
        Termins oder eines Listeneintrags und periodisch im Job submission_todo_sync.

        Ohne erreichbaren Link gibt es nichts abzugleichen (erwarteter Zustand, kein Fehler).
        Ein unerwarteter Fehler bricht die auslösende Änderung nicht ab, landet aber im
        Fehlerprotokoll. Rückgabe False nur bei einem solchen Fehler."""
        if submission_link_service.preferred_link(assignment) is None:
            return True
        tenant_id = assignment.tenant_id
        try:
            self.sync_submission_todos(db, assignment)
        except Exception as exc:
            # Nur ein Datenbankfehler hinterlässt eine abgebrochene Transaktion; alles andere
            # lässt die bereits committete auslösende Änderung unberührt.
            if isinstance(exc, SQLAlchemyError):
                db.rollback()
            record_system_error(db, exc=exc, tenant_id=tenant_id)
            return False
        return True

    def sync_submission_todos(self, db: Session, assignment: SubmissionAssignment) -> dict:
        """Eine Pendenz je Element mit Verantwortlicher Person; Titel, Person, Frist und Link
        folgen dem Element. Hat das Element schon Dateien, ist die Pendenz erledigt (auch bei
        direkt verknüpften Dateien, die den Datenbank-Trigger nicht auslösen).

        Offene Pendenzen, deren Element weggefallen ist (Termin gelöscht, Tag oder Zyklus
        gewechselt, Verantwortliche entfernt, Abgabe ohne Verantwortlichen-Quelle), werden
        gelöscht. Erledigte bleiben als Verlauf stehen."""
        link = submission_link_service.preferred_link(assignment)
        if link is None:
            raise ValueError("Die Abgabe ist über keinen Link erreichbar – bitte zuerst einen Link auswählen")

        raw_elements = self._resolve_raw_elements(db, assignment) if assignment.responsible_participant_source else []
        states = (
            {element.element_ref: element for element in self.get_assignment_elements(db, assignment)}
            if raw_elements else {}
        )
        existing = self.repository.list_todos_for_submission_assignment(db, assignment.id)
        todos_by_ref: dict[str, ProtocolTodo] = {t.element_ref: t for t in existing if t.element_ref}
        statuses = dict(db.execute(select(TodoStatus.code, TodoStatus.id)).all())
        open_id, done_id = statuses.get("open", 1), statuses.get("done", 3)
        cancelled_id = statuses.get("cancelled", done_id)
        closed_ids = {statuses[code] for code in ("done", "cancelled") if code in statuses}

        created = updated = removed = 0
        base_url = submission_link_service.abgabebox_base_url(db, assignment.tenant_id)
        current_refs: set[str] = set()

        for raw in raw_elements:
            participant_ids = raw.get("responsible_participant_ids") or []
            if not participant_ids:
                continue
            element_ref = _element_ref(event_public_id=raw["event_public_id"], list_entry_public_id=raw["list_entry_public_id"])
            current_refs.add(element_ref)
            url = f"{submission_link_service.link_url(base_url, link)}/{assignment.public_slug}/{element_ref}"
            task = f"{assignment.title}: {raw['label']}"
            due_date = raw.get("window_end")
            state = states.get(element_ref)
            # Nur geprüfte Dateien erledigen die Pendenz; Quarantäne/Scanfehler nicht (der Job
            # holt das nach, sobald der Scan sauber ist)
            has_files = bool(state and any(file.scan_status == "clean" for file in state.files))

            todo = todos_by_ref.get(element_ref)
            if todo is None:
                todo = ProtocolTodo(
                    tenant_id=assignment.tenant_id,
                    protocol_element_block_id=None,
                    sort_index=0,
                    task=task,
                    assigned_participant_id=participant_ids[0],
                    todo_status_id=open_id,
                    due_date=due_date,
                    reference_link=url,
                    tags=[],
                    submission_assignment_id=assignment.id,
                    element_ref=element_ref,
                )
                db.add(todo)
                db.flush()
                created += 1
            else:
                updated += 1
            todo.task = task
            todo.due_date = due_date
            todo.reference_link = url
            # Alle Verantwortlichen des Elements (mehrere = gemeinsam). Die Anzeige liest
            # protocol_todo_assignee vor assigned_participant_id, daher immer beide nachführen.
            if (previous := todo_assignee_ids(db, todo.id)) != participant_ids or todo.assigned_participant_id != participant_ids[0]:
                set_todo_assignees(db, todo, participant_ids)
                # Abgabe-Aufgaben haben kein Protokoll: neu Verantwortliche sofort (gebündelt) melden
                todo_notifications.on_assignees_added(db, todo, [pid for pid in participant_ids if pid not in previous])
            if has_files and todo.todo_status_id not in closed_ids:
                todo.todo_status_id = done_id
                todo.completed_at = state.submitted_at or datetime.now(UTC)
                db.add(todo)
                db.flush()
                # Zu spät abgegeben: Pendenzen-Busse einfrieren (todo_fine_service).
                todo_fine_service.sync_todo(db, todo)
            db.add(todo)

        for element_ref, todo in todos_by_ref.items():
            if element_ref not in current_refs and todo.todo_status_id not in closed_ids:
                # Von Hand ergänzte Pendenzen (Notizen, Dateien) nicht löschen, nur abbrechen -
                # fällt das Element nur kurz weg, bleibt die Arbeit erhalten
                has_details = (todo.notes or "").strip() or db.scalar(
                    select(ProtocolTodoFile.protocol_todo_id).where(ProtocolTodoFile.protocol_todo_id == todo.id).limit(1)
                )
                if has_details:
                    todo.todo_status_id = cancelled_id
                    db.add(todo)
                else:
                    db.delete(todo)
                removed += 1

        db.commit()
        return {"created": created, "updated": updated, "removed": removed}

    def refresh_todo_links(self, db: Session, assignment: SubmissionAssignment) -> None:
        """Points the reference_link of the Abgabe's existing todos at the current preferred
        link - called whenever the set of links (or a link's token) changes, so todos never
        keep a dead URL. Unlike sync_submission_todos this never creates todos. No link left
        = no reachable URL, so the reference is cleared."""
        link = submission_link_service.preferred_link(assignment)
        base_url = submission_link_service.abgabebox_base_url(db, assignment.tenant_id)
        for todo in self.repository.list_todos_for_submission_assignment(db, assignment.id):
            if not todo.element_ref:
                continue
            todo.reference_link = (
                f"{submission_link_service.link_url(base_url, link)}/{assignment.public_slug}/{todo.element_ref}"
                if link is not None
                else None
            )
            db.add(todo)
        db.commit()

    def get_upload_log(self, db: Session, *, assignment_id: int, element_ref: str) -> list[SubmissionUploadLogEntry]:
        rows = self.repository.list_upload_log(db, assignment_id=assignment_id, element_ref=element_ref)
        return [SubmissionUploadLogEntry.model_validate(row) for row in rows]

    def rescan_pending(self, db: Session, assignment_id: int) -> dict:
        """Rescan all pending files for an assignment via ClamAV. Returns scan summary."""
        pending = self.repository.list_pending_files_for_assignment(db, assignment_id=assignment_id)
        results = {"scanned": len(pending), "clean": 0, "infected": 0, "still_pending": 0}
        for stored_file, element_ref in pending:
            try:
                with get_object_store().local_copy(ABGABEBOX, stored_file.storage_path) as file_path:
                    result = scanner.scan_file(file_path, host=settings.clamav_host, port=settings.clamav_port)
            except ObjectNotFound:
                result = "error"
            if result == "clean":
                try:
                    new_path = _move_from_quarantine(db, stored_file.storage_path)
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
            elif result == "error":
                self.repository.update_stored_file_scan(db, stored_file, scan_status="error")
                self.repository.create_upload_log(db, assignment_id=assignment_id, element_ref=element_ref, status="scan_error", error_message="Datei konnte nicht geprüft werden")
                results["still_pending"] += 1
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
