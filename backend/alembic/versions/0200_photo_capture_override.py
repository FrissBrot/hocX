"""Fotos: korrigiertes Aufnahmedatum (Vorrang vor EXIF und Schätzung).

Die Bildmetadaten liegen in typisierten Spalten von stored_file (exif_taken_at,
estimated_taken_on, gps_* ...), nicht in einer JSON-Spalte - die Korrektur braucht deshalb
eigene Spalten. Rein additiv: bestehende Datensätze bleiben unverändert gültig, das
EXIF-Datum (exif_taken_at) und die Datei-Bytes werden nie umgeschrieben.

stored_file:
- capture_corrected_at: vom Benutzer korrigiertes Aufnahmedatum, gleiche Konvention wie
  exif_taken_at (lokale Kamerazeit, gespeichert als wäre sie UTC - "floating"). Ohne Uhrzeit
  steht technisch 12:00 drin, siehe capture_corrected_has_time.
- capture_corrected_has_time: wurde eine Uhrzeit angegeben? Steuert nur die Anzeige.
- capture_corrected_set_at/_by: wann/von wem (Audit-Log hält zusätzlich jede Aktion fest).

Priorität siehe backend/app/services/capture_date.py: korrigiert > EXIF > geschätzt > Upload.

Revision ID: 0200_photo_capture_override
Revises: 0199_stored_file_soft_delete
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0200_photo_capture_override"
down_revision = "0199_stored_file_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stored_file", sa.Column("capture_corrected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "stored_file",
        sa.Column("capture_corrected_has_time", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("stored_file", sa.Column("capture_corrected_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "stored_file",
        sa.Column(
            "capture_corrected_set_by",
            sa.BigInteger(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Ohne Datum gibt es keine Uhrzeit-Angabe.
    op.create_check_constraint(
        "ck_stored_file_capture_corrected_time",
        "stored_file",
        "capture_corrected_at IS NOT NULL OR capture_corrected_has_time = false",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stored_file_capture_corrected_time", "stored_file", type_="check")
    op.drop_column("stored_file", "capture_corrected_set_by")
    op.drop_column("stored_file", "capture_corrected_set_at")
    op.drop_column("stored_file", "capture_corrected_has_time")
    op.drop_column("stored_file", "capture_corrected_at")
