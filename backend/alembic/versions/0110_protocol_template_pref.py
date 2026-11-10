"""Letzte Protokollvorlage pro Benutzer und Mandant speichern."""
from alembic import op
import sqlalchemy as sa

revision = "0110_protocol_template_pref"
down_revision = "0109_abgabebox_participant_grant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_protocol_template_preference",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("template_id", sa.BigInteger(), sa.ForeignKey("template.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_protocol_template_preference TO hocx_app")


def downgrade() -> None:
    op.drop_table("user_protocol_template_preference")
