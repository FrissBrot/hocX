"""Abgabe-Links: the public Abgabebox is now reached via a random, unguessable link token
instead of the tenant's public_slug.

submission_link holds the links (clear name for the admin UI + a random token that IS the
authentication), submission_assignment_link says which Abgabe is reachable over which link.

Existing tenants get one "Standard" link each and every existing Abgabe is attached to it, so
no Abgabe goes dark - but the old <domain>/<tenant-slug>/... URLs stop working (the slug alone
is no longer an access credential), so already distributed links have to be replaced by the
new ones (Abgaben page -> Links).

Isolation: hocx_app already has table-wide DML on both new tables via the ALTER DEFAULT
PRIVILEGES grant in baseline_schema.sql (see 0066's note). The restricted hocx_abgabebox role
gets exactly what it needs to resolve a token and nothing more: column-level SELECT on
(id, tenant_id, token) of submission_link and on (assignment_id, link_id) of
submission_assignment_link - never name/is_default/timestamps, never INSERT/UPDATE/DELETE.
"""

revision = "0075_submission_link"
down_revision = "0074_gallery_image_doc_links"
branch_labels = None
depends_on = None

import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

ABGABEBOX_ROLE = "hocx_abgabebox"
DEFAULT_LINK_NAME = "Standard"


def upgrade():
    op.create_table(
        "submission_link",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="submission_link_public_id_key"),
        sa.UniqueConstraint("token", name="submission_link_token_key"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_submission_link_tenant_name"),
    )
    op.create_index(
        "uq_submission_link_tenant_default",
        "submission_link",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.execute(
        "CREATE TRIGGER trg_submission_link_updated_at BEFORE UPDATE ON submission_link "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.create_table(
        "submission_assignment_link",
        sa.Column(
            "assignment_id",
            sa.BigInteger(),
            sa.ForeignKey("submission_assignment.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("link_id", sa.BigInteger(), sa.ForeignKey("submission_link.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_submission_assignment_link_link", "submission_assignment_link", ["link_id"])

    # Backfill: one default link per existing tenant, every existing Abgabe attached to it.
    bind = op.get_bind()
    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenant ORDER BY id"))]
    for tenant_id in tenant_ids:
        link_id = bind.execute(
            sa.text(
                "INSERT INTO submission_link (tenant_id, name, token, is_default) "
                "VALUES (:tenant_id, :name, :token, TRUE) RETURNING id"
            ),
            {"tenant_id": tenant_id, "name": DEFAULT_LINK_NAME, "token": secrets.token_urlsafe(24)},
        ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO submission_assignment_link (assignment_id, link_id) "
                "SELECT id, :link_id FROM submission_assignment WHERE tenant_id = :tenant_id"
            ),
            {"link_id": link_id, "tenant_id": tenant_id},
        )

    op.execute(f"GRANT SELECT (id, tenant_id, token) ON TABLE submission_link TO {ABGABEBOX_ROLE}")
    op.execute(f"GRANT SELECT (assignment_id, link_id) ON TABLE submission_assignment_link TO {ABGABEBOX_ROLE}")


def downgrade():
    op.drop_table("submission_assignment_link")
    op.drop_table("submission_link")
