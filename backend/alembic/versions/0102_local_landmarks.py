"""Lokale OSM-Umgebungsdaten für die automatische Marschkarte."""
from alembic import op

revision = '0102_local_landmarks'
down_revision = '0101_wanderplaner_reconnaissance'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE hiking_landmark (
        osm_type text NOT NULL, osm_id bigint NOT NULL,
        tags jsonb NOT NULL, nodes bigint[] NOT NULL DEFAULT '{}',
        geom geometry(Geometry,2056) NOT NULL,
        PRIMARY KEY(osm_type, osm_id))''')
    op.execute('CREATE INDEX hiking_landmark_geom_idx ON hiking_landmark USING gist(geom)')
    op.execute('''CREATE TABLE hiking_landmark_import (
        id integer PRIMARY KEY CHECK(id=1), imported_at timestamptz NOT NULL DEFAULT now(),
        source text NOT NULL, feature_count integer NOT NULL)''')
    op.execute('GRANT SELECT ON hiking_landmark, hiking_landmark_import TO hocx_app')


def downgrade():
    op.execute('DROP TABLE hiking_landmark_import')
    op.execute('DROP TABLE hiking_landmark')
