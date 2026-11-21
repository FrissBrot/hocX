"""Neue Mandanten-Berechtigung security.read (Admin-Redesign Phase E).

«Sicherheit & Anmeldungen» in den Mandanten-Einstellungen (Warnungen und Anmeldeaktivität der
eigenen Konten). User-Entscheid: nur die Standardrolle «admin». Die admin-Standardrolle hat
``all_permissions`` und deshalb keine Zeilen in ``tenant_role_permission`` (siehe 0190) - sie erhält
das neue Recht automatisch, auch für neue Mandanten über ``hocx_seed_tenant_roles``. Die Seed-Funktion
bleibt deshalb unverändert (writer/kassier/reader bekommen das Recht bewusst nicht). Eigene Rollen
können es danach über die Rollenverwaltung erhalten.

Revision ID: 0207_security_read
Revises: 0206_auth_hardening
Create Date: 2026-11-21
"""

from alembic import op

revision = "0207_security_read"
down_revision = "0206_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("INSERT INTO permission (key) VALUES ('security.read') ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.execute("DELETE FROM tenant_role_permission WHERE permission_key = 'security.read'")
    op.execute("DELETE FROM permission WHERE key = 'security.read'")
