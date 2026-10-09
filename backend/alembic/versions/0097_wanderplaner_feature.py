"""Wanderplaner-Anbindung in der hocX-Datenbank: Feature-Katalog, GPS-Metadaten der Fotos und
ein automatisches Fotoalbum pro Wandertour.

Die Touren selbst, das Wegenetz und die Umgebungsdaten liegen seit der Auslagerung im
Wanderplaner-Service mit eigener Datenbank (wanderplaner-backend/, dort
alembic/versions/0001_initial.py). Die hocX-Datenbank braucht deshalb weder PostGIS noch
pgRouting und bleibt auf postgres:16.

- 'wanderplaner' kommt nur in den Feature-Katalog, ohne Vorbelegung fuer bestehende
  Mandanten - wie 'abgabebox' ein Opt-in, das ein Platform-Admin pro Mandant freischaltet.
- stored_file.gps_*: aus EXIF gelesen (photo_tour_link_service.extract_gps), Grundlage fuer
  den Abgleich Foto -> Tour.
- photo_album.hiking_tour_public_id: verweist ohne Fremdschluessel auf die Tour im Service
  (andere Datenbank). Alben verschwundener Touren entfernt der naechste Abgleich.

Revision ID: 0097_wanderplaner_feature
Revises: 0096_album_item_share_pending
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0097_wanderplaner_feature"
down_revision = "0096_album_item_share_pending"
branch_labels = None
depends_on = None

# Bestehende Feldbedingungen bleiben für die bisherigen Albumarten erhalten.
OLD_FIELDS = """(kind = 'manual' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR
(kind = 'cycle' AND cycle_config_id IS NOT NULL AND cycle_year IS NOT NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR
(kind = 'submission' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NULL) OR
(kind = 'submission_element' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NOT NULL)"""


def upgrade() -> None:
    op.execute(
        "INSERT INTO feature (code, name, description) VALUES ("
        "'wanderplaner', 'Wanderplaner', "
        "'Planung von Wanderungen mit Routing, Marschzeit und Kartendruck (Schweiz/Liechtenstein)'"
        ")"
    )

    op.add_column("stored_file", sa.Column("gps_analyzed_at", sa.DateTime(timezone=True)))
    op.add_column("stored_file", sa.Column("gps_latitude", sa.Float()))
    op.add_column("stored_file", sa.Column("gps_longitude", sa.Float()))

    op.add_column("photo_album", sa.Column("hiking_tour_public_id", postgresql.UUID(as_uuid=True)))
    op.drop_constraint("ck_photo_album_kind", "photo_album", type_="check")
    op.drop_constraint("ck_photo_album_kind_fields", "photo_album", type_="check")
    op.create_check_constraint(
        "ck_photo_album_kind", "photo_album", "kind IN ('manual', 'cycle', 'submission', 'submission_element', 'hiking_tour')"
    )
    op.create_check_constraint(
        "ck_photo_album_kind_fields",
        "photo_album",
        f"(({OLD_FIELDS}) AND hiking_tour_public_id IS NULL) OR "
        "(kind = 'hiking_tour' AND hiking_tour_public_id IS NOT NULL AND cycle_config_id IS NULL AND cycle_year IS NULL "
        "AND submission_assignment_id IS NULL AND submission_element_ref IS NULL)",
    )
    op.create_index(
        "uq_photo_album_hiking_tour",
        "photo_album",
        ["tenant_id", "hiking_tour_public_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'hiking_tour'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM photo_album WHERE kind = 'hiking_tour'")
    op.drop_index("uq_photo_album_hiking_tour", table_name="photo_album")
    op.drop_constraint("ck_photo_album_kind_fields", "photo_album", type_="check")
    op.drop_constraint("ck_photo_album_kind", "photo_album", type_="check")
    op.create_check_constraint("ck_photo_album_kind", "photo_album", "kind IN ('manual', 'cycle', 'submission', 'submission_element')")
    op.create_check_constraint("ck_photo_album_kind_fields", "photo_album", OLD_FIELDS)
    op.drop_column("photo_album", "hiking_tour_public_id")
    op.drop_column("stored_file", "gps_longitude")
    op.drop_column("stored_file", "gps_latitude")
    op.drop_column("stored_file", "gps_analyzed_at")
    op.execute("DELETE FROM tenant_feature WHERE feature_code = 'wanderplaner'")
    op.execute("DELETE FROM feature WHERE code = 'wanderplaner'")
