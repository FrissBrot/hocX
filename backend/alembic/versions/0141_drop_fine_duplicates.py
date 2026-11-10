"""Prüfkopie zusammengeführter Bussen entfernen (Datenschutz-Audit PRIV-011)

Migration 0116 hat doppelte Bussen zusammengeführt und die entfernten Zeilen zur Kontrolle nach
attendance_fine_merged_duplicate kopiert - mit Namen, ohne Bezug zur Person und ohne Frist. Die
Anwendung liest die Tabelle nie; die Zusammenführung ist seit 1.1.x abgeschlossen. Wer die Kopie
noch prüfen will, sichert sie vor dem Update selbst, z. B.
``\\copy attendance_fine_merged_duplicate TO 'duplikate.csv' CSV HEADER``.

Revision ID: 0141_drop_fine_duplicates
Revises: 0140_calendar_hide_default
Create Date: 2026-10-21
"""

from alembic import op

revision = "0141_drop_fine_duplicates"
down_revision = "0140_calendar_hide_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attendance_fine_merged_duplicate")


def downgrade() -> None:
    # Die Inhalte sind gelöscht; nur die leere Struktur wird für 0116-Downgrades wiederhergestellt.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_fine_merged_duplicate AS
        SELECT af.*, NULL::bigint AS merged_into_id, now() AS merged_at
        FROM attendance_fine af
        WITH NO DATA
        """
    )
