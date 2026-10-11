"""Abgabebox: Teilnehmernamen nach der Identitätsvereinheitlichung aus app_user lesen.

0108_unified_participants hat die Tabelle participant entfernt - und mit ihr die
spaltenweisen SELECT-Grants der restricted Rolle hocx_abgabebox (id, public_id,
first_name, last_name, display_name). Ohne diesen Grant scheitert die öffentliche
Abgabeseite bei Abgaben mit Teilnehmer-Elementen. Der Grant folgt demselben minimalen
Spalten-Muster wie zuvor (siehe 0090_abgabebox_quota_grant.py): bewusst kein email,
password_hash, external_identity_json oder andere Kontodaten.

Revision ID: 0109_abgabebox_participant_grant
Revises: 0108_unified_participants
Create Date: 2026-10-11
"""

from alembic import op

revision = "0109_abgabebox_participant_grant"
down_revision = "0108_unified_participants"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"
COLUMNS = "id, public_id, first_name, last_name, display_name"


def upgrade() -> None:
    op.execute(f"GRANT SELECT ({COLUMNS}) ON TABLE app_user TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ({COLUMNS}) ON TABLE app_user FROM {ABGABEBOX_ROLE}")
