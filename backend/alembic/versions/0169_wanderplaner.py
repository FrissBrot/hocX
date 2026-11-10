"""Wanderplaner-Anbindung in der hocX-Datenbank: Feature, Berechtigungen und ein automatisches
Fotoalbum pro Wandertour.

Die Touren selbst, das Wegenetz und die Umgebungsdaten liegen im Wanderplaner-Service mit eigener
Datenbank (wanderplaner-backend/, dort alembic/versions/0001_initial.py). Die hocX-Datenbank braucht
deshalb weder PostGIS noch pgRouting.

- Feature 'wanderplaner' (permissions/features.json): ein Opt-in, das ein Platform-Admin pro
  Mandant freischaltet - kein Bestandsschutz-Backfill (die Funktion gab es bisher nicht) und
  keine Planzuordnung.
- Berechtigungen hiking.read (alle Standardrollen) und hiking.manage (writer; admin hat immer
  alle): Tabelle permission, Standardrollen bestehender Mandanten und hocx_seed_tenant_roles für
  neue Mandanten (Stand 0156 plus diese beiden).
- photo_album.hiking_tour_public_id: verweist ohne Fremdschlüssel auf die Tour im Service (andere
  Datenbank). Alben verschwundener Touren entfernt der nächste Abgleich
  (services/photo_tour_link_service.py). GPS und Aufnahmedatum der Fotos kommen aus den
  bestehenden stored_file-Metadatenspalten (image_metadata_service).

Ersetzt die nie auf main gelaufene Branch-Revision 0097_wanderplaner_feature.

Revision ID: 0169_wanderplaner
Revises: 0168_s3_only
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0169_wanderplaner"
down_revision = "0168_s3_only"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = ("hiking.read", "hiking.manage")
NEW_ROLE_PERMISSIONS = {
    "writer": ("hiking.read", "hiking.manage"),
    "kassier": ("hiking.read",),
    "reader": ("hiking.read",),
}
# Standardrollen-Zuordnung für neue Mandanten: Stand 0156_rbac plus NEW_ROLE_PERMISSIONS.
BASE_ROLE_PERMISSIONS = {
    "writer": (
        "meetings.read", "meetings.read_drafts", "meetings.edit", "templates.edit", "participants.manage",
        "finances.read", "reports.personal", "files.manage", "submissions.read", "submissions.manage",
    ),
    "kassier": ("meetings.read", "meetings.read_drafts", "finances.read", "finances.manage", "reports.personal", "submissions.read"),
    "reader": ("meetings.read", "finances.read", "submissions.read"),
}

# Feldbedingungen der bisherigen Albumarten (0068_photo_album_auto).
OLD_FIELDS = """(kind = 'manual' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR
(kind = 'cycle' AND cycle_config_id IS NOT NULL AND cycle_year IS NOT NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR
(kind = 'submission' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NULL) OR
(kind = 'submission_element' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NOT NULL)"""


def _quote(value: str) -> str:
    # Nur feste Literale aus dieser Datei (keine Benutzereingaben).
    return "'" + value.replace("'", "''") + "'"


def _seed_function(role_permissions: dict[str, tuple[str, ...]]) -> str:
    pairs = ", ".join(f"({_quote(role)}, {_quote(key)})" for role, keys in role_permissions.items() for key in keys)
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


def upgrade() -> None:
    op.execute(
        "INSERT INTO feature (code, name, description) VALUES ("
        "'wanderplaner', 'Wanderplaner', "
        "'Planung von Wanderungen mit Routing, Marschzeit und Kartendruck (Schweiz/Liechtenstein)'"
        ") ON CONFLICT (code) DO NOTHING"
    )

    values = ", ".join(f"({_quote(key)})" for key in NEW_PERMISSIONS)
    op.execute(f"INSERT INTO permission (key) VALUES {values} ON CONFLICT DO NOTHING")  # sql-ok: feste Literale aus dieser Migration
    merged = {role: BASE_ROLE_PERMISSIONS[role] + NEW_ROLE_PERMISSIONS.get(role, ()) for role in BASE_ROLE_PERMISSIONS}
    op.execute(_seed_function(merged))
    pairs = ", ".join(f"({_quote(role)}, {_quote(key)})" for role, keys in NEW_ROLE_PERMISSIONS.items() for key in keys)
    op.execute(
        f"""
        INSERT INTO tenant_role_permission (role_id, permission_key)
        SELECT r.id, v.permission_key
          FROM tenant_role r
          JOIN (VALUES {pairs}) AS v(system_key, permission_key) ON v.system_key = r.system_key
        ON CONFLICT DO NOTHING
        """  # sql-ok: feste Literale aus dieser Migration
    )

    op.add_column("photo_album", sa.Column("hiking_tour_public_id", postgresql.UUID(as_uuid=True)))
    op.drop_constraint("ck_photo_album_kind", "photo_album", type_="check")
    op.drop_constraint("ck_photo_album_kind_fields", "photo_album", type_="check")
    op.create_check_constraint(
        "ck_photo_album_kind", "photo_album", "kind IN ('manual', 'cycle', 'submission', 'submission_element', 'hiking_tour')"
    )
    op.create_check_constraint(
        "ck_photo_album_kind_fields",
        "photo_album",
        f"(({OLD_FIELDS}) AND hiking_tour_public_id IS NULL) OR "
        "(kind = 'hiking_tour' AND hiking_tour_public_id IS NOT NULL AND cycle_config_id IS NULL AND cycle_year IS NULL "
        "AND submission_assignment_id IS NULL AND submission_element_ref IS NULL)",
    )
    op.create_index(
        "uq_photo_album_hiking_tour",
        "photo_album",
        ["tenant_id", "hiking_tour_public_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'hiking_tour'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM photo_album WHERE kind = 'hiking_tour'")
    op.drop_index("uq_photo_album_hiking_tour", table_name="photo_album")
    op.drop_constraint("ck_photo_album_kind_fields", "photo_album", type_="check")
    op.drop_constraint("ck_photo_album_kind", "photo_album", type_="check")
    op.create_check_constraint("ck_photo_album_kind", "photo_album", "kind IN ('manual', 'cycle', 'submission', 'submission_element')")
    op.create_check_constraint("ck_photo_album_kind_fields", "photo_album", OLD_FIELDS)
    op.drop_column("photo_album", "hiking_tour_public_id")

    op.execute(_seed_function(BASE_ROLE_PERMISSIONS))
    keys = ", ".join(_quote(key) for key in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM tenant_role_permission WHERE permission_key IN ({keys})")  # sql-ok: feste Literale aus dieser Migration
    op.execute(f"DELETE FROM permission WHERE key IN ({keys})")  # sql-ok: feste Literale aus dieser Migration

    op.execute("DELETE FROM tenant_feature WHERE feature_code = 'wanderplaner'")
    op.execute("DELETE FROM plan_feature WHERE feature_code = 'wanderplaner'")
    op.execute("DELETE FROM feature WHERE code = 'wanderplaner'")
