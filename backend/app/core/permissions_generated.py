# GENERATED FILE - do not edit by hand. Source of truth: permissions/catalog.json (repo root).
# Regenerate with: python3 scripts/sync-permission-catalog.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class P(StrEnum):
    MEETINGS_READ = "meetings.read"
    MEETINGS_READ_DRAFTS = "meetings.read_drafts"
    MEETINGS_EDIT = "meetings.edit"
    TEMPLATES_EDIT = "templates.edit"
    TEMPLATES_MANAGE = "templates.manage"
    PARTICIPANTS_MANAGE = "participants.manage"
    FINANCES_READ = "finances.read"
    FINANCES_MANAGE = "finances.manage"
    REPORTS_PERSONAL = "reports.personal"
    FILES_MANAGE = "files.manage"
    SUBMISSIONS_READ = "submissions.read"
    SUBMISSIONS_MANAGE = "submissions.manage"
    SETTINGS_MANAGE = "settings.manage"
    ACCESS_MANAGE = "access.manage"
    DATA_EXPORT = "data.export"


@dataclass(frozen=True)
class PermissionDef:
    area: str
    feature: str | None
    requires_mfa: bool
    implies: tuple[P, ...]


AREAS: tuple[str, ...] = ("meetings", "templates", "participants", "finances", "reports", "files", "submissions", "administration",)

CATALOG: dict[P, PermissionDef] = {
    P.MEETINGS_READ: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=()),
    P.MEETINGS_READ_DRAFTS: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ,)),
    P.MEETINGS_EDIT: PermissionDef(area="meetings", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ_DRAFTS,)),
    P.TEMPLATES_EDIT: PermissionDef(area="templates", feature=None, requires_mfa=False, implies=(P.MEETINGS_READ,)),
    P.TEMPLATES_MANAGE: PermissionDef(area="templates", feature=None, requires_mfa=False, implies=(P.TEMPLATES_EDIT,)),
    P.PARTICIPANTS_MANAGE: PermissionDef(area="participants", feature=None, requires_mfa=False, implies=()),
    P.FINANCES_READ: PermissionDef(area="finances", feature="finance", requires_mfa=False, implies=()),
    P.FINANCES_MANAGE: PermissionDef(area="finances", feature="finance", requires_mfa=False, implies=(P.FINANCES_READ,)),
    P.REPORTS_PERSONAL: PermissionDef(area="reports", feature=None, requires_mfa=False, implies=()),
    P.FILES_MANAGE: PermissionDef(area="files", feature=None, requires_mfa=False, implies=()),
    P.SUBMISSIONS_READ: PermissionDef(area="submissions", feature="abgabebox", requires_mfa=False, implies=()),
    P.SUBMISSIONS_MANAGE: PermissionDef(area="submissions", feature="abgabebox", requires_mfa=False, implies=(P.SUBMISSIONS_READ,)),
    P.SETTINGS_MANAGE: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
    P.ACCESS_MANAGE: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
    P.DATA_EXPORT: PermissionDef(area="administration", feature=None, requires_mfa=True, implies=()),
}

# Standardrollen je Mandant (tenant_role.system_key). "admin" hat immer alle Permissions, auch
# künftig neu hinzukommende - beim Laden ausgewertet, nicht über tenant_role_permission.
SYSTEM_ROLE_KEYS: tuple[str, ...] = ('admin', 'writer', 'kassier', 'reader')
SYSTEM_ROLE_PERMISSIONS: dict[str, frozenset[P]] = {
    "admin": frozenset(P),
    "writer": frozenset({P.MEETINGS_READ, P.MEETINGS_READ_DRAFTS, P.MEETINGS_EDIT, P.TEMPLATES_EDIT, P.PARTICIPANTS_MANAGE, P.FINANCES_READ, P.REPORTS_PERSONAL, P.FILES_MANAGE, P.SUBMISSIONS_READ, P.SUBMISSIONS_MANAGE}),
    "kassier": frozenset({P.MEETINGS_READ, P.MEETINGS_READ_DRAFTS, P.FINANCES_READ, P.FINANCES_MANAGE, P.REPORTS_PERSONAL, P.SUBMISSIONS_READ}),
    "reader": frozenset({P.MEETINGS_READ, P.FINANCES_READ, P.SUBMISSIONS_READ}),
}
