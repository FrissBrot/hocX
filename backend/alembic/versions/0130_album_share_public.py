"""Öffentliche Links bei Album-Freigaben: Erlaubnis je Seite

Security-Audit release/1.2.0 (SEC-002): Ein Partner konnte ein fremdes, geteiltes Album ohne
Zustimmung des Besitzers öffentlich verlinken, und Fotos eines Partners landeten in öffentlichen
Links des Besitzers. Jede Seite schützt jetzt ihre eigenen Fotos:

- partner_public_links (setzt der Besitzer): der Partner darf dieses Album öffentlich verlinken.
- partner_photos_public (setzt der Partner): seine Fotos in diesem Album dürfen in öffentlichen
  Links erscheinen.

Beide standardmässig an (gemeinsame Alben sind zum gegenseitigen Teilen gedacht).

Revision ID: 0130_album_share_public
Revises: 0129_domain_active_unique
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0130_album_share_public"
down_revision = "0129_domain_active_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photo_album_tenant_share", sa.Column("partner_public_links", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("photo_album_tenant_share", sa.Column("partner_photos_public", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column("photo_album_tenant_share", "partner_photos_public")
    op.drop_column("photo_album_tenant_share", "partner_public_links")
