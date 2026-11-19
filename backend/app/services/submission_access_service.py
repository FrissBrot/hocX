"""Persönlicher Link für Verantwortliche einer Abgabe (docs/SUBMISSION_OWNER_ACCESS.md, Teil 3).

Wer für ein Element einer Abgabe verantwortlich ist, bekommt in den Mails zur Abgabe-Aufgabe einen
eigenen Link (``/abgabe/verwalten#<token>``). Darüber sieht die Person ohne Login die eigene Abgabe
und kann - je nach Einstellung der Abgabe (``owner_access``) - sie zurückziehen und neu abgeben.

Sicherheit:
- 256 Bit Zufall, gespeichert wird nur der SHA-256-Hash; der Klartext steht nur in der Mail.
- Der Link bindet Mandant, Abgabe, Element und Person. Bei jedem Zugriff wird neu geprüft: gültig,
  nicht widerrufen, Option nicht ``off``, Feature gebucht, Person noch verantwortlich.
- Ungültig heisst immer dieselbe Antwort (None → 404 «Link ungültig oder abgelaufen»).
- Zurückziehen löscht nichts: die Dateien werden markiert (``withdrawn_at``) und lassen sich von der
  Verwaltung wiederherstellen.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.features_generated import F
from app.core.tenant_scope import bind_tenant_scope
from app.models import (
    GalleryImage,
    Participant,
    ProtocolTodo,
    SubmissionAccessToken,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    Tenant,
    TodoStatus,
)
from app.models.entities import TenantFeature
from app.schemas.submission import SubmissionElementRead

TOKEN_DAYS = 30
# Mehrere Mails (neue Aufgabe, Erinnerung, Abgabe eingegangen) bringen je einen Link; ältere
# bleiben gültig, damit ein Link aus einer früheren Mail nicht plötzlich ins Leere führt - aber
# höchstens so viele je Person und Element.
MAX_ACTIVE_LINKS = 5
OWNER_ACCESS_LEVELS = ("off", "view", "manage")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def feature_access(db: Session, tenant_id: int) -> str | None:
    return db.scalar(
        select(TenantFeature.access).where(TenantFeature.tenant_id == tenant_id, TenantFeature.feature_code == F.ABGABEBOX).limit(1)
    )


def issue(db: Session, *, assignment: SubmissionAssignment, element_ref: str, participant_id: int) -> str | None:
    """Neuer persönlicher Link (ohne Commit); None, wenn die Abgabe keinen Zugang vorsieht."""
    if assignment.owner_access == "off" or feature_access(db, assignment.tenant_id) not in ("full", "read_only"):
        return None
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(SubmissionAccessToken(
        tenant_id=assignment.tenant_id, assignment_id=assignment.id, element_ref=element_ref, participant_id=participant_id,
        token_hash=hash_token(token), created_at=now, expires_at=now + timedelta(days=assignment.owner_access_days or TOKEN_DAYS),
    ))
    db.flush()
    active = db.scalars(
        select(SubmissionAccessToken)
        .where(
            SubmissionAccessToken.assignment_id == assignment.id, SubmissionAccessToken.element_ref == element_ref,
            SubmissionAccessToken.participant_id == participant_id, SubmissionAccessToken.revoked_at.is_(None),
            SubmissionAccessToken.expires_at > now,
        )
        .order_by(SubmissionAccessToken.created_at.desc(), SubmissionAccessToken.id.desc())
    ).all()
    for old in active[MAX_ACTIVE_LINKS:]:
        old.revoked_at = now
    return token


@dataclass
class Access:
    token: SubmissionAccessToken
    assignment: SubmissionAssignment
    element: SubmissionElementRead
    person: Participant
    level: str  # view · manage (manage nur mit voll gebuchtem Feature)
    tenant_name: str


def _still_responsible(db: Session, assignment: SubmissionAssignment, element_ref: str, participant_id: int, raw: dict) -> bool:
    """Verantwortlich laut Abgabe (Quelle der Verantwortlichen) oder zugewiesen an der Aufgabe des
    Elements (von Hand umverteilt)."""
    if participant_id in (raw.get("responsible_participant_ids") or []):
        return True
    from app.notifications.todos import assignee_ids

    todo = db.scalar(
        select(ProtocolTodo).where(
            ProtocolTodo.submission_assignment_id == assignment.id, ProtocolTodo.element_ref == element_ref,
            ProtocolTodo.tenant_id == assignment.tenant_id, ProtocolTodo.pending_delete.is_(False),
        )
    )
    return todo is not None and participant_id in assignee_ids(db, todo)


def token_active(token: str) -> bool:
    """Schnelle Vorprüfung ohne Request-Session (Multipart-Schutz vor dem Lesen des Uploads):
    gibt es den Link, ist er weder widerrufen noch abgelaufen?"""
    from app.core.db import SessionLocal

    if not token or len(token) > 200:
        return False
    with SessionLocal() as db:
        return db.scalar(
            select(SubmissionAccessToken.id).where(
                SubmissionAccessToken.token_hash == hash_token(token), SubmissionAccessToken.revoked_at.is_(None),
                SubmissionAccessToken.expires_at > _now(),
            )
        ) is not None


def resolve(db: Session, token: str, *, touch: bool = True) -> Access | None:
    """Gültiger Zugang oder None - ohne zu verraten, woran es scheitert.

    Ein gültiger Link bindet die Session an seinen Mandanten (Row-Level-Security, wie
    get_optional_current_user): die öffentlichen Routen laufen sonst unbeschränkt, und die
    Element-Auflösung liest Teilnehmer/Termine aus Listenwerten ohne eigenen Mandantenfilter."""
    if not token or len(token) > 200:
        return None
    row = db.scalar(select(SubmissionAccessToken).where(SubmissionAccessToken.token_hash == hash_token(token)))
    now = _now()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    bind_tenant_scope(db, row.tenant_id)
    access = _resolve_bound(db, row, now, touch=touch)
    if access is None:
        bind_tenant_scope(db, None)
    return access


def _resolve_bound(db: Session, row: SubmissionAccessToken, now: datetime, *, touch: bool) -> Access | None:
    from app.services.submission_service import SubmissionService, raw_element_ref

    assignment = db.get(SubmissionAssignment, row.assignment_id)
    if assignment is None or assignment.tenant_id != row.tenant_id or assignment.owner_access == "off":
        return None
    access = feature_access(db, row.tenant_id)
    if access not in ("full", "read_only"):
        return None
    person = db.get(Participant, row.participant_id)
    if person is None or person.tenant_id != row.tenant_id or not person.is_active:
        return None
    service = SubmissionService()
    # Noch verantwortlich für genau dieses Element?
    raw = next(
        (
            entry for entry in service._resolve_raw_elements(db, assignment)
            if raw_element_ref(entry) == row.element_ref
        ),
        None,
    )
    if raw is None or not _still_responsible(db, assignment, row.element_ref, row.participant_id, raw):
        return None
    element = next((item for item in service.get_assignment_elements(db, assignment) if item.element_ref == row.element_ref), None)
    if element is None:
        return None
    if touch:
        row.last_used_at = now
        db.commit()
    # Deaktivierte Abgabe (in der Abgabebox nicht mehr erreichbar): nur noch ansehen
    level = "manage" if assignment.owner_access == "manage" and access == "full" and assignment.is_active else "view"
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == row.tenant_id)) or ""
    return Access(token=row, assignment=assignment, element=element, person=person, level=level, tenant_name=tenant_name)


def _element_filter(db: Session, element_ref: str) -> list:
    """WHERE-Bedingungen für die Einreichungen des Elements (event_id, list_entry_id, manual_element_id)."""
    from app.services.submission_service import _parse_element_ref, upload_key_filter

    return upload_key_filter(_parse_element_ref(db, element_ref))


def can_withdraw(access: Access) -> bool:
    return access.level == "manage" and access.element.status != "closed" and bool(access.element.files)


def _window_open(access: Access) -> bool:
    """Wie die Abgabebox: Hochladen im Zeitfenster des Elements. Nach dem Ende nur mit «offen
    halten» oder wenn die Person zurückgezogen hat (sonst wäre sie nach dem Korrigieren ausgesperrt)."""
    from app.services.submission_service import local_today

    element = access.element
    today = local_today()
    if element.window_start is not None and today < element.window_start:
        return False
    if element.window_end is None or today <= element.window_end:
        return True
    return bool(access.assignment.keep_open_after_end or element.withdrawn_count)


def can_upload(access: Access) -> bool:
    return access.level == "manage" and access.element.status != "closed" and _window_open(access)


def _set_withdrawn(db: Session, assignment: SubmissionAssignment, element_ref: str, value: datetime | None) -> int:
    """Markiert (value) bzw. entmarkiert (None) alle Dateien des Elements - Abgabebox und App."""
    upload_ids = select(SubmissionUpload.id).where(
        SubmissionUpload.assignment_id == assignment.id, *_element_filter(db, element_ref),
    )
    current = SubmissionUploadFile.withdrawn_at.is_(None) if value is not None else SubmissionUploadFile.withdrawn_at.is_not(None)
    changed = db.execute(
        update(SubmissionUploadFile).where(SubmissionUploadFile.upload_id.in_(upload_ids), current).values(withdrawn_at=value)
    ).rowcount or 0
    linked = GalleryImage.submission_withdrawn_at.is_(None) if value is not None else GalleryImage.submission_withdrawn_at.is_not(None)
    changed += db.execute(
        update(GalleryImage)
        .where(
            GalleryImage.tenant_id == assignment.tenant_id, GalleryImage.submission_assignment_id == assignment.id,
            GalleryImage.submission_element_ref == element_ref, linked,
        )
        .values(submission_withdrawn_at=value)
    ).rowcount or 0
    return changed


def _reopen_todo(db: Session, assignment: SubmissionAssignment, element_ref: str) -> None:
    """Nach dem Zurückziehen: eine erledigte Abgabe-Aufgabe ist wieder offen."""
    from app.services import todo_fine_service

    todo = db.scalar(
        select(ProtocolTodo).where(
            ProtocolTodo.submission_assignment_id == assignment.id, ProtocolTodo.element_ref == element_ref,
            ProtocolTodo.tenant_id == assignment.tenant_id, ProtocolTodo.pending_delete.is_(False),
        )
    )
    if todo is None:
        return
    statuses = dict(db.execute(select(TodoStatus.code, TodoStatus.id)).all())
    if todo.todo_status_id == statuses.get("done"):
        todo.todo_status_id = statuses["open"]
        todo.completed_at = None
        db.flush()
        todo_fine_service.sync_todo(db, todo)


def withdraw(db: Session, access: Access) -> int:
    """Zieht die Abgabe des Elements zurück (Dateien bleiben für die Verwaltung erhalten)."""
    from app.services.audit_service import AuditService

    count = _set_withdrawn(db, access.assignment, access.element.element_ref, _now())
    _reopen_todo(db, access.assignment, access.element.element_ref)
    AuditService().log(
        db, action="submission.withdrawn_by_owner", tenant_id=access.assignment.tenant_id, actor_user_id=access.person.id,
        actor_email=access.person.email, entity_type="submission_assignment", entity_id=access.assignment.id,
        details={"element_ref": access.element.element_ref, "files": count},
    )
    from app.notifications import submissions as submission_notifications
    from app.services.submission_service import SubmissionService

    submission_notifications.on_withdrawn(
        db, assignment=access.assignment, element_ref=access.element.element_ref, element_label=access.element.label,
        person=access.person, files=count,
    )
    SubmissionService().refresh_completion(db, access.assignment)
    db.commit()
    return count


def restore(db: Session, assignment: SubmissionAssignment, element_ref: str) -> int:
    """Verwaltung: zurückgezogene Dateien des Elements wiederherstellen (ohne Commit)."""
    return _set_withdrawn(db, assignment, element_ref, None)


def withdrawn_count(db: Session, assignment: SubmissionAssignment, element_ref: str) -> int:
    from sqlalchemy import func

    files = db.scalar(
        select(func.count(SubmissionUploadFile.id))
        .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
        .where(
            SubmissionUpload.assignment_id == assignment.id, SubmissionUploadFile.withdrawn_at.is_not(None),
            *_element_filter(db, element_ref),
        )
    ) or 0
    linked = db.scalar(
        select(func.count(GalleryImage.id)).where(
            GalleryImage.submission_assignment_id == assignment.id, GalleryImage.submission_element_ref == element_ref,
            GalleryImage.submission_withdrawn_at.is_not(None),
        )
    ) or 0
    return int(files) + int(linked)


CLEANUP_AFTER = timedelta(days=30)


def cleanup(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Aufräumen im Job submission_todo_sync (docs/SUBMISSION_OWNER_ACCESS.md):

    - abgelaufene oder widerrufene Links 30 Tage danach löschen,
    - Dateien, die vor über 30 Tagen zurückgezogen und nicht wiederhergestellt wurden, löschen
      (samt Speicherobjekt, Journal und leerer Einreichung, wie das Löschen in der Verwaltung),
    - zurückgezogene, direkt verknüpfte Bilder nach 30 Tagen von der Abgabe lösen (die Datei bleibt
      unter «Dateien» erhalten, sie gehört dem Verein).
    Committet selbst."""
    from sqlalchemy import delete, or_

    from app.models import StoredFile
    from app.services import deletion_service
    from app.services.file_service import FileService

    limit = (now or _now()) - CLEANUP_AFTER
    tokens = db.execute(
        delete(SubmissionAccessToken).where(or_(SubmissionAccessToken.expires_at < limit, SubmissionAccessToken.revoked_at < limit))
    ).rowcount or 0
    unlinked = db.execute(
        update(GalleryImage)
        .where(GalleryImage.submission_withdrawn_at.is_not(None), GalleryImage.submission_withdrawn_at < limit)
        .values(submission_assignment_id=None, submission_element_ref=None, submission_withdrawn_at=None)
    ).rowcount or 0
    db.commit()
    rows = db.execute(
        select(SubmissionUploadFile, StoredFile)
        .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
        .where(SubmissionUploadFile.withdrawn_at.is_not(None), SubmissionUploadFile.withdrawn_at < limit)
        .order_by(SubmissionUploadFile.id)
        .limit(500)
    ).all()
    files = len(rows)
    if rows:
        deletion_service.delete_submission_files(db, [(row[0], row[1]) for row in rows], file_service=FileService())
    return {"tokens": int(tokens), "files": files, "unlinked_images": int(unlinked)}
