"""Mandanten-Trust: tenant_trust haelt fest, dass zwei Mandanten schon einmal eine
Album-Freigabe angenommen haben. Erst dann sehen sie sich gegenseitig mit Namen/Profilbild
und koennen sich per Namen suchen; vorher ist ein Mandant nur ueber seine ID auffindbar
(siehe tenant_trust_service.py). Bestehende angenommene Freigaben werden uebernommen.

hocx_app hat bereits table-wide DML auf neuen Tabellen via ALTER DEFAULT PRIVILEGES (siehe
0066/0068) - kein neues GRANT noetig.

Revision ID: 0095_tenant_trust
Revises: 0094_photo_album_tenant_share
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0095_tenant_trust"
down_revision = "0094_photo_album_tenant_share"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_trust",
        sa.Column("tenant_low_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_high_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("tenant_low_id < tenant_high_id", name="ck_tenant_trust_ordered"),
    )
    op.create_index("idx_tenant_trust_high", "tenant_trust", ["tenant_high_id"])
    op.execute(
        """
        INSERT INTO tenant_trust (tenant_low_id, tenant_high_id, created_at)
        SELECT LEAST(a.tenant_id, s.tenant_id), GREATEST(a.tenant_id, s.tenant_id), MIN(COALESCE(s.responded_at, s.created_at))
        FROM photo_album_tenant_share s
        JOIN photo_album a ON a.id = s.album_id
        WHERE s.status = 'accepted' AND a.tenant_id <> s.tenant_id
        GROUP BY 1, 2
        """
    )


def downgrade() -> None:
    op.drop_table("tenant_trust")
