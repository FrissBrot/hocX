"""Teilnehmer und Login-Konten bilden eine gemeinsame Identität.

Die bestehende app_user-ID bleibt für Authentifizierung und Audit erhalten. Alle
Teilnehmer-Verweise (einschliesslich JSON-Snapshots) werden auf diese ID umgestellt.
Die alte participant-Tabelle und die Schattenkonto-Metadaten entfallen.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0108_unified_participants"
down_revision = "0107_system_monitoring"
branch_labels = None
depends_on = None


def _remap(value, ids, public_ids, key=""):
    if isinstance(value, dict):
        return {
            k: ({name: _remap(pid, ids, public_ids, "participant_id") for name, pid in v.items()}
                if k == "participant_name_overrides" and isinstance(v, dict)
                else _remap(v, ids, public_ids, k))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_remap(v, ids, public_ids, key[:-1] if key.endswith("_ids") else key) for v in value]
    if isinstance(value, str) and value.lower() in public_ids:
        return public_ids[value.lower()]
    if key.endswith("participant_id") or key in {"participant", "organizer_id", "leadership_id", "spezial1_id", "spezial2_id", "spezial3_id"}:
        if isinstance(value, int):
            return ids.get(value, value)
        if isinstance(value, str) and value.isdigit():
            return str(ids.get(int(value), int(value)))
    return value


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column("app_user", sa.Column("login_enabled", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column("app_user", sa.Column("joined_at", sa.Date()))
    op.add_column("app_user", sa.Column("left_at", sa.Date()))
    for column in ("first_name", "last_name", "email", "password_hash"):
        op.alter_column("app_user", column, nullable=True)
    for constraint in sa.inspect(conn).get_unique_constraints("app_user"):
        if constraint["column_names"] == ["email"]:
            op.drop_constraint(constraint["name"], "app_user", type_="unique")
    conn.execute(sa.text("""
        UPDATE app_user SET login_enabled = COALESCE((external_identity_json->>'login_enabled')::boolean, TRUE);
        UPDATE app_user u SET first_name=p.first_name, last_name=p.last_name,
            display_name=p.display_name, email=CASE WHEN u.login_enabled THEN u.email ELSE p.email END, is_active=p.is_active,
            joined_at=p.joined_at, left_at=p.left_at
        FROM participant p WHERE p.app_user_id=u.id;
        UPDATE app_user SET email=NULL, password_hash=NULL WHERE NOT login_enabled AND email LIKE '%@participants.hocx.local';
        UPDATE app_user SET email=lower(trim(email)) WHERE login_enabled;
        UPDATE app_user SET password_hash=NULL WHERE NOT login_enabled;
        UPDATE app_user SET external_identity_json = (CASE WHEN external_identity_json->>'source'='participant_auto' THEN external_identity_json - 'source' ELSE external_identity_json END) - 'participant_email' - 'login_enabled' - 'merged_user_ids';
    """))
    # Historische unverbundene Teilnehmer erhalten jetzt direkt eine Identität.
    unlinked = conn.execute(sa.text("SELECT * FROM participant WHERE app_user_id IS NULL ORDER BY id")).mappings().all()
    reader_role = conn.scalar(sa.text("SELECT id FROM role WHERE code='reader'"))
    for row in unlinked:
        user_id = conn.scalar(sa.text("""
            INSERT INTO app_user (public_id,tenant_id,role_id,first_name,last_name,display_name,email,
                is_active,joined_at,left_at,login_enabled,created_at,updated_at)
            VALUES (:public_id,:tenant_id,:role_id,:first_name,:last_name,:display_name,:email,
                :is_active,:joined_at,:left_at,FALSE,:created_at,:updated_at) RETURNING id
        """), {**row, "role_id": reader_role})
        conn.execute(sa.text("UPDATE participant SET app_user_id=:uid WHERE id=:pid"), {"uid":user_id,"pid":row["id"]})
    rows = conn.execute(sa.text("SELECT p.id,p.public_id,p.app_user_id,u.public_id AS user_public_id FROM participant p JOIN app_user u ON u.id=p.app_user_id")).mappings().all()
    ids = {r["id"]: r["app_user_id"] for r in rows}
    public_ids = {str(r["public_id"]): str(r["user_public_id"]) for r in rows}
    inspector = sa.inspect(conn)
    # Alle echten FKs werden vor dem ID-Wechsel abgenommen und danach neu erstellt.
    for table in inspector.get_table_names():
        if table == "participant":
            continue
        for fk in inspector.get_foreign_keys(table):
            if fk["referred_table"] != "participant":
                continue
            column = fk["constrained_columns"][0]
            op.drop_constraint(fk["name"], table, type_="foreignkey")
            conn.execute(sa.text(f'UPDATE "{table}" t SET "{column}"=p.app_user_id FROM participant p WHERE t."{column}"=p.id'))
            op.create_foreign_key(fk["name"], table, "app_user", [column], ["id"], ondelete=fk["options"].get("ondelete"))
    # JSONB enthält Teilnehmer-IDs in Anwesenheit, Listen, Verantwortlichen und Importentwürfen.
    metadata = sa.MetaData()
    for table_name in inspector.get_table_names():
        if table_name == "participant":
            continue
        columns = inspector.get_columns(table_name)
        json_names = [c["name"] for c in columns if isinstance(c["type"], sa.dialects.postgresql.JSONB)]
        primary_keys = inspector.get_pk_constraint(table_name)["constrained_columns"]
        if not json_names or not primary_keys:
            continue
        table = sa.Table(table_name, metadata, autoload_with=conn)
        for row in conn.execute(sa.select(table)).mappings():
            changed = {}
            for name in json_names:
                remapped = _remap(row[name], ids, public_ids, name)
                if remapped != row[name]:
                    changed[name] = remapped
            if changed:
                conn.execute(table.update().where(*(table.c[k] == row[k] for k in primary_keys)).values(**changed))
    op.drop_table("participant")
    op.create_index("uq_app_user_login_email", "app_user", ["email"], unique=True, postgresql_where=sa.text("login_enabled"))
    op.create_check_constraint("ck_app_user_login_credentials", "app_user", "NOT login_enabled OR (email IS NOT NULL AND email <> '' AND password_hash IS NOT NULL)")


def downgrade() -> None:
    raise RuntimeError("Die Identitätsvereinheitlichung erfordert zur Rückkehr ein Backup vor Migration 0108.")
