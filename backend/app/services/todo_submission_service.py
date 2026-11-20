"""Einzelabgabe aus einer Pendenz («Als Abgabe einsammeln», ein Klick).

Die bestehende Pendenz wird selbst die Pendenz des Standard-Elements der neuen Einzelabgabe
(keine Doppel-Pendenz): Sie wird im selben Commit mit Abgabe und Element verknüpft
(``submission_assignment_id`` + ``element_ref`` «manual»), danach übernimmt sie der normale
Abgleich (SubmissionService.sync_submission_todos über todos_by_ref). Der Abgleich führt ab dann
Aufgabe, Fälligkeit, Link, Verantwortliche und Status; Notizen, Dateien, Tags, Busse und der
Protokoll-Bezug bleiben.

Standardwerte wie der Abgabe-Assistent im Frontend (submission-assignment-form.tsx, initialForm).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Participant, ProtocolTodo, SubmissionAssignment, TodoStatus
from app.repositories.protocol_todo_repository import ProtocolTodoRepository
from app.repositories.submission_repository import MANUAL_ELEMENT_REF
from app.schemas.protocol import TodoSubmissionFile, TodoSubmissionStatus
from app.schemas.submission import MAX_ELEMENT_RESPONSIBLE, SubmissionAssignmentCreate, SubmissionManualElementWrite
from app.services import submission_link_service
from app.services.submission_service import SubmissionService, local_today, lock_submission_element
from app.services.task_package_service import set_todo_assignees, todo_assignee_ids

# Elementname (ManualElementName) ist auf 200 Zeichen begrenzt; der Titel bleibt gleich lang, damit
# der Abgleich die Pendenz nur nach dem Titel benennt (Standard-Element heisst wie die Abgabe)
TITLE_MAX_LENGTH = 200
SLUG_MAX_LENGTH = 60
FALLBACK_SLUG = "abgabe"


class TodoSubmissionError(ValueError):
    """Erwartete Ablehnung mit stabilem Code (Route: 400/409, nicht ins Fehlerprotokoll)."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class TodoSubmissionResult:
    assignment: SubmissionAssignment
    element_url: str | None


def slugify(title: str) -> str:
    """Wie slugify() im Abgabe-Assistenten (submission-assignment-form.tsx), dazu gekürzt."""
    value = title.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:SLUG_MAX_LENGTH].strip("-") or FALLBACK_SLUG


def unique_slug(db: Session, tenant_id: int, title: str) -> str:
    """Slug aus dem Titel, im Mandanten eindeutig (Kollision: -2, -3, ...). Ein gleichzeitig
    angelegter gleicher Slug scheitert an uq_submission_assignment_tenant_slug (Route: 409)."""
    base = slugify(title)
    taken = set(
        db.scalars(
            select(SubmissionAssignment.public_slug).where(
                SubmissionAssignment.tenant_id == tenant_id,
                SubmissionAssignment.public_slug.like(f"{base}%"),
            )
        )
    )
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def _title_from_task(task: str) -> tuple[str, str | None]:
    """Titel aus der Aufgabe (eine Zeile, höchstens TITLE_MAX_LENGTH); bei gekürzter Aufgabe
    steht der volle Text in der Beschreibung, damit nichts verloren geht."""
    flat = " ".join((task or "").split())
    if len(flat) <= TITLE_MAX_LENGTH:
        return flat or "Abgabe", None
    return flat[: TITLE_MAX_LENGTH - 1].rstrip() + "…", flat


def _responsible_ids(db: Session, todo: ProtocolTodo) -> list[int]:
    """Alle Verantwortlichen der Pendenz (Reihenfolge wie protocol_todo_assignee), nur Personen
    des Mandanten der Pendenz."""
    ids = todo_assignee_ids(db, todo.id) or ([todo.assigned_participant_id] if todo.assigned_participant_id else [])
    if not ids:
        return []
    own = set(
        db.scalars(select(Participant.id).where(Participant.id.in_(ids), Participant.tenant_id == todo.tenant_id))
    )
    return [participant_id for participant_id in dict.fromkeys(ids) if participant_id in own]


def ensure_convertible(db: Session, todo: ProtocolTodo) -> None:
    """Prüfungen vor jedem Schreiben (Route ruft sie auch für einen klaren Fehler vor dem Anlegen)."""
    if todo.submission_assignment_id is not None:
        raise TodoSubmissionError("todo_already_submission", "Diese Pendenz gehört schon zu einer Abgabe.")
    if todo.pending_delete:
        raise TodoSubmissionError("todo_pending_delete", "Diese Pendenz ist zum Löschen markiert.")
    if todo.task_package_item_id is not None:
        raise TodoSubmissionError(
            "todo_from_task_package", "Pendenzen aus einem Aufgabenpaket lassen sich nicht als Abgabe einsammeln."
        )
    status_code = db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id))
    if status_code in ("done", "cancelled"):
        raise TodoSubmissionError("todo_closed", "Erledigte oder abgebrochene Pendenzen lassen sich nicht als Abgabe einsammeln.")


