# GENERATED FILE - do not edit by hand. Source of truth: permissions/catalog.json (repo root).
# Regenerate with: python3 scripts/sync-permission-catalog.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class P(StrEnum):
    MEETINGS_READ = "meetings.read"
    MEETINGS_READ_DRAFTS = "meetings.read_drafts"
    MEETINGS_EDIT = "meetings.edit"
    MEETINGS_APPROVE = "meetings.approve"
    TODOS_COMPLETE_OWN = "todos.complete_own"
    TEMPLATES_EDIT = "templates.edit"
    TEMPLATES_MANAGE = "templates.manage"
    PARTICIPANTS_READ = "participants.read"
    PARTICIPANTS_CONTACTS = "participants.contacts"
    PARTICIPANTS_MANAGE = "participants.manage"
    PARTICIPANTS_EXPORT = "participants.export"
    FINANCES_READ = "finances.read"
    FINANCES_MANAGE = "finances.manage"
    FINES_MANAGE = "fines.manage"
    REPORTS_PERSONAL = "reports.personal"
    FILES_READ = "files.read"
    FILES_MANAGE = "files.manage"
    FILES_IMPORT = "files.import"
    PHOTOS_READ = "photos.read"
    PHOTOS_MANAGE = "photos.manage"
    SHARING_PUBLIC = "sharing.public"
    SUBMISSIONS_READ = "submissions.read"
    SUBMISSIONS_REVIEW = "submissions.review"
    SUBMISSIONS_MANAGE = "submissions.manage"
    SETTINGS_MANAGE = "settings.manage"
    ACTIVITY_READ = "activity.read"
    SECURITY_READ = "security.read"
    ACCESS_MANAGE = "access.manage"
    DATA_EXPORT = "data.export"


@dataclass(frozen=True)
class PermissionDef:
    area: str
    feature: str | None
    requires_mfa: bool
    implies: tuple[P, ...]
    # Mögliche Reichweiten ("all" zuerst = Standard); leer = Recht ohne Reichweite (immer alle).
    scopes: tuple[str, ...] = ()


AREAS: tuple[str, ...] = ("meetings", "templates", "participants", "finances", "reports", "files", "submissions", "administration",)

CATALOG: dict[P, PermissionDef] = {
    P.MEETINGS_READ: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=()),
    P.MEETINGS_READ_DRAFTS: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ,)),
    P.MEETINGS_EDIT: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ_DRAFTS,)),
    P.MEETINGS_APPROVE: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ_DRAFTS,)),
    P.TODOS_COMPLETE_OWN: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=()),
    P.TEMPLATES_EDIT: PermissionDef(area="templates", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ,)),
    P.TEMPLATES_MANAGE: PermissionDef(area="templates", feature=None, requires_mfa=False, implies=(P.TEMPLATES_EDIT,)),
    P.PARTICIPANTS_READ: PermissionDef(area="participants", feature=None, requires_mfa=False, implies=()),
    P.PARTICIPANTS_CONTACTS: PermissionDef(area="participants", feature=None, requires_mfa=False, implies=(P.PARTICIPANTS_READ,)),
    P.PARTICIPANTS_MANAGE: PermissionDef(area="participants", feature=None, requires_mfa=False, implies=(P.PARTICIPANTS_CONTACTS,)),
    P.PARTICIPANTS_EXPORT: PermissionDef(area="participants", feature=None, requires_mfa=True, implies=(P.PARTICIPANTS_READ,)),
    P.FINANCES_READ: PermissionDef(area="finances", feature="finance", requires_mfa=False, implies=()),
    P.FINANCES_MANAGE: PermissionDef(area="finances", feature="finance", requires_mfa=False, implies=(P.FINANCES_READ,)),
    P.FINES_MANAGE: PermissionDef(area="finances", feature="finance", requires_mfa=False, implies=(P.FINANCES_READ,)),
    P.REPORTS_PERSONAL: PermissionDef(area="reports", feature=None, requires_mfa=False, implies=()),
    P.FILES_READ: PermissionDef(area="files", feature=None, requires_mfa=False, implies=()),
    P.FILES_MANAGE: PermissionDef(area="files", feature=None, requires_mfa=False, implies=(P.FILES_READ,)),
    P.FILES_IMPORT: PermissionDef(area="files", feature=None, requires_mfa=False, implies=()),
    P.PHOTOS_READ: PermissionDef(area="files", feature=None, requires_mfa=False, implies=()),
    P.PHOTOS_MANAGE: PermissionDef(area="files", feature=None, requires_mfa=False, implies=(P.PHOTOS_READ,)),
    P.SHARING_PUBLIC: PermissionDef(area="files", feature=None, requires_mfa=False, implies=()),
    P.SUBMISSIONS_READ: PermissionDef(area="submissions", feature="abgabebox", requires_mfa=False, implies=(), scopes=("all", "assigned",)),
    P.SUBMISSIONS_REVIEW: PermissionDef(area="submissions", feature="abgabebox", requires_mfa=False, implies=(P.SUBMISSIONS_READ,), scopes=("all", "assigned",)),
    P.SUBMISSIONS_MANAGE: PermissionDef(area="submissions", feature="abgabebox", requires_mfa=False, implies=(P.SUBMISSIONS_READ,)),
    P.SETTINGS_MANAGE: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
    P.ACTIVITY_READ: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
    P.SECURITY_READ: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
    P.ACCESS_MANAGE: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
    P.DATA_EXPORT: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
}

# Rechte mit Reichweite (alle | zugewiesene), siehe docs/permissions-plan.md, Phase 4.
SCOPED_PERMISSIONS: frozenset[P] = frozenset(key for key, definition in CATALOG.items() if definition.scopes)

# Standardrollen je Mandant (tenant_role.system_key). "admin" hat immer alle Permissions, auch
# künftig neu hinzukommende - beim Laden ausgewertet, nicht über tenant_role_permission.
SYSTEM_ROLE_KEYS: tuple[str, ...] = ('admin', 'writer', 'kassier', 'reader')
SYSTEM_ROLE_PERMISSIONS: dict[str, frozenset[P]] = {
    "admin": frozenset(P),
    "writer": frozenset({P.MEETINGS_READ, P.MEETINGS_READ_DRAFTS, P.MEETINGS_EDIT, P.MEETINGS_APPROVE, P.TODOS_COMPLETE_OWN, P.TEMPLATES_EDIT, P.PARTICIPANTS_READ, P.PARTICIPANTS_CONTACTS, P.PARTICIPANTS_MANAGE, P.FINANCES_READ, P.REPORTS_PERSONAL, P.FILES_READ, P.FILES_MANAGE, P.PHOTOS_READ, P.PHOTOS_MANAGE, P.SHARING_PUBLIC, P.SUBMISSIONS_READ, P.SUBMISSIONS_REVIEW, P.SUBMISSIONS_MANAGE}),
    "kassier": frozenset({P.MEETINGS_READ, P.MEETINGS_READ_DRAFTS, P.TODOS_COMPLETE_OWN, P.FINANCES_READ, P.FINANCES_MANAGE, P.FINES_MANAGE, P.REPORTS_PERSONAL, P.SUBMISSIONS_READ}),
    "reader": frozenset({P.MEETINGS_READ, P.TODOS_COMPLETE_OWN, P.FINANCES_READ, P.SUBMISSIONS_READ}),
}
