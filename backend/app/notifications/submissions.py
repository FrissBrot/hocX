"""Mail an die Verwaltung, wenn eine verantwortliche Person ihre Abgabe über den persönlichen Link
zurückzieht (``submission.withdrawn``, docs/SUBMISSION_OWNER_ACCESS.md, Teil 3).

Empfänger sind alle aktiven Konten des Mandanten mit ``submissions.manage`` (über ihre Rollen,
admin hat immer alle Rechte), ausser der Person selbst. Beim Versand wird neu geprüft, ob die
Abgabe noch existiert und das Element noch zurückgezogene Dateien hat (sonst ist die Mail überholt,
z. B. weil die Verwaltung schon wiederhergestellt hat).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import P, effective_permissions
from app.models import Notification, Participant, SubmissionAssignment, TenantRole, TenantRolePermission, UserRole
from app.notifications import publish


def managers(db: Session, tenant_id: int) -> list[int]:
    """Konten des Mandanten, die Abgaben verwalten dürfen (effektive Rechte über alle Rollen)."""
    rows = db.execute(
        select(UserRole.user_id, TenantRole.system_key, TenantRolePermission.permission_key)
        .join(TenantRole, TenantRole.id == UserRole.role_id)
        .join(Participant, Participant.id == UserRole.user_id)
        .outerjoin(TenantRolePermission, TenantRolePermission.role_id == TenantRole.id)
        .where(UserRole.tenant_id == tenant_id, TenantRole.tenant_id == tenant_id, Participant.is_active.is_(True))
    ).all()
    keys: dict[int, list[str]] = {}
    systems: dict[int, list[str | None]] = {}
    for user_id, system_key, permission_key in rows:
        keys.setdefault(user_id, [])
        systems.setdefault(user_id, []).append(system_key)
        if permission_key is not None:
            keys[user_id].append(permission_key)
    return sorted(user_id for user_id in keys if P.SUBMISSIONS_MANAGE in effective_permissions(keys[user_id], systems[user_id]))


def on_withdrawn(db: Session, *, assignment: SubmissionAssignment, element_ref: str, element_label: str, person: Participant, files: int) -> int:
    """Benachrichtigung anlegen (ohne Commit)."""
    recipients = [user_id for user_id in managers(db, assignment.tenant_id) if user_id != person.id]
    return publish(
        db, kind="submission.withdrawn", tenant_id=assignment.tenant_id, recipient_ids=recipients, subject_id=assignment.id,
        payload={"element_ref": element_ref, "label": element_label, "person_id": person.id, "files": files},
    )


def items_for(db: Session, notifications: list[Notification], recipient_id: int, *, base_url: str | None = None, **_) -> dict[int, dict]:
    from app.services import submission_access_service

    if not notifications:
        return {}
    tenant_id = notifications[0].tenant_id
    ids = {n.subject_id for n in notifications if n.subject_id}
    assignments = {
        row.id: row for row in db.scalars(select(SubmissionAssignment).where(SubmissionAssignment.id.in_(ids), SubmissionAssignment.tenant_id == tenant_id))
    } if ids else {}
    person_ids = {int((n.payload or {}).get("person_id") or 0) for n in notifications}
    people = {
        row.id: row for row in db.scalars(select(Participant).where(Participant.id.in_(person_ids), Participant.tenant_id == tenant_id))
    } if person_ids else {}
    items: dict[int, dict] = {}
    for notification in notifications:
        payload = notification.payload or {}
        assignment = assignments.get(notification.subject_id)
        element_ref = str(payload.get("element_ref") or "")
        if assignment is None or not element_ref:
            continue
        try:
            still_withdrawn = submission_access_service.withdrawn_count(db, assignment, element_ref) > 0
        except ValueError:
            still_withdrawn = False
        if not still_withdrawn:
            continue
        person = people.get(int(payload.get("person_id") or 0))
        items[notification.id] = {
            "kind": notification.kind,
            "title": assignment.title,
            "label": str(payload.get("label") or ""),
            "person": (person.display_name if person else "") or "",
            "files": int(payload.get("files") or 0),
            "at": notification.created_at,
            "url": f"{base_url}/submission-assignments" if base_url else None,
        }
    return items
