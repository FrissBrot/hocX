"""Bild-Metadaten: geschätztes Aufnahmedatum, GPS, Kamera und Herkunft der Werte.

Rein additiv (nur neue, nullable Spalten bzw. Spalten mit Default) - bestehende Datensätze
bleiben unverändert gültig. Keine Daten werden umgeschrieben; fehlende Werte älterer Bilder
füllt der gezielt aufrufbare Backfill (app/scripts/backfill_image_metadata.py) nach.

stored_file:
- estimated_taken_on: vom Benutzer geschätztes Aufnahmedatum als reines Kalenderdatum (DATE,
  bewusst ohne Uhrzeit/Zeitzone), getrennt von exif_taken_at (echtes Aufnahmedatum) und
  created_at (Uploaddatum). estimated_taken_set_at/_by halten fest, wann/von wem.
- exif_taken_offset: Zeitzonen-Offset aus EXIF OffsetTimeOriginal ("+02:00"), falls vorhanden.
  exif_taken_at speichert unverändert die lokale Uhrzeit der Kamera (Konvention seit 0083),
  der Offset ergänzt sie nur.
- exif_taken_source: Herkunft von exif_taken_at ("server", "client", "backfill").
- gps_*: Koordinaten (WGS84, Süd/West negativ), Höhe in m, Blickrichtung in Grad,
  horizontale Genauigkeit in m, GPS-Zeitstempel (UTC) und Herkunft.
- camera_make/camera_model/orientation: Kamera und EXIF-Ausrichtung.
- metadata_scanned_at/metadata_scan_status: Ergebnis der letzten serverseitigen Analyse
  (Neu-Upload oder Backfill) - macht den Backfill fortsetzbar und wiederholbar.

gallery_upload_job:
- estimated_taken_on: im Upload-Popup angegebenes Schätzdatum für Bilder ohne Aufnahmedatum.
- file_hints: clientseitig extrahierte Metadaten je SHA-256 (nur Hinweise, siehe
  image_metadata_service - werden nur angewendet, wenn der serverseitig berechnete Hash passt).
- file_results: Ergebnis je Datei (uploaded/skipped/metadata_updated/failed) für die
  Upload-Ergebnisanzeige.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0113_image_capture_metadata"
down_revision = "0112_protocol_todos_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stored_file", sa.Column("estimated_taken_on", sa.Date(), nullable=True))
    op.add_column("stored_file", sa.Column("estimated_taken_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "stored_file",
        sa.Column("estimated_taken_set_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("stored_file", sa.Column("exif_taken_offset", sa.Text(), nullable=True))
    op.add_column("stored_file", sa.Column("exif_taken_source", sa.Text(), nullable=True))
    op.add_column("stored_file", sa.Column("gps_latitude", sa.Float(), nullable=True))
    op.add_column("stored_file", sa.Column("gps_longitude", sa.Float(), nullable=True))
    op.add_column("stored_file", sa.Column("gps_altitude_m", sa.Float(), nullable=True))
    op.add_column("stored_file", sa.Column("gps_direction_deg", sa.Float(), nullable=True))
    op.add_column("stored_file", sa.Column("gps_accuracy_m", sa.Float(), nullable=True))
    op.add_column("stored_file", sa.Column("gps_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stored_file", sa.Column("gps_source", sa.Text(), nullable=True))
    op.add_column("stored_file", sa.Column("camera_make", sa.Text(), nullable=True))
    op.add_column("stored_file", sa.Column("camera_model", sa.Text(), nullable=True))
    op.add_column("stored_file", sa.Column("orientation", sa.SmallInteger(), nullable=True))
    op.add_column("stored_file", sa.Column("metadata_scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stored_file", sa.Column("metadata_scan_status", sa.Text(), nullable=True))

    op.create_check_constraint(
        "ck_stored_file_gps_pair",
        "stored_file",
        "(gps_latitude IS NULL) = (gps_longitude IS NULL)",
    )
    op.create_check_constraint(
        "ck_stored_file_gps_range",
        "stored_file",
        "gps_latitude IS NULL OR (gps_latitude BETWEEN -90 AND 90 AND gps_longitude BETWEEN -180 AND 180)",
    )
    op.create_check_constraint(
        "ck_stored_file_gps_direction",
        "stored_file",
        "gps_direction_deg IS NULL OR (gps_direction_deg >= 0 AND gps_direction_deg < 360)",
    )
    op.create_check_constraint(
        "ck_stored_file_metadata_source",
        "stored_file",
        "(exif_taken_source IS NULL OR exif_taken_source IN ('server', 'client', 'backfill'))"
        " AND (gps_source IS NULL OR gps_source IN ('server', 'client', 'backfill'))",
    )
    # Kartenansicht (später) und Backfill-Kandidaten.
    op.create_index(
        "idx_stored_file_tenant_gps",
        "stored_file",
        ["tenant_id"],
        postgresql_where=sa.text("gps_latitude IS NOT NULL"),
    )
    op.create_index(
        "idx_stored_file_metadata_backfill",
        "stored_file",
        ["id"],
        postgresql_where=sa.text("metadata_scanned_at IS NULL AND mime_type LIKE 'image/%'"),
    )

    op.add_column("gallery_upload_job", sa.Column("estimated_taken_on", sa.Date(), nullable=True))
    op.add_column(
        "gallery_upload_job",
        sa.Column("file_hints", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "gallery_upload_job",
        sa.Column("file_results", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("gallery_upload_job", "file_results")
    op.drop_column("gallery_upload_job", "file_hints")
    op.drop_column("gallery_upload_job", "estimated_taken_on")
    op.drop_index("idx_stored_file_metadata_backfill", table_name="stored_file")
    op.drop_index("idx_stored_file_tenant_gps", table_name="stored_file")
    for name in ("ck_stored_file_metadata_source", "ck_stored_file_gps_direction", "ck_stored_file_gps_range", "ck_stored_file_gps_pair"):
        op.drop_constraint(name, "stored_file", type_="check")
    for column in (
        "metadata_scan_status", "metadata_scanned_at", "orientation", "camera_model", "camera_make",
        "gps_source", "gps_timestamp", "gps_accuracy_m", "gps_direction_deg", "gps_altitude_m",
        "gps_longitude", "gps_latitude", "exif_taken_source", "exif_taken_offset",
        "estimated_taken_set_by", "estimated_taken_set_at", "estimated_taken_on",
    ):
        op.drop_column("stored_file", column)
