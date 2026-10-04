"""Freigabe-Links: pro Link waehlbar, welche Foto-Metadaten oeffentlich mitgehen.

share_location / share_capture_date / share_camera steuern, was photo_metadata_privacy.py beim
oeffentlichen Download (Einzeldatei, Lightbox, ZIP) aus den Fotos entfernt. Bestehende Links
bekommen dieselben Vorgaben wie neue: Aufnahmedatum ja, Standort (GPS) und Kamera/Geraet nein -
bisher gingen alle Metadaten ungefiltert raus, der Standort ist das heikelste davon.

Revision ID: 0100_share_link_metadata_privacy
Revises: 0099_submission_auto_close
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0100_share_link_metadata_privacy"
down_revision = "0099_submission_auto_close"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("share_link", sa.Column("share_location", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("share_link", sa.Column("share_capture_date", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("share_link", sa.Column("share_camera", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("share_link", "share_camera")
    op.drop_column("share_link", "share_capture_date")
    op.drop_column("share_link", "share_location")
