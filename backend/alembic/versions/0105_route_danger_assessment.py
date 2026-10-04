"""Gefahreneinschätzung: amtliche Kategorie je Leg-Teilabschnitt + kombinierte Geländeanalyse."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0105_route_danger_assessment'
down_revision = '0104_photo_tour_link'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('hiking_tour_route_leg', sa.Column('wanderweg_segments_json', postgresql.JSONB()))
    op.add_column('hiking_tour', sa.Column('terrain_danger_json', postgresql.JSONB()))
    op.add_column('hiking_tour', sa.Column('terrain_danger_computed_at', sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column('hiking_tour', 'terrain_danger_computed_at')
    op.drop_column('hiking_tour', 'terrain_danger_json')
    op.drop_column('hiking_tour_route_leg', 'wanderweg_segments_json')
