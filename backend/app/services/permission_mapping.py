"""Rechte-Migration alt → neu (Plan «Berechtigungen», Phase 3, Migration 0190).

Neue Rechte bekommt genau, wer die entsprechende Fähigkeit schon hatte - niemand verliert oder
gewinnt etwas. Einzige bewusste Ausnahme (Entscheid 18.11.2026): «eigene Pendenzen erledigen»
bekommen ALLE Rollen inkl. Leser; ohne dieses Recht ist ein Benutzer read-only.

Die Standardrolle admin hat keine Zeilen (immer alle Rechte) und ist hier nicht betroffen.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

NEW_PERMISSIONS = (
    "meetings.approve",
    "todos.complete_own",
    "participants.read",
    "participants.contacts",
    "participants.export",
    "fines.manage",
    "files.read",
    "photos.read",
    "photos.manage",
    "sharing.public",
    "submissions.review",
    "activity.read",
)

# Wer das alte Recht hat, bekommt zusätzlich die neuen (heutige Fähigkeit, neu benannt/abgetrennt).
MAPPING: dict[str, tuple[str, ...]] = {
    # Protokolle abschliessen konnte, wer bearbeiten darf
    "meetings.edit": ("meetings.approve",),
    "participants.manage": ("participants.read", "participants.contacts"),
    # Datenauskunft für andere Personen verlangte data.export (nicht participants.manage)
    "data.export": ("participants.export",),
    "finances.manage": ("fines.manage",),
    "settings.manage": ("activity.read",),
    "files.manage": ("files.read", "photos.read", "photos.manage", "sharing.public"),
    "submissions.manage": ("submissions.review", "sharing.public"),
}
FOR_EVERY_ROLE = ("todos.complete_own",)


def mapped(old: set[str]) -> set[str]:
    """Rechte einer Rolle nach der Migration (ohne implies, wie gespeichert)."""
    result = set(old) | set(FOR_EVERY_ROLE)
    for key, added in MAPPING.items():
        if key in old:
            result |= set(added)
    return result


@dataclass
class RoleChange:
    tenant_id: int
    role_id: int
    role: str  # Name bzw. Standardschlüssel
    before: list[str]
    after: list[str]

    @property
    def added(self) -> list[str]:
        return sorted(set(self.after) - set(self.before))


def report(db: Session, *, tenant_id: int | None = None) -> list[RoleChange]:
    """Probelauf: je Rolle die Rechte vorher/nachher, ohne zu schreiben. Nach der Migration
    zeigt er keine Änderungen mehr (idempotent)."""
    rows = db.execute(
        text(
            """
            SELECT r.tenant_id, r.id, COALESCE(r.name, r.system_key, '') AS role,
                   COALESCE(array_agg(p.permission_key ORDER BY p.permission_key) FILTER (WHERE p.permission_key IS NOT NULL), '{}') AS keys
              FROM tenant_role r LEFT JOIN tenant_role_permission p ON p.role_id = r.id
             WHERE (r.system_key IS DISTINCT FROM 'admin')
               AND (CAST(:tenant_id AS bigint) IS NULL OR r.tenant_id = :tenant_id)
             GROUP BY r.tenant_id, r.id, r.name, r.system_key
             ORDER BY r.tenant_id, r.id
            """
        ),
        {"tenant_id": tenant_id},
    ).all()
    changes = []
    for row in rows:
        before = set(row.keys or [])
        after = mapped(before)
        changes.append(RoleChange(row.tenant_id, row.id, row.role, sorted(before), sorted(after)))
    return changes