def create_from_todo(db: Session, todo: ProtocolTodo, *, tenant_id: int, service: SubmissionService | None = None) -> TodoSubmissionResult:
    """Einzelabgabe aus der Pendenz anlegen und die Pendenz verknüpfen (ein Commit), danach
    gleicht create_assignment die Pendenzen ab. ``todo`` ist schon im Mandanten aufgelöst."""
    service = service or SubmissionService()
    if todo.tenant_id != tenant_id:  # Defense in depth: Aufrufer löst per public_id mit tenant_id auf
        raise TodoSubmissionError("todo_not_found", "Todo not found", status_code=404)
    ensure_convertible(db, todo)

    responsible = _responsible_ids(db, todo)
    if not responsible:
        # Ohne Verantwortliche führt der Abgleich keine Pendenz für das Element: die Pendenz
        # bliebe unverknüpft stehen. Darum vorher verlangen.
        raise TodoSubmissionError(
            "todo_without_assignee", "Die Pendenz braucht eine verantwortliche Person, um sie als Abgabe einzusammeln.",
            status_code=400,
        )
    if len(responsible) > MAX_ELEMENT_RESPONSIBLE:
        raise TodoSubmissionError(
            "todo_too_many_assignees", f"Eine Abgabe hat höchstens {MAX_ELEMENT_RESPONSIBLE} Verantwortliche je Element.",
            status_code=400,
        )
    if not submission_link_service.default_links(db, tenant_id):
        raise TodoSubmissionError(
            "submission_no_default_link", "Es gibt keinen Standard-Link für Abgaben. Bitte zuerst unter Abgaben einen Link anlegen."
        )

    row = ProtocolTodoRepository().get_row(db, todo.id)
    # Fälligkeit wie angezeigt: festes Datum, Termin oder «nächste/letzte Sitzung» → festes Datum
    due: date | None = row.resolved_due_date if row is not None else todo.due_date
    title, full_task = _title_from_task(todo.task)
    public_ids = {pid: public_id for pid, public_id in db.execute(
        select(Participant.id, Participant.public_id).where(Participant.id.in_(responsible))
    ).all()}
    payload = SubmissionAssignmentCreate(
        title=title,
        description=full_task,
        public_slug=unique_slug(db, tenant_id, title),
        source_type="manual",
        max_files_per_element=5,
        max_file_size_mb=20,
        auto_close="never",
        # Schon überfällig: offen halten, sonst schlösse das abgelaufene Fenster das Element
        # sofort und der Abgleich bräche die Pendenz ab
        keep_open_after_end=due is not None and due < local_today(),
        owner_access="manage",
        owner_access_days=30,
        link_ids=None,  # Standard-Links des Mandanten
        manual_elements=[
            SubmissionManualElementWrite(
                name=title, window_end=due, responsible_participant_ids=[public_ids[pid] for pid in responsible if pid in public_ids],
            )
        ],
    )

    # Pendenz vorbereiten (gleicher Commit wie die Abgabe): feste Fälligkeit, Verantwortliche als
    # protocol_todo_assignee-Zeilen - sonst hielte der Abgleich sie für neu und meldete sie erneut
    todo.due_date = due
    todo.due_event_id = None
    todo.due_marker = None
    if todo_assignee_ids(db, todo.id) != responsible:
        set_todo_assignees(db, todo, responsible)
    created = service.create_assignment(db, payload, tenant_id=tenant_id, link_todo=todo)
    assignment = db.get(SubmissionAssignment, _internal_id(db, created.id, tenant_id))
    return TodoSubmissionResult(assignment=assignment, element_url=element_url(db, assignment, MANUAL_ELEMENT_REF))


def element_url(db: Session, assignment: SubmissionAssignment, element_ref: str) -> str | None:
    """Öffentliche Abgabebox-URL eines Elements über den bevorzugten Link (wie der Abgleich sie
    als reference_link setzt). Enthält den Link-Token: nur an Leute mit Leserecht auf die Abgabe."""
    link = submission_link_service.preferred_link(assignment)
    if link is None:
        return None
    base = submission_link_service.link_url(submission_link_service.abgabebox_base_url(db, assignment.tenant_id), link)
    return f"{base}/{assignment.public_slug}/{element_ref}"


