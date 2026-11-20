from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pathlib import Path

from app.core.config import settings
from app.core.error_log import record_system_error
from app.core.cycle_utils import cycle_years_for_offsets
from app.core.trash_scope import not_trashed_id
from app import scanner
from app.core.features_generated import F
from app.models import CycleConfig, GalleryImage, Event, ListDefinition, ListEntry, Participant, ProtocolTodo, StoredFile, SubmissionAssignment, SubmissionManualElement, SubmissionUpload, SubmissionUploadFile, TenantFeature, TodoStatus, ProtocolTodoFile
from app.repositories.submission_repository import MANUAL_ELEMENT_REF, SubmissionRepository, manual_element_ref
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentRead,
    SubmissionAssignmentUpdate,
    SubmissionElementRead,
    SubmissionFileRead,
    SubmissionManualElementRead,
    SubmissionManualElementWrite,
    SubmissionUploadLogEntry,
)
from app.notifications import todos as todo_notifications
from app.services import list_columns, public_id_service, submission_link_service, todo_fine_service
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



# Gemeinsam mit abgabebox-backend/app/repository.py (SUBMISSION_ELEMENT_LOCK_NAMESPACE): Schliessen
# von Hand und das Speichern einer Einreichung laufen je Abgabe nacheinander, damit ein Upload, der
# gerade läuft, ein eben geschlossenes Element nicht wieder öffnet.
SUBMISSION_ELEMENT_LOCK_NAMESPACE = 909100002


def submission_todo_tags(assignment: SubmissionAssignment) -> list[str]:
    """Tags, die jede Pendenz der Abgabe bekommt (Migration 0202): die gewählten Tags und, mit
    «Abgabe-Tag erstellen», ein eigenes Tag mit dem Titel der Abgabe."""
    from app.schemas.submission import clean_todo_tags

    tags = list(assignment.todo_tags or [])
    if assignment.todo_own_tag and (assignment.title or "").strip():
        tags.append(assignment.title)
    return clean_todo_tags(tags)


def merge_submission_todo_tags(current: list[str], *, previous: list[str], wanted: list[str]) -> list[str]:
    """Tags einer Pendenz nach dem Abgleich: vorher von der Abgabe vorgegebene, nicht mehr gewollte
    Tags fallen weg, gewollte kommen dazu; von Hand gesetzte bleiben, Reihenfolge bleibt."""
    wanted_lower = {tag.lower() for tag in wanted}
    dropped = {tag.lower() for tag in previous} - wanted_lower
    result = [tag for tag in (current or []) if str(tag).lower() not in dropped]
    present = {str(tag).lower() for tag in result}
    result += [tag for tag in wanted if tag.lower() not in present]
    return result


def window_expired(element: SubmissionElementRead, assignment: SubmissionAssignment, today: date) -> bool:
    """Element automatisch zu: Fenster bzw. Stichtag vorbei und die Abgabe hält es danach nicht
    offen (``keep_open_after_end``, Migration 0173). Gleiche Regel wie die Abgabebox
    (abgabebox-backend element_resolver: ``today > deadline and not keep_open``)."""
    return element.window_end is not None and element.window_end < today and not assignment.keep_open_after_end


def local_today() -> date:
    """Heute in Schweizer Zeit wie die Abgabebox (element_resolver) und die Bussen; der Container
    läuft in UTC, sonst öffnen und schliessen Zeitfenster nachts bis zu zwei Stunden zu spät."""
    return todo_fine_service.today()


