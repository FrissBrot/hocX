"""GPS-Metadaten und ein automatisches Album pro Wandertour."""
import sqlalchemy as sa
from alembic import op

revision = '0104_photo_tour_link'
down_revision = '0103_waypoint_environment_names'
branch_labels = None
depends_on = None

# Bestehende Feldbedingungen bleiben für die bisherigen Albumarten erhalten.
OLD_FIELDS = """(kind = 'manual' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR
(kind = 'cycle' AND cycle_config_id IS NOT NULL AND cycle_year IS NOT NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR
(kind = 'submission' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NULL) OR
(kind = 'submission_element' AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NOT NULL)"""


def upgrade():
    op.add_column('stored_file', sa.Column('gps_analyzed_at', sa.DateTime(timezone=True)))
    op.add_column('stored_file', sa.Column('gps_latitude', sa.Float()))
    op.add_column('stored_file', sa.Column('gps_longitude', sa.Float()))
    op.add_column('photo_album', sa.Column('hiking_tour_id', sa.BigInteger()))
    op.create_foreign_key('fk_photo_album_hiking_tour', 'photo_album', 'hiking_tour', ['hiking_tour_id'], ['id'], ondelete='CASCADE')
    op.drop_constraint('ck_photo_album_kind', 'photo_album', type_='check')
    op.drop_constraint('ck_photo_album_kind_fields', 'photo_album', type_='check')
    op.create_check_constraint('ck_photo_album_kind', 'photo_album', "kind IN ('manual', 'cycle', 'submission', 'submission_element', 'hiking_tour')")
    op.create_check_constraint('ck_photo_album_kind_fields', 'photo_album', f"(({OLD_FIELDS}) AND hiking_tour_id IS NULL) OR (kind = 'hiking_tour' AND hiking_tour_id IS NOT NULL AND cycle_config_id IS NULL AND cycle_year IS NULL AND submission_assignment_id IS NULL AND submission_element_ref IS NULL)")
    op.create_index('uq_photo_album_hiking_tour', 'photo_album', ['tenant_id', 'hiking_tour_id'], unique=True, postgresql_where=sa.text("kind = 'hiking_tour'"))


def downgrade():
    op.execute("DELETE FROM photo_album WHERE kind = 'hiking_tour'")
    op.drop_index('uq_photo_album_hiking_tour', table_name='photo_album')
    op.drop_constraint('ck_photo_album_kind_fields', 'photo_album', type_='check')
    op.drop_constraint('ck_photo_album_kind', 'photo_album', type_='check')
    op.create_check_constraint('ck_photo_album_kind', 'photo_album', "kind IN ('manual', 'cycle', 'submission', 'submission_element')")
    op.create_check_constraint('ck_photo_album_kind_fields', 'photo_album', OLD_FIELDS)
    op.drop_constraint('fk_photo_album_hiking_tour', 'photo_album', type_='foreignkey')
    op.drop_column('photo_album', 'hiking_tour_id')
    op.drop_column('stored_file', 'gps_longitude')
    op.drop_column('stored_file', 'gps_latitude')
    op.drop_column('stored_file', 'gps_analyzed_at')
