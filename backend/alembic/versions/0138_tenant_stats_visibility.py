"""Statistik je Person nur für Berechtigte (Datenschutz-Audit PRIV-001)

Bussen und Anwesenheit je Person sehen in der Statistik standardmässig nur Schreibende, Kassier und
Admins; Leser sehen ihre eigene Zeile. Ein Mandant kann die Ranglisten mit diesem Schalter
ausdrücklich für alle Mitglieder freigeben.

Revision ID: 0138_tenant_stats_visibility
Revises: 0137_template_fine_tariff
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0138_tenant_stats_visibility"
down_revision = "0137_template_fine_tariff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("statistics_per_person_public", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )


def downgrade() -> None:
    op.drop_column("tenant", "statistics_per_person_public")
