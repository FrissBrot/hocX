"""Mandantenuebergreifende Fotoalben: photo_album_tenant_share laedt einen ANDEREN Mandanten in
ein eigenes ("manual") Album ein. Der Besitzer bleibt photo_album.tenant_id; diese Tabelle
traegt nur den eingeladenen Partner-Mandanten und den Stand der Einladung
(pending/accepted/declined). Erst nach "accepted" darf der eingeladene Mandant das Album sehen
bzw. eigene Fotos hinzufuegen/loeschen (siehe access_service.py, photo_album_share_service.py).

hocx_app hat bereits table-wide DML auf neuen Tabellen via ALTER DEFAULT PRIVILEGES (siehe
0066/0068) - kein neues GRANT noetig.

Revision ID: 0094_photo_album_tenant_share
Revises: 0093_share_link
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0094_photo_album_tenant_share"
down_revision = "0093_share_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "photo_album_tenant_share",
        sa.Column("album_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("photo_album.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("invited_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responded_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'declined')", name="ck_photo_album_tenant_share_status"),
    )
    op.create_index("idx_photo_album_tenant_share_tenant", "photo_album_tenant_share", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("photo_album_tenant_share")
