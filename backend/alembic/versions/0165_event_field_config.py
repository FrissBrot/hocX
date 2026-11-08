"""Mandanten-Einstellung für die Spezialfelder der Termine: eigener Name (Alias) und Ausblenden.

``tenant.event_field_config_json`` = {"<feld>": {"label": "...", "hidden": true}} für die Felder
spezial1_ids..spezial3_ids und spezial_text1..spezial_text3 (app/schemas/event_field_config.py).
Leer = Standardnamen, nichts ausgeblendet. Liegt in der Mandantenzeile selbst (RLS wie tenant).

Revision ID: 0165_event_field_config
Revises: 0164_submission_todo_public_ref
Create Date: 2026-11-08
"""

from alembic import op

revision = "0165_event_field_config"
down_revision = "0164_submission_todo_public_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN IF NOT EXISTS event_field_config_json JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS event_field_config_json")
