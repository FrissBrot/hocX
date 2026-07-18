"""abgabebox: grant SELECT(id) on stored_file to restricted role

Postgres verlangt fuer "INSERT ... RETURNING id" SELECT-Recht auf die
zurueckgegebene Spalte, auch wenn es sich um einen reinen INSERT handelt.
Der abgabebox-backend-Service (restricted Rolle hocx_abgabebox) braucht die neu
erzeugte stored_file.id, um sie in submission_upload_file zu verknuepfen - dafuer
genuegt SELECT auf die id-Spalte (keine sensiblen Felder wie storage_path/original_name).

Revision ID: 0021_abgabebox_stored_file_id_grant
Revises: 0020_abgabebox
Create Date: 2026-07-08
"""

from alembic import op

revision = "0021_abgabebox_id_grant"
down_revision = "0020_abgabebox"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"


def upgrade() -> None:
    op.execute(f"GRANT SELECT (id) ON stored_file TO {ROLE_NAME}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT (id) ON stored_file FROM {ROLE_NAME}")
