"""Album-Freigabe an Partner-Mandanten: Standort (GPS) schaltbar (IMGMETA-007)

Neue Spalte photo_album_tenant_share.share_location, Standard true (Entscheidung: zwei
Mandanten, die ein Album teilen, vertrauen sich). Ist sie aus, bekommt der Partner Originale und
Downloads der Fotos dieses Albums ohne Standortdaten. Bestehende Freigaben erhalten den
Standardwert - an ihrem bisherigen Verhalten (Download mit GPS) ändert sich nichts.

Rein additiv; der Downgrade entfernt die Spalte.

Revision ID: 0118_album_share_location
Revises: 0117_imgmeta_merge_main
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0118_album_share_location"
down_revision = "0117_imgmeta_merge_main"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "photo_album_tenant_share",
        sa.Column("share_location", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("photo_album_tenant_share", "share_location")
