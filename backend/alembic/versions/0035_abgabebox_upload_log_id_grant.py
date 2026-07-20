"""abgabebox: grant SELECT(id) on submission_upload_log to restricted role

Migration 0031 gab hocx_abgabebox nur INSERT auf submission_upload_log, aber
"INSERT ... RETURNING id" (das SQLAlchemy Core beim Insert automatisch anhaengt,
siehe implicit_returning) braucht zusaetzlich SELECT-Recht auf die id-Spalte -
exakt das gleiche Muster wie 0021 fuer stored_file. Ohne diesen Grant schlug
JEDER _log()-Aufruf im abgabebox-backend (public.py) mit InsufficientPrivilege
fehl, was durch das umschliessende try/except still verschluckt wurde - die
Upload-Log-Tabelle war seit 0031 faktisch leer.

Revision ID: 0035_abgabebox_log_id_grant
Revises: 0034_fine_collected_by
Create Date: 2026-07-20
"""

from alembic import op

revision = "0035_abgabebox_log_id_grant"
down_revision = "0034_fine_collected_by"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"


def upgrade() -> None:
    op.execute(f"GRANT SELECT (id) ON submission_upload_log TO {ROLE_NAME}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT (id) ON submission_upload_log FROM {ROLE_NAME}")
