"""add live-resolvable responsible-name snapshot fields to protocol_element

Supports "Verantwortlich"-Namen, die live aus einer verknuepften Listen-Zeile
nachgezogen werden, solange das Protokoll nicht abgeschlossen ist (siehe
responsible_label_service.py). section_name_snapshot bleibt unveraendert der
Fallback-/final-eingefrorene Wert.

Revision ID: 0042_protocol_live_responsible
Revises: 0041_global_oidc
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0042_protocol_live_responsible"
down_revision = "0041_global_oidc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocol_element", sa.Column("element_title_snapshot", sa.Text(), nullable=True))
    op.add_column("protocol_element", sa.Column("responsible_assignments_snapshot", JSONB, nullable=True))
    op.add_column("protocol_element", sa.Column("responsible_name_display_mode", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("protocol_element", "responsible_name_display_mode")
    op.drop_column("protocol_element", "responsible_assignments_snapshot")
    op.drop_column("protocol_element", "element_title_snapshot")
