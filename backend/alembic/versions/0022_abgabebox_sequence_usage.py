"""abgabebox: grant USAGE on identity sequences to restricted role

Entdeckt beim Live-Test von Migration 0020/0021: anders als angenommen genuegt
INSERT-Recht auf eine Tabelle mit GENERATED [BY DEFAULT] AS IDENTITY-Spalte NICHT,
um implizit nextval() auf der zugehoerigen Sequenz aufzurufen - Postgres verlangt
dafuer explizites USAGE (oder SELECT/UPDATE) auf die Sequenz, genau wie bei einer
klassischen serial-Spalte. Ohne dieses Grant schlaegt jeder INSERT mit
"permission denied for sequence ..." fehl.

Revision ID: 0022_abgabebox_seq_usage
Revises: 0021_abgabebox_id_grant
Create Date: 2026-07-08
"""

from alembic import op

revision = "0022_abgabebox_seq_usage"
down_revision = "0021_abgabebox_id_grant"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"
SEQUENCES = ("stored_file_id_seq", "submission_upload_id_seq", "submission_upload_file_id_seq")


def upgrade() -> None:
    for sequence in SEQUENCES:
        op.execute(f"GRANT USAGE ON SEQUENCE {sequence} TO {ROLE_NAME}")


def downgrade() -> None:
    for sequence in SEQUENCES:
        op.execute(f"REVOKE USAGE ON SEQUENCE {sequence} FROM {ROLE_NAME}")
