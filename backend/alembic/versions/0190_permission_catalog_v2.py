"""Neue Rechte und Rollen-Migration (Plan «Berechtigungen», Phase 3).

Zwölf neue Rechte (Katalog permissions/catalog.json): meetings.approve, todos.complete_own,
participants.read, participants.contacts, participants.export, fines.manage, files.read,
photos.read, photos.manage, sharing.public, submissions.review, activity.read.

Jede bestehende Rolle (auch selbst erstellte) bekommt sie nach app.services.permission_mapping:
wer die Fähigkeit schon hatte, behält sie unter dem neuen Recht; «eigene Pendenzen erledigen»
bekommen alle Rollen (Entscheid 18.11.2026). Die Standardrollen neuer Mandanten bekommen dieselben
Rechte (hocx_seed_tenant_roles neu, aus dem Katalog).

Probelauf vorher/nachher je Rolle: app.services.permission_mapping.report(db).
Reversibel: downgrade entfernt die neuen Rechte samt Zuordnungen und stellt die alte
Seed-Funktion wieder her (die alten Rechte bleiben unverändert).

Revision ID: 0190_permission_catalog_v2
Revises: 0189_stored_file_context
Create Date: 2026-11-18
"""


from alembic import op


revision = "0190_permission_catalog_v2"
down_revision = "0189_stored_file_context"
branch_labels = None
depends_on = None

# Feste Kopie aus app.services.permission_mapping (eine Migration ändert sich nie mehr, auch wenn
# der App-Code sich ändert; der Probelauf dort nutzt dieselbe Regel).
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
MAPPING = {
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

# Rechte der Standardrollen VOR dieser Migration (Stand 0156), für den Rückweg
OLD_SYSTEM_ROLES = {
    "writer": ["meetings.read", "meetings.read_drafts", "meetings.edit", "templates.edit", "participants.manage", "finances.read",
               "reports.personal", "files.manage", "submissions.read", "submissions.manage"],
    "kassier": ["meetings.read", "meetings.read_drafts", "finances.read", "finances.manage", "reports.personal", "submissions.read"],
    "reader": ["meetings.read", "finances.read", "submissions.read"],
}


def _quote(value: str) -> str:
    assert all(ch.isalnum() or ch in "._" for ch in value), value
    return "'" + value + "'"


def _seed_function(system_roles: dict[str, list[str]]) -> str:
    pairs = ", ".join(f"({_quote(role)}, {_quote(key)})" for role, keys in system_roles.items() for key in keys)
    return f"""
        CREATE OR REPLACE FUNCTION public.hocx_seed_tenant_roles(p_tenant_id bigint) RETURNS void
            LANGUAGE plpgsql
            SET search_path = public
        AS $$
        BEGIN
            INSERT INTO tenant_role (tenant_id, system_key)
            SELECT p_tenant_id, k FROM unnest(ARRAY['admin', 'writer', 'kassier', 'reader']) AS k
            ON CONFLICT DO NOTHING;
            INSERT INTO tenant_role_permission (role_id, permission_key)
            SELECT r.id, v.permission_key
              FROM tenant_role r
              JOIN (VALUES {pairs}) AS v(system_key, permission_key) ON v.system_key = r.system_key
             WHERE r.tenant_id = p_tenant_id
            ON CONFLICT DO NOTHING;
        END
        $$
    """  # sql-ok: feste Literale aus dieser Migration


def _new_system_roles() -> dict[str, list[str]]:
    """Standardrollen nach dieser Migration = alte Rechte + Mapping (wie permissions/catalog.json)."""
    result = {}
    for role, keys in OLD_SYSTEM_ROLES.items():
        added = {key for old, new in MAPPING.items() if old in keys for key in new}
        result[role] = sorted(set(keys) | added | set(FOR_EVERY_ROLE))
    return result


def upgrade() -> None:
    values = ", ".join(f"({_quote(key)})" for key in NEW_PERMISSIONS)
    op.execute(f"INSERT INTO permission (key) VALUES {values} ON CONFLICT DO NOTHING")  # sql-ok: feste Literale
    # Zuordnung für alle bestehenden Rollen (admin hat keine Zeilen = alle Rechte)
    for old, added in MAPPING.items():
        for key in added:
            op.execute(
                "INSERT INTO tenant_role_permission (role_id, permission_key) "
                f"SELECT DISTINCT p.role_id, {_quote(key)} FROM tenant_role_permission p "  # sql-ok: feste Literale
                f"WHERE p.permission_key = {_quote(old)} ON CONFLICT DO NOTHING"
            )
    for key in FOR_EVERY_ROLE:
        op.execute(
            "INSERT INTO tenant_role_permission (role_id, permission_key) "
            f"SELECT r.id, {_quote(key)} FROM tenant_role r WHERE r.system_key IS DISTINCT FROM 'admin' "  # sql-ok: feste Literale
            "ON CONFLICT DO NOTHING"
        )
    op.execute(_seed_function(_new_system_roles()))


def downgrade() -> None:
    keys = ", ".join(_quote(key) for key in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM tenant_role_permission WHERE permission_key IN ({keys})")  # sql-ok: feste Literale
    op.execute(f"DELETE FROM permission WHERE key IN ({keys})")  # sql-ok: feste Literale
    op.execute(_seed_function(OLD_SYSTEM_ROLES))
