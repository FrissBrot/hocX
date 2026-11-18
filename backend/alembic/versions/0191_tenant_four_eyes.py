"""Vier-Augen-Prinzip für Protokolle (Plan «Berechtigungen», Phase 3; Entscheid 18.11.2026).

``tenant.four_eyes_protocols`` (Standard aus): an = wer ein Protokoll verfasst hat
(``protocol.created_by``), darf es nicht selbst abschliessen; abschliessen braucht ausserdem das
Recht ``meetings.approve``. Umschalten: settings.manage (Zugriff › Sicherheit).

Revision ID: 0191_tenant_four_eyes
Revises: 0190_permission_catalog_v2
Create Date: 2026-11-18
"""

from alembic import op

revision = "0191_tenant_four_eyes"
down_revision = "0190_permission_catalog_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.tenant ADD COLUMN four_eyes_protocols boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE public.tenant DROP COLUMN IF EXISTS four_eyes_protocols")
