"""users belong to exactly one tenant: app_user gets tenant_id + role_id, user_tenant_role /
user_role / app_user.default_tenant_id are dropped

Multi-tenant membership (one login, several tenants, tenant switcher) is removed. A user now
belongs to exactly one tenant with exactly one role, stored directly on app_user.

Data resolution - nothing is dropped silently:
  * A user with more than one ACTIVE membership cannot be mapped 1:1. The migration aborts and
    lists them. Either resolve them by hand first (delete the extra rows in user_tenant_role,
    or split the person into separate accounts) or re-run with
    `alembic -x single_tenant_resolution=auto upgrade head`, which keeps for each such user the
    membership of their default tenant (else the most privileged role, else the lowest tenant
    id) and drops the others. `-x seed_demo=true` (dev/e2e/CI demo data) implies "auto".
  * A user without any membership row but with a default tenant is kept there as an inactive
    reader (they could not log in before either).
  * A user with no membership and no default tenant belongs nowhere and is deleted (only with
    "auto"; otherwise the migration aborts as above).
"""

revision = "0078_single_tenant_users"
down_revision = "0077_requeue_perceptual_hashes"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import context, op


def _auto_resolve() -> bool:
    args = context.get_x_argument(as_dictionary=True)
    return args.get("single_tenant_resolution", "").lower() == "auto" or args.get("seed_demo", "").lower() == "true"


def upgrade():
    bind = op.get_bind()

    multi = bind.execute(
        sa.text(
            """
            SELECT u.email, count(*) AS memberships
            FROM app_user u
            JOIN user_tenant_role m ON m.user_id = u.id AND m.is_active
            GROUP BY u.id, u.email
            HAVING count(*) > 1
            ORDER BY u.email
            """
        )
    ).all()
    tenantless = bind.execute(
        sa.text(
            """
            SELECT u.email
            FROM app_user u
            WHERE u.default_tenant_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM user_tenant_role m WHERE m.user_id = u.id)
            ORDER BY u.email
            """
        )
    ).all()

    if (multi or tenantless) and not _auto_resolve():
        lines = ["Migration 0078 (single-tenant users) cannot map every account to exactly one tenant."]
        if multi:
            lines.append("Accounts with more than one active tenant membership:")
            lines.extend(f"  - {row.email} ({row.memberships} tenants)" for row in multi)
        if tenantless:
            lines.append("Accounts without any tenant (no membership, no default tenant), would be deleted:")
            lines.extend(f"  - {row.email}" for row in tenantless)
        lines.append(
            "Resolve them manually, or re-run with `alembic -x single_tenant_resolution=auto upgrade head` "
            "to keep each account's default-tenant membership (else the most privileged role) and drop the rest."
        )
        raise RuntimeError("\n".join(lines))

    op.add_column("app_user", sa.Column("tenant_id", sa.BigInteger(), nullable=True))
    op.add_column("app_user", sa.Column("role_id", sa.SmallInteger(), nullable=True))

    # One membership per user: active first, then the default tenant, then the most privileged
    # role, then the lowest tenant id. A user whose only memberships are inactive ends up
    # inactive themselves.
    bind.execute(
        sa.text(
            """
            UPDATE app_user u
            SET tenant_id = pick.tenant_id,
                role_id = pick.role_id,
                is_active = u.is_active AND pick.is_active
            FROM (
                SELECT DISTINCT ON (m.user_id) m.user_id, m.tenant_id, m.role_id, m.is_active
                FROM user_tenant_role m
                JOIN app_user au ON au.id = m.user_id
                JOIN role r ON r.id = m.role_id
                ORDER BY
                    m.user_id,
                    m.is_active DESC,
                    COALESCE(m.tenant_id = au.default_tenant_id, false) DESC,
                    CASE r.code WHEN 'admin' THEN 0 WHEN 'kassier' THEN 1 WHEN 'writer' THEN 2 ELSE 3 END,
                    m.tenant_id
            ) pick
            WHERE u.id = pick.user_id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE app_user
            SET tenant_id = default_tenant_id,
                role_id = (SELECT id FROM role WHERE code = 'reader'),
                is_active = false
            WHERE tenant_id IS NULL AND default_tenant_id IS NOT NULL
            """
        )
    )
    bind.execute(sa.text("DELETE FROM app_user WHERE tenant_id IS NULL"))

    op.alter_column("app_user", "tenant_id", nullable=False)
    op.alter_column("app_user", "role_id", nullable=False)
    op.create_foreign_key("app_user_tenant_id_fkey", "app_user", "tenant", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("app_user_role_id_fkey", "app_user", "role", ["role_id"], ["id"], ondelete="RESTRICT")
    op.create_index("idx_app_user_tenant_role", "app_user", ["tenant_id", "role_id"])

    op.drop_index("idx_app_user_default_tenant", table_name="app_user")
    op.drop_constraint("app_user_default_tenant_id_fkey", "app_user", type_="foreignkey")
    op.drop_column("app_user", "default_tenant_id")

    op.drop_table("user_tenant_role")
    op.drop_table("user_role")


def downgrade():
    bind = op.get_bind()

    op.create_table(
        "user_role",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="user_role_pkey"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name="user_role_user_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="user_role_role_id_fkey", ondelete="RESTRICT"),
    )
    op.create_index("idx_user_role_role", "user_role", ["role_id"])

    op.create_table(
        "user_tenant_role",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "tenant_id", name="user_tenant_role_pkey"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name="user_tenant_role_user_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="user_tenant_role_tenant_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="user_tenant_role_role_id_fkey", ondelete="RESTRICT"),
    )
    op.create_index("idx_user_tenant_role_tenant", "user_tenant_role", ["tenant_id", "role_id"])
    op.create_index("idx_user_tenant_role_role", "user_tenant_role", ["role_id", "is_active"])
    op.execute(
        "CREATE TRIGGER trg_user_tenant_role_updated_at BEFORE UPDATE ON user_tenant_role "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.add_column("app_user", sa.Column("default_tenant_id", sa.BigInteger(), nullable=True))
    bind.execute(sa.text("UPDATE app_user SET default_tenant_id = tenant_id"))
    op.create_foreign_key(
        "app_user_default_tenant_id_fkey", "app_user", "tenant", ["default_tenant_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("idx_app_user_default_tenant", "app_user", ["default_tenant_id"])

    bind.execute(
        sa.text(
            "INSERT INTO user_tenant_role (user_id, tenant_id, role_id, is_active) "
            "SELECT id, tenant_id, role_id, is_active FROM app_user"
        )
    )

    op.drop_index("idx_app_user_tenant_role", table_name="app_user")
    op.drop_constraint("app_user_role_id_fkey", "app_user", type_="foreignkey")
    op.drop_constraint("app_user_tenant_id_fkey", "app_user", type_="foreignkey")
    op.drop_column("app_user", "role_id")
    op.drop_column("app_user", "tenant_id")
