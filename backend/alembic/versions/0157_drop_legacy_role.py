"""Feste Rolle pro Konto entfernen (app_user.role_id, Tabelle role).

Seit 0156_rbac kommen die Rechte ausschliesslich aus user_role/tenant_role. Der Downgrade stellt
die alte Spalte verlustbehaftet wieder her: jedes Konto bekommt die höchste seiner
Standardrollen (admin > writer > kassier > reader), Konten nur mit eigenen Rollen werden reader.

Revision ID: 0157_drop_legacy_role
Revises: 0156_rbac
Create Date: 2026-10-26
"""

from alembic import op

revision = "0157_drop_legacy_role"
down_revision = "0156_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_app_user_tenant_role")
    op.execute("ALTER TABLE app_user DROP COLUMN role_id")
    op.execute("DROP TABLE role")


def downgrade() -> None:
    op.execute("CREATE TABLE role (id smallint PRIMARY KEY, code text NOT NULL UNIQUE, description text)")
    op.execute(
        "INSERT INTO role (id, code, description) VALUES "
        "(1, 'admin', 'Tenant administrator'), "
        "(2, 'writer', 'Workspace write access'), "
        "(3, 'reader', 'Read-only workspace access with PDF export'), "
        "(4, 'kassier', 'Reader access plus full finance and fines management')"
    )
    op.execute("GRANT SELECT ON role TO hocx_app")
    op.execute("ALTER TABLE app_user ADD COLUMN role_id smallint REFERENCES role(id) ON DELETE RESTRICT")
    op.execute(
        """
        UPDATE app_user u SET role_id = COALESCE((
            SELECT r.id
              FROM user_role ur
              JOIN tenant_role tr ON tr.id = ur.role_id
              JOIN role r ON r.code = tr.system_key
             WHERE ur.user_id = u.id
             ORDER BY array_position(ARRAY['admin', 'writer', 'kassier', 'reader'], tr.system_key)
             LIMIT 1
        ), 3)
        """
    )
    op.execute("ALTER TABLE app_user ALTER COLUMN role_id SET NOT NULL")
    op.execute("CREATE INDEX idx_app_user_tenant_role ON app_user (tenant_id, role_id)")
