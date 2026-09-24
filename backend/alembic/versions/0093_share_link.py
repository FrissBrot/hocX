"""Oeffentliche Download-Links fuer Dateien/Fotos: share_link traegt einen zufaelligen,
unerratbaren Token, der selbst die Authentifizierung ist (Teil der URL: <app-domain>/share/
<token>), analog zu submission_link. Zeigt entweder auf ein Album (album_id gesetzt - "live",
immer der aktuelle Album-Inhalt) oder auf eine feste Dateiauswahl (share_link_file).

hocx_app hat bereits table-wide DML auf neuen Tabellen via ALTER DEFAULT PRIVILEGES (siehe
0066/0068) - kein neues GRANT noetig. Die oeffentliche Download-Route laeuft im normalen
Haupt-Backend (kein separater, restricted Service wie bei Abgabebox), da es sich um reinen
Lesezugriff handelt.

Revision ID: 0093_share_link
Revises: 0092_upload_capacity
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0093_share_link"
down_revision = "0092_upload_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("album_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("photo_album.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("token", name="uq_share_link_token"),
    )
    op.create_index("idx_share_link_tenant", "share_link", ["tenant_id"])
    op.create_index("idx_share_link_album", "share_link", ["album_id"])

    op.create_table(
        "share_link_file",
        sa.Column("share_link_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("share_link.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("share_link_file")
    op.drop_table("share_link")