def linked_assignment(db: Session, todo: ProtocolTodo) -> SubmissionAssignment | None:
    """Abgabe der Pendenz, nur im Mandanten der Pendenz (Defense in depth zum FK)."""
    if todo.submission_assignment_id is None or not todo.element_ref:
        return None
    assignment = db.get(SubmissionAssignment, todo.submission_assignment_id)
    if assignment is None or assignment.tenant_id != todo.tenant_id:
        return None
    return assignment


def submission_status(db: Session, todo: ProtocolTodo, assignment: SubmissionAssignment, *, service: SubmissionService | None = None) -> TodoSubmissionStatus:
    """Stand der Abgabe einer Pendenz für «Pendenz bearbeiten» › Dateien (Statuskarte, eingereichte
    Dateien). ``can_stop`` sagt nur, ob «Beenden» fachlich geht; die Rechte prüft die Route."""
    service = service or SubmissionService()
    elements = service.get_assignment_elements(db, assignment)
    element = next((item for item in elements if item.element_ref == todo.element_ref), None)
    files = [
        TodoSubmissionFile(
            id=file.id, original_name=file.original_name, mime_type=file.mime_type,
            file_size_bytes=file.file_size_bytes, content_url=file.content_url, scan_status=file.scan_status,
        )
        for file in (element.files if element is not None else [])
    ]
    return TodoSubmissionStatus(
        assignment_id=assignment.public_id,
        title=assignment.title,
        created_at=assignment.created_at,
        element_status=element.status if element is not None else "closed",
        submitted_at=element.submitted_at if element is not None else None,
        element_url=element_url(db, assignment, todo.element_ref) if element is not None else None,
        files=files,
        can_stop=_stoppable(db, assignment, elements),
    )


def _stoppable(db: Session, assignment: SubmissionAssignment, elements: list) -> bool:
    """«Beenden» löscht die Abgabe: nur eine Einzelabgabe mit genau einem Element, in die noch
    nichts eingegangen ist (keine Einreichung, keine Datei, auch keine zurückgezogene)."""
    from app.services import deletion_service

    if assignment.source_type != "manual" or len(elements) != 1:
        return False
    if any(element.files or element.withdrawn_count for element in elements):
        return False
    # Hängt noch eine weitere Pendenz an der Abgabe (z. B. Verlauf eines früheren Elements),
    # löschte ON DELETE CASCADE sie mit: dann nicht hier beenden
    others = db.scalar(
        select(func.count()).select_from(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id)
    ) or 0
    if others > 1:
        return False
    return not deletion_service.assignment_preview(db, assignment)


def stop_collecting(db: Session, todo: ProtocolTodo, *, actor_user_id: int | None, service: SubmissionService | None = None) -> SubmissionAssignment:
    """«Beenden»: Einsammeln abbrechen. Die Pendenz verliert den Bezug zur Abgabe und behält ihren
    Status, ihre Fälligkeit, Notizen und Dateien; die (leere) Einzelabgabe wird gelöscht.

    Bewusst nicht über DELETE /submission-assignments: dort löschte ON DELETE CASCADE eine Pendenz
    ohne Protokoll mit. Und nicht über «Element schliessen»: das bräche die Pendenz ab. Dateien
    werden nie gelöscht - kam zwischen Prüfung und Löschen doch eine an, bleibt sie in der
    Galerie (delete_file_ids leer)."""
    from app.services import deletion_service

    service = service or SubmissionService()
    assignment = linked_assignment(db, todo)
    if assignment is None:
        raise TodoSubmissionError("todo_not_submission", "Diese Pendenz gehört zu keiner Abgabe.", status_code=404)
    # Gleichzeitiger Abgleich der Abgabe wartet (er legte sonst die Pendenz neu an)
    lock_submission_element(db, assignment.id)
    if not _stoppable(db, assignment, service.get_assignment_elements(db, assignment)):
        raise TodoSubmissionError(
            "submission_not_stoppable",
            "Diese Abgabe lässt sich hier nicht beenden (schon eingereicht oder mehrere Elemente). Bitte unter Abgaben bearbeiten.",
        )
    todo.submission_assignment_id = None
    todo.element_ref = None
    todo.reference_link = None
    db.add(todo)
    db.flush()
    deletion_service.delete_assignment(db, assignment, delete_file_ids=set(), actor_user_id=actor_user_id)
    return assignment


def _internal_id(db: Session, public_id: uuid.UUID, tenant_id: int) -> int:
    from app.services import public_id_service

    internal_id = public_id_service.resolve_internal_id(db, SubmissionAssignment, public_id, tenant_id=tenant_id)
    if internal_id is None:  # gerade angelegt - nur bei einem Fehler im Ablauf
        raise RuntimeError("Neu angelegte Abgabe nicht gefunden")
    return internal_id
