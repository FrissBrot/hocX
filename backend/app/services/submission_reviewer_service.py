"""Prüfer je Abgabe-Auftrag und Reichweite «nur zugewiesene» (Plan «Berechtigungen», Phase 4).

Ein Konto mit ``submissions.read`` bzw. ``submissions.review`` nur in der Reichweite «zugewiesene»
(CurrentUser.assigned_only, Migration 0195) sieht bzw. prüft nur die Aufträge, denen es in
``resource_assignment`` als Prüfer zugewiesen ist. Fremde Aufträge sind für es 404 - wie ein
Auftrag eines anderen Mandanten (kein Existenz-Orakel). ``submissions.manage`` gilt immer für alle
(impliziert ``submissions.read`` für alle, siehe permissions.resolve_scopes).

Zuweisungen schreibt nur dieses Modul, nur mit ``submissions.manage`` (Routen in
api/routes/submission_assignments.py) und nur für Konten mit Login des eigenen Mandanten.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.permissions import P
from app.core.security import CurrentUser
from app.models import AppUser, ResourceAssignment, SubmissionAssignment

RESOURCE_TYPE = "submission_assignment"
FUNCTION_REVIEWER = "reviewer"
# Begrenzt nur Missbrauch (eine Zeile je Prüfer)
MAX_REVIEWERS = 100


# ── Reichweite ──────────────────────────────────────────────────────────────────────────────


def visible_assignment_ids(db: Session, user: CurrentUser) -> set[int] | None:
    """Interne IDs der Aufträge, die das Konto lesen darf; ``None`` = alle des Mandanten."""
    if user.sees_all(P.SUBMISSIONS_READ):
        return None
    return _assigned_ids(db, user)


def _assigned_ids(db: Session, user: CurrentUser) -> set[int]:
    return set(
        db.scalars(
            select(ResourceAssignment.resource_id).where(
                ResourceAssignment.tenant_id == user.current_tenant_id,
                ResourceAssignment.resource_type == RESOURCE_TYPE,
                ResourceAssignment.function == FUNCTION_REVIEWER,
                ResourceAssignment.user_id == user.user_id,
            )
        )
    )


def _is_reviewer(db: Session, user: CurrentUser, assignment: SubmissionAssignment) -> bool:
    return db.scalar(
        select(ResourceAssignment.id).where(
            ResourceAssignment.tenant_id == user.current_tenant_id,
            ResourceAssignment.resource_type == RESOURCE_TYPE,
            ResourceAssignment.function == FUNCTION_REVIEWER,
            ResourceAssignment.resource_id == assignment.id,
            ResourceAssignment.user_id == user.user_id,
        ).limit(1)
    ) is not None


def can_read(db: Session, user: CurrentUser, assignment: SubmissionAssignment) -> bool:
    """Lesen dieses Auftrags (Mandant prüft der Aufrufer bereits beim Laden)."""
    if assignment.tenant_id != user.current_tenant_id:
        return False
    return user.sees_all(P.SUBMISSIONS_READ) or _is_reviewer(db, user, assignment)


def ensure_can_read(db: Session, user: CurrentUser, assignment: SubmissionAssignment, *, detail: str = "Abgabe nicht gefunden") -> None:
    """Nicht lesbar = 404, gleiche Antwort wie für einen fremden oder unbekannten Auftrag."""
    if not can_read(db, user, assignment):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def ensure_can_review(db: Session, user: CurrentUser, assignment: SubmissionAssignment) -> None:
    """Schliessen/Wieder öffnen: ``submissions.review`` (prüft der Aufrufer) in der Reichweite des
    Kontos. Nicht lesbar = 404; lesbar (Reichweite alle), aber nicht zugewiesen = 403."""
    ensure_can_read(db, user, assignment)
    if not user.sees_all(P.SUBMISSIONS_REVIEW) and not _is_reviewer(db, user, assignment):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur zugewiesene Abgaben können geprüft werden")


# ── Prüfer lesen und setzen ─────────────────────────────────────────────────────────────────


def reviewer_ids(db: Session, tenant_id: int, assignment_ids: Iterable[int]) -> dict[int, list[uuid.UUID]]:
    """Öffentliche IDs der Prüfer je Auftrag (eine Abfrage für die ganze Liste)."""
    ids = list(set(assignment_ids))
    result: dict[int, list[uuid.UUID]] = {assignment_id: [] for assignment_id in ids}
    if not ids:
        return result
    rows = db.execute(
        select(ResourceAssignment.resource_id, AppUser.public_id)
        .join(AppUser, AppUser.id == ResourceAssignment.user_id)
        .where(
            ResourceAssignment.tenant_id == tenant_id,
            ResourceAssignment.resource_type == RESOURCE_TYPE,
            ResourceAssignment.function == FUNCTION_REVIEWER,
            ResourceAssignment.resource_id.in_(ids),
            AppUser.tenant_id == tenant_id,
        )
        .order_by(AppUser.display_name, AppUser.id)
    )
    for resource_id, public_id in rows:
        result[resource_id].append(public_id)
    return result


def candidates(db: Session, tenant_id: int) -> list[AppUser]:
    """Wählbare Prüfer: aktive Konten mit Login des Mandanten, die Abgaben überhaupt sehen dürfen
    (submissions.read über eine Rolle - gespeichert inkl. Implikationen, also auch review/manage).
    Sonst liessen sich Prüfer zuweisen, die nichts sehen, und die Liste zählte alle Logins auf
    (Security-Review Phase 4)."""
    from sqlalchemy import or_

    from app.core.permissions import ADMIN_ROLE_KEY
    from app.models import TenantRole, TenantRolePermission, UserRole

    # Standardrolle admin hat immer alle Rechte, auch ohne gespeicherte Zeilen (effective_permissions)
    can_read = (
        select(UserRole.user_id)
        .join(TenantRole, TenantRole.id == UserRole.role_id)
        .where(
            UserRole.tenant_id == tenant_id,
            or_(
                TenantRole.system_key == ADMIN_ROLE_KEY,
                TenantRole.id.in_(select(TenantRolePermission.role_id).where(TenantRolePermission.permission_key == "submissions.read")),
            ),
        )
    )
    return list(
        db.scalars(
            select(AppUser)
            .where(
                AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True), AppUser.login_enabled.is_(True),
                AppUser.id.in_(can_read),
            )
            .order_by(AppUser.display_name, AppUser.id)
        )
    )


def _current_user_ids(db: Session, assignment: SubmissionAssignment) -> set[int]:
    return set(
        db.scalars(
            select(ResourceAssignment.user_id).where(
                ResourceAssignment.tenant_id == assignment.tenant_id,
                ResourceAssignment.resource_type == RESOURCE_TYPE,
                ResourceAssignment.function == FUNCTION_REVIEWER,
                ResourceAssignment.resource_id == assignment.id,
            )
        )
    )


def resolve_reviewers(db: Session, assignment: SubmissionAssignment | None, tenant_id: int, public_ids: Iterable[uuid.UUID]) -> set[int]:
    """Interne IDs der gewünschten Prüfer. Neu zugewiesen werden nur aktive Konten mit Login des
    eigenen Mandanten; bereits zugewiesene dürfen bleiben (z. B. nach Entzug des Logins - sie
    können sich dann ohnehin nicht anmelden). Fremde/unbekannte IDs: ValueError (400, gleiche
    Antwort für beide)."""
    wanted = list(dict.fromkeys(public_ids))
    if len(wanted) > MAX_REVIEWERS:
        raise ValueError("Zu viele Prüfer")
    if not wanted:
        return set()
    existing = _current_user_ids(db, assignment) if assignment is not None else set()
    rows = db.execute(
        select(AppUser.id, AppUser.is_active, AppUser.login_enabled)
        .where(AppUser.tenant_id == tenant_id, AppUser.public_id.in_(wanted))
    ).all()
    allowed = {row.id for row in rows if (row.is_active and row.login_enabled) or row.id in existing}
    if len(rows) != len(wanted) or len(allowed) != len(wanted):
        raise ValueError("Unbekannter Prüfer")
    return allowed


def set_reviewers(db: Session, actor: CurrentUser, assignment: SubmissionAssignment, user_ids: set[int]) -> tuple[list[int], list[int]]:
    """Setzt die Prüfer vollständig (ohne Commit). Gibt (hinzugefügt, entfernt) zurück."""
    if assignment.tenant_id != actor.current_tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Abgabe nicht gefunden")
    current = _current_user_ids(db, assignment)
    added, removed = sorted(user_ids - current), sorted(current - user_ids)
    if removed:
        db.execute(
            delete(ResourceAssignment).where(
                ResourceAssignment.tenant_id == assignment.tenant_id,
                ResourceAssignment.resource_type == RESOURCE_TYPE,
                ResourceAssignment.function == FUNCTION_REVIEWER,
                ResourceAssignment.resource_id == assignment.id,
                ResourceAssignment.user_id.in_(removed),
            )
        )
    for user_id in added:
        db.add(
            ResourceAssignment(
                tenant_id=assignment.tenant_id, resource_type=RESOURCE_TYPE, resource_id=assignment.id,
                user_id=user_id, function=FUNCTION_REVIEWER, created_by=actor.user_id,
            )
        )
    db.flush()
    return added, removed
