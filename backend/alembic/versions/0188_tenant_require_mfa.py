"""MFA-Pflicht je Mandant (tenant.require_mfa).

Ein Vereins-Admin (access.manage) kann MFA für alle Logins seiner Organisation verlangen. Ist die
Pflicht an, löst die Session eines Kontos ohne MFA-Faktor nicht mehr auf
(app/core/security.py::get_optional_current_user, Fehler 403 «mfa_setup_required»); beim
nächsten Login führt der bestehende Ablauf direkt in die Einrichtung
(mfa_service.prepare_login, status «setup_required»). Standard: aus, bestehende Mandanten
ändern sich nicht.

Keine neue Tabelle und keine neue Berechtigung (Umschalten: access.manage).

Revision ID: 0188_tenant_require_mfa
Revises: 0185_document_page_fingerprints
Create Date: 2026-11-18
"""

from alembic import op

revision = "0188_tenant_require_mfa"
# 0186/0187 entstehen parallel und werden beim Zusammenführen davor eingehängt.
down_revision = "0185_document_page_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN IF NOT EXISTS require_mfa boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS require_mfa")
