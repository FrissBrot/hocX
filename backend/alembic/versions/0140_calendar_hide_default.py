"""Kalender-Feeds übertragen standardmässig nur Titel und Datum (Datenschutz-Audit PRIV-018)

Nur der Standard für neue Feeds ändert sich; bestehende Abos behalten ihre Einstellung.

Revision ID: 0140_calendar_hide_default
Revises: 0139_error_log_actor_ids
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0140_calendar_hide_default"
down_revision = "0139_error_log_actor_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("calendar_feed", "hide_details", server_default=sa.text("true"))


def downgrade() -> None:
    op.alter_column("calendar_feed", "hide_details", server_default=sa.text("false"))