def lock_submission_element(db: Session, assignment_id: int) -> None:
    """Transaktions-Lock je Abgabe (wird mit Commit/Rollback frei)."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :assignment_id)"),
        {"ns": SUBMISSION_ELEMENT_LOCK_NAMESPACE, "assignment_id": assignment_id},
    )


def element_has_clean_files(element: SubmissionElementRead) -> bool:
    """Einheitliche Regel für «abgegeben»: mindestens eine sauber geprüfte Datei. Dateien im
    Virenscan, mit Scanfehler oder infizierte zählen nicht."""
    return any(file.scan_status == "clean" for file in element.files)


def _shift_date(day: date, days: int) -> date:
    """Datum ± Tage, an date.min/date.max geklemmt: Altbestände mit riesigem Offset (vor der
    Schema-Grenze OFFSET_DAYS_MAX) liefen sonst in einen OverflowError, und die Abgabe glich nie
    mehr ab."""
    try:
        return day + timedelta(days=days)
    except OverflowError:
        return date.max if days > 0 else date.min


def _element_ref(*, event_public_id: uuid.UUID | None, list_entry_public_id: uuid.UUID | None) -> str:
    if event_public_id is not None:
        return f"event-{event_public_id}"
    if list_entry_public_id is not None:
        return f"entry-{list_entry_public_id}"
    return MANUAL_ELEMENT_REF


def raw_element_ref(raw: dict) -> str:
    """element_ref eines Elements aus _resolve_raw_elements (Elemente einer Einzelabgabe tragen ihre
    Referenz selbst, Migration 0198)."""
    return raw.get("element_ref") or _element_ref(event_public_id=raw["event_public_id"], list_entry_public_id=raw["list_entry_public_id"])


ElementKey = tuple[int | None, int | None, int | None]


def raw_element_key(raw: dict) -> ElementKey:
    """Schlüssel der Einreichungen eines Elements: (event_id, list_entry_id, manual_element_id)."""
    return raw["event_id"], raw["list_entry_id"], raw.get("manual_element_id")


def upload_key(upload: SubmissionUpload) -> ElementKey:
    return upload.event_id, upload.list_entry_id, upload.manual_element_id


def upload_key_filter(key: ElementKey) -> list:
    """WHERE-Bedingungen für die Einreichungen eines Elements (NULL-sicher)."""
    columns = (SubmissionUpload.event_id, SubmissionUpload.list_entry_id, SubmissionUpload.manual_element_id)
    return [column == value if value is not None else column.is_(None) for column, value in zip(columns, key)]


def _resolve_event_responsible(event: Event, source: str | None) -> list[int]:
    """Alle Personen im Verantwortlichen-Feld des Termins (mehrere = gemeinsam verantwortlich)."""
    if not source:
        return []
    return list(dict.fromkeys(int(pid) for pid in (getattr(event, source, None) or []) if pid))


def _resolve_list_responsible(entry: ListEntry, definition: ListDefinition, source: str | None) -> list[int]:
    """Verantwortliche eines Listeneintrags: die gewählte Personen-Spalte (``source`` = Spalten-Key;
    alte Werte der festen Spalten vor 0186 löst der v1-Adapter auf). Ohne Quelle niemand."""
    if not source:
        return []
    column = list_columns.resolve_column(definition, source)
    if column is None or column.value_type not in list_columns.PARTICIPANT_TYPES:
        return []
    ids = list_columns.participant_ids_of(list_columns.get_value(entry, column), column.value_type)
    return list(dict.fromkeys(int(pid) for pid in ids if pid))


def _parse_element_ref(db: Session, element_ref: str) -> ElementKey:
    """Referenz -> (event_id, list_entry_id, manual_element_id). Löst ohne Mandantenfilter auf: der
    Aufrufer prüft danach, dass das Element zu seiner (mandantengebundenen) Abgabe gehört."""
    if element_ref == MANUAL_ELEMENT_REF:
        return None, None, None
    kind, _, raw_id = element_ref.partition("-")
    try:
        public_id = uuid.UUID(raw_id)
    except ValueError:
        raise ValueError("Ungültige Element-Referenz") from None
    if kind == "event":
        internal_id = public_id_service.resolve_internal_id(db, Event, public_id)
        if internal_id is None:
            raise ValueError("Ungültige Element-Referenz")
        return internal_id, None, None
    if kind == "entry":
        internal_id = public_id_service.resolve_internal_id(db, ListEntry, public_id)
        if internal_id is None:
            raise ValueError("Ungültige Element-Referenz")
        return None, internal_id, None
    if kind == "manual":
        element = public_id_service.get_by_public_id(db, SubmissionManualElement, public_id)  # nosemgrep: public-id-lookup-without-tenant -- Aufrufer prüft die Zugehörigkeit zur Abgabe
        if element is None or element.is_default:
            raise ValueError("Ungültige Element-Referenz")
        return None, None, element.id
    raise ValueError("Ungültige Element-Referenz")


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

    def _assignment_read(self, assignment: SubmissionAssignment, db: Session | None = None) -> SubmissionAssignmentRead:
        read = SubmissionAssignmentRead.model_validate(assignment)
        read.link_ids = [link.public_id for link in assignment.links]
        if assignment.source_type == "manual":
            session = db or Session.object_session(assignment)
            if session is not None:
                read.manual_elements = self.manual_elements_read(session, assignment)
        return read

    def manual_elements_read(self, db: Session, assignment: SubmissionAssignment) -> list[SubmissionManualElementRead]:
        elements = self.repository.list_manual_elements(db, assignment_id=assignment.id)
        all_ids = {int(pid) for element in elements for pid in (element.responsible_participant_ids or [])}
        public_ids = self._tenant_participant_public_ids(db, assignment.tenant_id, all_ids)
        return [
            SubmissionManualElementRead(
                id=element.public_id,
                element_ref=manual_element_ref(element),
                name=element.name,
                window_start=element.window_start,
                window_end=element.window_end,
                is_default=element.is_default,
                responsible_participant_ids=[
                    public_ids[int(pid)] for pid in (element.responsible_participant_ids or []) if int(pid) in public_ids
                ],
            )
            for element in elements
        ]

    @staticmethod
    def _tenant_participant_public_ids(db: Session, tenant_id: int, ids: set[int]) -> dict[int, uuid.UUID]:
        """Nur Personen des Mandanten (gespeicherte IDs fremder oder gelöschter Personen fallen weg)."""
        if not ids:
            return {}
        return dict(db.execute(
            select(Participant.id, Participant.public_id).where(Participant.id.in_(ids), Participant.tenant_id == tenant_id)
        ).all())

    @staticmethod
    def _resolve_responsible(db: Session, tenant_id: int, public_ids: list[uuid.UUID]) -> list[int]:
        """Öffentliche Personen-IDs -> interne, nur im eigenen Mandanten. Eine fremde oder unbekannte
        ID lehnt die ganze Änderung ab (gleiche Meldung, kein Existenz-Orakel)."""
        result: list[int] = []
        for public_id in dict.fromkeys(public_ids):
            internal_id = public_id_service.resolve_internal_id(db, Participant, public_id, tenant_id=tenant_id)
            if internal_id is None:
                raise ValueError("Verantwortliche Person nicht gefunden")
            result.append(internal_id)
        return result

    def _sync_manual_elements(
        self,
        db: Session,
        assignment: SubmissionAssignment,
        items: list[SubmissionManualElementWrite] | None,
        *,
        fallback_deadline: date | None = None,
        eraser=None,
    ) -> None:
        """Elemente einer Einzelabgabe anlegen, ändern, entfernen (ohne Commit). Dateien entfernter
        Elemente sammelt `eraser`: der Aufrufer committet die ganze Änderung und löscht die
        Speicherobjekte danach (eraser.after_commit) - kein halber Stand bei einem späteren Fehler. `items` None = unverändert; gibt es
        noch keine Elemente, entsteht das Standard-Element aus Titel und (altem) Stichtag. Bestehende
        Elemente werden über ihre öffentliche ID erkannt - nur Elemente dieser Abgabe, sonst ValueError.
        Alle Prüfungen laufen, bevor etwas geändert wird."""
        existing = self.repository.list_manual_elements(db, assignment_id=assignment.id)
        if items is None:
            if not existing:
                db.add(SubmissionManualElement(
                    tenant_id=assignment.tenant_id, assignment_id=assignment.id, is_default=True,
                    name=(assignment.title or "").strip()[:200] or "Abgabe", window_end=fallback_deadline, sort_index=0,
                ))
                db.flush()
            return
        if not items:
            raise ValueError("Eine Einzelabgabe braucht mindestens ein Element")
        by_public_id = {element.public_id: element for element in existing}
        kept: set[int] = set()
        prepared: list[tuple[SubmissionManualElement | None, SubmissionManualElementWrite, list[int]]] = []
        for item in items:
            current = None
            if item.id is not None:
                current = by_public_id.get(item.id)
                if current is None or current.id in kept:
                    raise ValueError("Element nicht gefunden")
                kept.add(current.id)
            prepared.append((current, item, self._resolve_responsible(db, assignment.tenant_id, item.responsible_participant_ids)))
        for element in existing:
            if element.id not in kept:
                self._delete_manual_element(db, assignment, element, eraser=eraser)
        has_default = any(element.is_default for element in existing if element.id in kept)
        for index, (current, item, responsible) in enumerate(prepared):
            if current is None:
                # Neue Abgabe: das erste Element ist das Standard-Element (Referenz «manual»)
                current = SubmissionManualElement(
                    tenant_id=assignment.tenant_id, assignment_id=assignment.id,
                    is_default=not existing and not has_default and index == 0,
                )
                has_default = has_default or current.is_default
            current.name = item.name
            current.window_start = item.window_start
            current.window_end = item.window_end
            current.responsible_participant_ids = responsible
            current.sort_index = index
            db.add(current)
        db.flush()

    def _delete_manual_element(self, db: Session, assignment: SubmissionAssignment, element: SubmissionManualElement, *, eraser=None) -> None:
        """Element entfernen: Dateien seiner Einreichungen vollständig löschen (wie beim Löschen eines
        Listeneintrags, PRIV-003), App-Verknüpfungen lösen. Pendenzen gleicht der Abgleich danach ab."""
        from app.services import deletion_service

        ref = manual_element_ref(element)
        if element.is_default:
            deletion_service.erase_uploads_of(db, manual_default_assignment_id=assignment.id, eraser=eraser)
            # Schliessen/Wiederöffnen-Zeilen ohne Dateien
            db.execute(
                SubmissionUpload.__table__.delete().where(
                    SubmissionUpload.assignment_id == assignment.id, *upload_key_filter((None, None, None))
                )
            )
        else:
            deletion_service.erase_uploads_of(db, manual_element_id=element.id, eraser=eraser)
        db.execute(
            GalleryImage.__table__.update()
            .where(
                GalleryImage.tenant_id == assignment.tenant_id,
                GalleryImage.submission_assignment_id == assignment.id,
                GalleryImage.submission_element_ref == ref,
            )
            .values(submission_assignment_id=None, submission_element_ref=None, submission_withdrawn_at=None)
        )
        db.delete(element)
        db.flush()

    def list_assignments(self, db: Session, *, tenant_id: int) -> list[SubmissionAssignmentRead]:
        return [self._assignment_read(item, db) for item in self.repository.list_assignments(db, tenant_id=tenant_id)]

    def get_assignment(self, db: Session, assignment_id: int) -> SubmissionAssignment | None:
        return self.repository.get_assignment(db, assignment_id)

    def create_assignment(
        self, db: Session, payload: SubmissionAssignmentCreate, *, tenant_id: int
    ) -> SubmissionAssignmentRead:
        self._validate_source_fields(payload)
        if payload.manual_elements is not None and payload.source_type != "manual":
            raise ValueError("Elemente gibt es nur bei Einzelabgaben")
        list_definition_id = self._resolve_list_definition_tenant(db, payload.list_definition_id, tenant_id=tenant_id)
        values = payload.model_dump(exclude={"reviewer_ids", "file_visibility", "manual_elements"})  # Prüfer/Freigabe setzt die Route (submission_reviewer_service)
        link_ids = values.pop("link_ids")
        # Einzelabgabe: das Zeitfenster gehört zu den Elementen (0198); ein Stichtag von älteren
        # Clients wird zum Ende des Standard-Elements
        fallback_deadline = values["deadline"] if payload.source_type == "manual" else None
        if payload.source_type == "manual":
            values["deadline"] = None
        values["list_definition_id"] = list_definition_id
        values["cycle_config_id"] = self._resolve_cycle_config_tenant(db, payload.cycle_config_id, tenant_id=tenant_id)
        values["cycle_offsets"] = sorted(set(values["cycle_offsets"]), reverse=True)
        links = (
            submission_link_service.default_links(db, tenant_id)
            if link_ids is None
            else submission_link_service.resolve_links(db, link_ids, tenant_id=tenant_id)
        )
        entity = SubmissionAssignment(tenant_id=tenant_id, links=links, **values)
        if payload.source_type == "manual":
            # Abgabe und Elemente in einer Transaktion (eine fremde Person bricht alles ab)
            db.add(entity)
            db.flush()
            self._sync_manual_elements(db, entity, payload.manual_elements, fallback_deadline=fallback_deadline)
        created = self.repository.create_assignment(db, entity)
        self.sync_todos_if_tracked(db, created)
        return self._assignment_read(created, db)

    def update_assignment(
        self, db: Session, assignment_id: int, payload: SubmissionAssignmentUpdate
    ) -> SubmissionAssignmentRead | None:
        assignment = self.repository.get_assignment(db, assignment_id)
        if assignment is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if values.get("keep_open_after_end", False) is None:
            values.pop("keep_open_after_end")  # null = unverändert (Spalte ist NOT NULL)
        for key in ("owner_access", "owner_access_days", "owner_resubmit_only_personal", "todo_tags", "todo_own_tag"):
            if key in values and values[key] is None:
                values.pop(key)  # null = unverändert (Spalten sind NOT NULL)
        # Vor der Änderung: welche Tags die Pendenzen bisher von der Abgabe bekamen (Titel, Tags,
        # Schalter können sich ändern) - der Abgleich nimmt nur diese wieder weg.
        previous_todo_tags = submission_todo_tags(assignment)
        values.pop("reviewer_ids", None)  # Prüfer setzt die Route (submission_reviewer_service)
        values.pop("file_visibility", None)  # Kontext-Freigabe setzt die Route (context_visibility_service)
        values.pop("manual_elements", None)
        manual_items = payload.manual_elements
        link_ids = values.pop("link_ids", None)
        sync_manual = False
        fallback_deadline = None
        if values.get("source_type", assignment.source_type) == "manual":
            # Stichtag älterer Clients: Ende des Standard-Elements, falls es noch keine Elemente gibt
            fallback_deadline = values.pop("deadline", None) or assignment.deadline
            if assignment.deadline is not None:
                values["deadline"] = None
            sync_manual = manual_items is not None or not self.repository.list_manual_elements(db, assignment_id=assignment.id)
        elif manual_items is not None:
            raise ValueError("Elemente gibt es nur bei Einzelabgaben")
        from app.services.file_eraser import FileEraser

        # Dateien entfernter Elemente erst nach dem Commit der ganzen Änderung löschen
        eraser = FileEraser()
        if link_ids is not None:
            assignment.links = submission_link_service.resolve_links(db, link_ids, tenant_id=assignment.tenant_id)
        if not values:
            if sync_manual:
                self._sync_manual_elements(db, assignment, manual_items, fallback_deadline=fallback_deadline, eraser=eraser)
            if link_ids is not None or sync_manual:
                db.add(assignment)
                db.commit()
                eraser.after_commit(db)
                db.refresh(assignment)
                if link_ids is not None:
                    self.refresh_todo_links(db, assignment)
                self.sync_todos_if_tracked(db, assignment)
            return self._assignment_read(assignment, db)
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
        if sync_manual:
            self._sync_manual_elements(db, assignment, manual_items, fallback_deadline=fallback_deadline, eraser=eraser)
        updated = self.repository.update_assignment(db, assignment, values)  # committet alles zusammen
        eraser.after_commit(db)
        if link_ids is not None:
            self.refresh_todo_links(db, updated)
        self.sync_todos_if_tracked(db, updated, previous_todo_tags=previous_todo_tags)
        return self._assignment_read(updated, db)

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
                cycle_years_for_offsets(local_today(), config.reset_month, config.reset_day, assignment.cycle_offsets)
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
                raise ValueError("tag_filter ist für Termin-Abgaben erforderlich")
            if values.get("list_definition_id") is not None or values.get("deadline") is not None:
                raise ValueError("list_definition_id/deadline duerfen bei Termin-Abgaben nicht gesetzt sein")
            # Zyklus-Filter: Konfiguration und Zyklen gehoeren zusammen (ohne beides = alle Termine).
            if (values.get("cycle_config_id") is None) != (not values.get("cycle_offsets")):
                raise ValueError("cycle_config_id und cycle_offsets müssen zusammen gesetzt sein")
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
                raise ValueError("list_definition_id ist für Listen-Abgaben erforderlich")
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
                        _shift_date(event.event_date, -assignment.offset_days_before)
                        if assignment.offset_days_before is not None else None
                    ),
                    "window_end": (
                        _shift_date(event.event_end_date or event.event_date, assignment.offset_days_after)
                        if assignment.offset_days_after is not None else None
                    ),
                    "responsible_participant_ids": _resolve_event_responsible(event, source),
                }
                for event in events
            ]
            return self._sort_raw_elements(raw, assignment.sort_order)

        if assignment.source_type == "manual":
            # Von Hand angelegte Elemente (Migration 0198) in ihrer Reihenfolge aus dem Formular.
            # Das Standard-Element hat kein Ziel in der Einreichung (Schlüssel wie vor 0198).
            elements = self.repository.list_manual_elements(db, assignment_id=assignment.id)
            if not elements:
                # Ohne Elemente (nur bei Daten, die am Dienst vorbei entstanden sind): wie vor 0198
                # ein Element, die Abgabe selbst - gleiche Regel wie die Abgabebox
                return [{
                    "event_id": None, "event_public_id": None, "list_entry_id": None, "list_entry_public_id": None,
                    "manual_element_id": None, "element_ref": MANUAL_ELEMENT_REF, "label": assignment.title,
                    "sort_date": None, "window_start": None, "window_end": None, "responsible_participant_ids": [],
                }]
            all_ids = {int(pid) for element in elements for pid in (element.responsible_participant_ids or [])}
            own = set(self._tenant_participant_public_ids(db, assignment.tenant_id, all_ids))
            return [
                {
                    "event_id": None,
                    "event_public_id": None,
                    "list_entry_id": None,
                    "list_entry_public_id": None,
                    "manual_element_id": None if element.is_default else element.id,
                    "element_ref": manual_element_ref(element),
                    "label": element.name,
                    "sort_date": element.window_end or element.window_start,
                    "window_start": element.window_start,
                    "window_end": element.window_end,
                    "responsible_participant_ids": list(dict.fromkeys(
                        int(pid) for pid in (element.responsible_participant_ids or []) if int(pid) in own
                    )),
                }
                for element in elements
            ]

        definition = self.repository.get_list_definition(db, assignment.list_definition_id) if assignment.list_definition_id else None
        if definition is None:
            return []
        entries = self.repository.list_list_entries(db, list_definition_id=definition.id)
        participant_ids: set[int] = set()
        event_ids: set[int] = set()
        # Bezeichnung der Abgabe-Einträge aus der Spalte mit der Rolle «Bezeichnung» (0186)
        label_column = list_columns.label_column(definition)
        label_type = label_column.value_type if label_column else "text"
        for entry in entries:
            self._collect_referenced_ids(label_type, list_columns.get_value(entry, label_column), participant_ids, event_ids)
        participants_by_id = self.repository.get_participants(db, participant_ids=list(participant_ids))
        events_by_id = {eid: event for eid in event_ids if (event := self.repository.get_event(db, eid)) is not None}

        raw = [
            {
                "event_id": None,
                "event_public_id": None,
                "list_entry_id": entry.id,
                "list_entry_public_id": entry.public_id,
                "label": _value_label(
                    label_type,
                    list_columns.get_value(entry, label_column),
                    participants_by_id=participants_by_id,
                    events_by_id=events_by_id,
                ),
                # Listen-Eintraege haben kein eigenes Datum - nur der (optionale) Stichtag der
                # ganzen Abgabe existiert, gleich fuer alle Eintraege. "date"/"proximity"-Sortierung
                # kann sie also nicht unterscheiden und faellt auf die urspruengliche Reihenfolge zurueck.
                "sort_date": None,
                "window_start": None,
                "window_end": assignment.deadline,
                "responsible_participant_ids": _resolve_list_responsible(entry, definition, source),
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
            today = local_today()
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

    def element_refs(self, db: Session, assignment: SubmissionAssignment) -> list[str]:
        """Referenzen aller Elemente, die heute zur Abgabe gehören - ohne Bezeichnungen und
        Verantwortliche (für den Fortschritt, günstiger als _resolve_raw_elements)."""
        if assignment.source_type == "manual":
            elements = self.repository.list_manual_elements(db, assignment_id=assignment.id)
            return [manual_element_ref(element) for element in elements] if elements else [MANUAL_ELEMENT_REF]
        if assignment.source_type == "events":
            return [f"event-{event.public_id}" for event in self.list_assignment_events(db, assignment)]
        if assignment.list_definition_id is None:
            return []
        return [
            f"entry-{entry.public_id}"
            for entry in self.repository.list_list_entries(db, list_definition_id=assignment.list_definition_id)
        ]

    def summaries(self, db: Session, assignments: list[SubmissionAssignment]) -> dict[int, dict]:
        """Fortschritt mehrerer Abgaben: Element-Zustände in einer Runde Abfragen statt je Abgabe."""
        states = self.repository.element_states(db, assignment_ids=[assignment.id for assignment in assignments])
        return {
            assignment.id: self.repository.summarize_states(states.get(assignment.id, {}), self.element_refs(db, assignment))
            for assignment in assignments
        }

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
        uploads_by_key: dict[ElementKey, list[SubmissionUpload]] = {}
        for upload in uploads:
            uploads_by_key.setdefault(upload_key(upload), []).append(upload)

        linked_files: dict[str, list[StoredFile]] = {}
        for gallery_image, stored_file in db.execute(
            select(GalleryImage, StoredFile)
            .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
            .where(
                GalleryImage.tenant_id == assignment.tenant_id,
                StoredFile.tenant_id == assignment.tenant_id,
                GalleryImage.submission_assignment_id == assignment.id,
                GalleryImage.submission_withdrawn_at.is_(None),
            )
            .order_by(GalleryImage.id)
        ):
            linked_files.setdefault(gallery_image.submission_element_ref, []).append(stored_file)

        files_by_upload = self.repository.list_files_for_uploads(db, upload_ids=[upload.id for upload in uploads])
        withdrawn_by_key: dict[ElementKey, int] = {}
        if uploads:
            for event_id, list_entry_id, manual_element_id, count in db.execute(
                select(SubmissionUpload.event_id, SubmissionUpload.list_entry_id, SubmissionUpload.manual_element_id, func.count(SubmissionUploadFile.id))
                .join(SubmissionUploadFile, SubmissionUploadFile.upload_id == SubmissionUpload.id)
                .where(SubmissionUpload.assignment_id == assignment.id, SubmissionUploadFile.withdrawn_at.is_not(None))
                .group_by(SubmissionUpload.event_id, SubmissionUpload.list_entry_id, SubmissionUpload.manual_element_id)
            ):
                withdrawn_by_key[(event_id, list_entry_id, manual_element_id)] = int(count)
        withdrawn_linked = dict(db.execute(
            select(GalleryImage.submission_element_ref, func.count(GalleryImage.id))
            .where(
                GalleryImage.tenant_id == assignment.tenant_id, GalleryImage.submission_assignment_id == assignment.id,
                GalleryImage.submission_withdrawn_at.is_not(None),
                # wie die Abgabebox (submission_withdrawn_elements, 0199): Papierkorb zählt nicht
                not_trashed_id(GalleryImage.stored_file_id),
            )
            .group_by(GalleryImage.submission_element_ref)
        ).all())
        all_responsible = {pid for raw in raw_elements for pid in (raw.get("responsible_participant_ids") or [])}
        participant_public_ids = public_id_service.resolve_public_ids(db, Participant, list(all_responsible)) if all_responsible else {}

        results: list[SubmissionElementRead] = []
        for raw in raw_elements:
            key = raw_element_key(raw)
            element_uploads = uploads_by_key.get(key, [])

            files: list[SubmissionFileRead] = []
            submitted_at: datetime | None = None
            for upload in element_uploads:
                if upload.submitted_at is not None and (submitted_at is None or upload.submitted_at > submitted_at):
                    submitted_at = upload.submitted_at
                for stored_file in files_by_upload.get(upload.id, []):
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

            element_ref = raw_element_ref(raw)
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
            responsible_public_ids = [participant_public_ids[pid] for pid in responsible_ids if pid in participant_public_ids]
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
                    withdrawn_count=withdrawn_by_key.get(key, 0) + int(withdrawn_linked.get(element_ref, 0)),
                )
            )
        return results

    def _latest_upload_for_element(
        self, db: Session, assignment: SubmissionAssignment, element_ref: str
    ) -> tuple[ElementKey, SubmissionUpload | None]:
        # Nur Elemente dieser Abgabe (und damit dieses Mandanten): eine fremde oder erfundene
        # Referenz darf weder eine Zeile anlegen noch verraten, ob es den Termin gibt.
        raw = next((item for item in self._resolve_raw_elements(db, assignment) if raw_element_ref(item) == element_ref), None)
        if raw is None:
            raise ValueError("Element gehört nicht zu dieser Abgabe")
        key = raw_element_key(raw)
        uploads = self.repository.list_uploads_for_assignment(db, assignment_id=assignment.id)
        matching = [u for u in uploads if upload_key(u) == key]
        return key, (matching[-1] if matching else None)

    def close_element(self, db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionElementRead:
        """Schliesst ein Element manuell (keine weiteren Uploads mehr moeglich), unabhaengig
        davon, ob schon Dateien eingegangen sind - das Gegenstueck zu reopen_element, seit
        Abgaben ohne Tage-Fenster sonst unbegrenzt offen blieben."""
        lock_submission_element(db, assignment.id)
        (event_id, list_entry_id, manual_element_id), latest = self._latest_upload_for_element(db, assignment, element_ref)
        if latest is not None and latest.status == "closed":
            raise ValueError("Element ist bereits geschlossen")

        self.repository.create_upload(
            db,
            SubmissionUpload(
                assignment_id=assignment.id,
                event_id=event_id,
                list_entry_id=list_entry_id,
                manual_element_id=manual_element_id,
                status="closed",
                submitted_at=None,
            ),
        )
        return self._element_with_todo_sync(db, assignment, element_ref)

    def reopen_element(self, db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionElementRead:
        """Hebt eine manuelle Schliessung wieder auf. Bereits eingereichte Dateien bleiben
        erhalten (kumulatives Modell) - anders als vor der 2026-08-17 Umstellung, als reopen
        die bisherigen Dateien geloescht hat."""
        (event_id, list_entry_id, manual_element_id), latest = self._latest_upload_for_element(db, assignment, element_ref)
        if latest is None or latest.status != "closed":
            raise ValueError("Element ist nicht geschlossen")

        self.repository.create_upload(
            db,
            SubmissionUpload(
                assignment_id=assignment.id,
                event_id=event_id,
                list_entry_id=list_entry_id,
                manual_element_id=manual_element_id,
                status="submitted",
                submitted_at=None,
            ),
        )
        return self._element_with_todo_sync(db, assignment, element_ref)

    def _element_with_todo_sync(self, db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionElementRead:
        """Nach Schliessen/Wiederöffnen: Element neu lesen und seine Aufgabe nachführen."""
        element = next(
            (element for element in self.get_assignment_elements(db, assignment) if element.element_ref == element_ref),
            None,
        )
        if element is None:
            raise ValueError("Element gehört nicht zu dieser Abgabe")
        todo = db.scalar(
            select(ProtocolTodo).where(
                ProtocolTodo.submission_assignment_id == assignment.id,
                ProtocolTodo.element_ref == element.element_ref,
                ProtocolTodo.tenant_id == assignment.tenant_id,
                ProtocolTodo.pending_delete.is_(False),
            )
        )
        changed = todo is not None and self._apply_element_state(
            db, todo, element, expired=window_expired(element, assignment, local_today())
        )
        if self.refresh_completion(db, assignment) or changed:
            db.commit()
        return element

    def assignment_completion(self, db: Session, assignment: SubmissionAssignment) -> bool:
        """Regel «abgeschlossen» (docs/SUBMISSION_OWNER_ACCESS.md, Teil 2):

        - Jedes bekannte Element ist geschlossen oder hat eine geprüfte Datei (Quarantäne zählt nicht).
        - Und es kann nichts mehr dazukommen: manuell sofort; Termine/Zyklus, wenn kein Fenster mehr
          in der Zukunft endet; Listen, wenn der Stichtag vorbei ist (ohne Stichtag zählt der Stand).
        Ohne Elemente ist eine Abgabe nie abgeschlossen."""
        elements = self.get_assignment_elements(db, assignment)
        if not elements:
            return False
        if not all(element.status == "closed" or element_has_clean_files(element) for element in elements):
            return False
        today = local_today()
        if assignment.source_type == "manual":
            return True
        if assignment.source_type == "list":
            return assignment.deadline is None or assignment.deadline < today
        return not any(element.window_end is not None and element.window_end >= today for element in elements)

    def refresh_completion(self, db: Session, assignment: SubmissionAssignment) -> bool:
        """completed_at nachführen (ohne Commit). Liefert True bei einer Änderung."""
        done = self.assignment_completion(db, assignment)
        if done and assignment.completed_at is None:
            assignment.completed_at = datetime.now(UTC)
        elif not done and assignment.completed_at is not None:
            assignment.completed_at = None
        else:
            return False
        db.add(assignment)
        return True

    @staticmethod
    def _apply_element_state(db: Session, todo: ProtocolTodo, element: SubmissionElementRead, *, expired: bool = False) -> bool:
        """Aufgabe eines Elements nach seinem Zustand (Entscheid 2026-11-12, ergänzt 2026-11-18):

        - geprüfte Datei vorhanden → erledigt (Busse einfrieren, Mail «Abgabe eingegangen»)
        - von Hand geschlossen ohne geprüfte Datei → eine offene Aufgabe wird abgebrochen (keine
          Busse). Eine von Hand erledigte oder abgebrochene bleibt, wie sie ist.
        - automatisch geschlossen (``expired``: Fenster/Stichtag vorbei, ohne «nach dem Ende offen
          halten») ohne geprüfte Datei → wie von Hand geschlossen: abgebrochen. Mit «offen halten»
          bleibt sie offen und wird überfällig (Busse läuft ab der Fälligkeit = letzter Tag).
        - wieder geöffnet (von Hand oder Frist verlängert) ohne geprüfte Datei → eine abgebrochene
          Aufgabe wird wieder offen, samt Busse, falls eine Regel greift.

        Dateien im Virenscan zählen nicht: der Scan oder der Job submission_todo_sync erledigen
        die Aufgabe, sobald sie sauber sind. Liefert True, wenn sich etwas geändert hat (ohne Commit)."""
        statuses = dict(db.execute(select(TodoStatus.code, TodoStatus.id)).all())
        current = next((code for code, status_id in statuses.items() if status_id == todo.todo_status_id), None)
        if element_has_clean_files(element):
            target = "done"
        elif element.status == "closed" or expired:
            target = "cancelled" if current in ("open", "in_progress") else None
        else:
            target = "open" if current == "cancelled" else None
        target_id = statuses.get(target) if target else None
        if target_id is None or todo.todo_status_id == target_id:
            return False
        todo.todo_status_id = target_id
        if target == "open":
            todo.completed_at = None
        elif target == "done":
            todo.completed_at = element.submitted_at or datetime.now(UTC)
        else:
            todo.completed_at = datetime.now(UTC)
        db.add(todo)
        db.flush()
        todo_fine_service.sync_todo(db, todo)
        if target == "done":
            todo_notifications.on_submission_done(db, todo)
        return True

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
            .where(SubmissionAssignment.tenant_id.in_(booked))
            .order_by(SubmissionAssignment.id)
        ).all()
        synced = failed = 0
        # Persönliche Links und zurückgezogene Dateien aufräumen (Fehler nicht stumm, Abgleich läuft weiter)
        try:
            from app.services import submission_access_service

            submission_access_service.cleanup(db)
        except Exception as exc:
            db.rollback()
            record_system_error(db, exc=exc)
            failed += 1
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

    def sync_todos_if_tracked(
        self, db: Session, assignment: SubmissionAssignment, *, previous_todo_tags: list[str] | None = None
    ) -> bool:
        """Automatischer Todo-Abgleich (FAR-010): nach Anlegen/Ändern einer Abgabe, eines
        Termins oder eines Listeneintrags und periodisch im Job submission_todo_sync.

        Ohne erreichbaren Link gibt es nichts abzugleichen (erwarteter Zustand, kein Fehler).
        Ein unerwarteter Fehler bricht die auslösende Änderung nicht ab, landet aber im
        Fehlerprotokoll. Rückgabe False nur bei einem solchen Fehler."""
        tenant_id = assignment.tenant_id
        try:
            if submission_link_service.preferred_link(assignment) is None:
                # Keine Aufgaben abzugleichen, «abgeschlossen» trotzdem nachführen
                if self.refresh_completion(db, assignment):
                    db.commit()
                return True
            self.sync_submission_todos(db, assignment, previous_todo_tags=previous_todo_tags)
        except Exception as exc:
            # Nur ein Datenbankfehler hinterlässt eine abgebrochene Transaktion; alles andere
            # lässt die bereits committete auslösende Änderung unberührt.
            if isinstance(exc, SQLAlchemyError):
                db.rollback()
            record_system_error(db, exc=exc, tenant_id=tenant_id)
            return False
        return True

    def sync_submission_todos(
        self, db: Session, assignment: SubmissionAssignment, *, previous_todo_tags: list[str] | None = None
    ) -> dict:
        """Eine Pendenz je Element mit Verantwortlicher Person; Titel, Person, Frist und Link
        folgen dem Element. Hat das Element schon Dateien, ist die Pendenz erledigt (auch bei
        direkt verknüpften Dateien, die den Datenbank-Trigger nicht auslösen).

        Offene Pendenzen, deren Element weggefallen ist (Termin gelöscht, Tag oder Zyklus
        gewechselt, Verantwortliche entfernt, Abgabe ohne Verantwortlichen-Quelle), werden
        gelöscht. Erledigte bleiben als Verlauf stehen."""
        link = submission_link_service.preferred_link(assignment)
        if link is None:
            raise ValueError("Die Abgabe ist über keinen Link erreichbar – bitte zuerst einen Link auswählen")

        # Zwei gleichzeitige Abgleiche (z. B. zwei Terminänderungen) legten sonst dieselbe Pendenz
        # an; der zweite scheiterte an uix_protocol_todo_submission_element und landete im
        # Fehlerprotokoll. Mit dem Lock je Abgabe wartet er und sieht danach die Pendenzen des ersten.
        lock_submission_element(db, assignment.id)
        # Einzelabgaben: Verantwortliche je Element von Hand (0198), ohne Quelle
        tracked = bool(assignment.responsible_participant_source) or assignment.source_type == "manual"
        raw_elements = self._resolve_raw_elements(db, assignment) if tracked else []
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
        today = local_today()
        # Tags der Abgabe (0202); previous_todo_tags = Vorgabe vor einer Änderung der Abgabe
        wanted_tags = submission_todo_tags(assignment)
        previous_tags = wanted_tags if previous_todo_tags is None else previous_todo_tags
        base_url = submission_link_service.abgabebox_base_url(db, assignment.tenant_id)
        current_refs: set[str] = set()

        for raw in raw_elements:
            participant_ids = raw.get("responsible_participant_ids") or []
            if not participant_ids:
                continue
            element_ref = raw_element_ref(raw)
            current_refs.add(element_ref)
            url = f"{submission_link_service.link_url(base_url, link)}/{assignment.public_slug}/{element_ref}"
            # Das Standard-Element einer Einzelabgabe heisst meist wie die Abgabe: nicht doppelt
            task = assignment.title if raw["label"] == assignment.title else f"{assignment.title}: {raw['label']}"
            due_date = raw.get("window_end")
            state = states.get(element_ref)
            expired = state is not None and window_expired(state, assignment, today)
            # Nur geprüfte Dateien erledigen die Pendenz; Quarantäne/Scanfehler nicht (der Job
            # holt das nach, sobald der Scan sauber ist)
            has_files = bool(state and element_has_clean_files(state))

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
                    tags=list(wanted_tags),
                    submission_assignment_id=assignment.id,
                    element_ref=element_ref,
                )
                db.add(todo)
                db.flush()
                created += 1
            else:
                updated += 1
            previous_due = todo.due_date
            merged_tags = merge_submission_todo_tags(list(todo.tags or []), previous=previous_tags, wanted=wanted_tags)
            if merged_tags != list(todo.tags or []):
                todo.tags = merged_tags
            todo.task = task
            todo.due_date = due_date
            todo.reference_link = url
            # Alle Verantwortlichen des Elements (mehrere = gemeinsam). Die Anzeige liest
            # protocol_todo_assignee vor assigned_participant_id, daher immer beide nachführen.
            if (previous := todo_assignee_ids(db, todo.id)) != participant_ids or todo.assigned_participant_id != participant_ids[0]:
                set_todo_assignees(db, todo, participant_ids)
                # Abgabe-Aufgaben haben kein Protokoll: neu Verantwortliche sofort (gebündelt) melden
                todo_notifications.on_assignees_added(db, todo, [pid for pid in participant_ids if pid not in previous])
            # Frist verlängert: war das Element automatisch zu (alte Frist vorbei) und ist es jetzt
            # wieder offen, geht die Aufgabe wieder auf. Nur dann - eine von Hand abgebrochene
            # Aufgabe eines laufenden Elements bleibt abgebrochen.
            reopened_by_extension = (
                todo.todo_status_id == cancelled_id and not expired and previous_due is not None
                and previous_due < today and (due_date is None or due_date >= today)
            )
            if state is not None and (has_files or state.status == "closed" or expired or reopened_by_extension):
                # Datei geprüft → erledigt (auch aus «abgebrochen»: geschlossen, während die Datei
                # noch im Scan war); ohne Datei geschlossen (von Hand oder Frist vorbei) →
                # abgebrochen, keine Busse; Frist verlängert → wieder offen
                self._apply_element_state(db, todo, state, expired=expired)
            if has_files and todo.todo_status_id == done_id and todo.completed_at is not None:
                self._freeze_fines_after_trigger(db, todo)
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

        self.refresh_completion(db, assignment)
        db.commit()
        return {"created": created, "updated": updated, "removed": removed}

    @staticmethod
    def _freeze_fines_after_trigger(db: Session, todo: ProtocolTodo) -> None:
        """Der Datenbank-Trigger (Einreichung in der Abgabebox) erledigt die Aufgabe ohne Python,
        also ohne Pendenzen-Busse. Der Abgleich friert sie nach - genau einmal je Abschluss
        (protocol_todo.fine_evaluated_at, Migration 0177), auch wenn der Job tagelang ausfiel.
        Früher galt ein Fenster von zwei Tagen; danach ging die Busse still verloren."""
        if todo.fine_evaluated_at is not None:
            return
        todo_fine_service.sync_todo(db, todo)

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
        if results["clean"]:
            # Freigegebene Dateien erledigen ihre Aufgabe gleich (der Trigger greift nur beim
            # Einreichen mit sofort sauberer Datei)
            assignment = self.repository.get_assignment(db, assignment_id)
            if assignment is not None:
                self.sync_todos_if_tracked(db, assignment)
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
