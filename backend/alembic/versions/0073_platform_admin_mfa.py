"""platform-admin MFA: lets user_mfa_factor store TOTP factors for PlatformAdmin, not just
AppUser.

Audit finding, 2026-08-27: tenant users with the 'admin' role are forced to enroll MFA
(see app.services.mfa_service.user_requires_mfa / get_optional_current_user's enforcement),
but PlatformAdmin login was password-only, despite being the highest-privilege tier (full
cross-tenant access, backup export, admin management). Reuses this existing table rather
than adding a parallel one, since the TOTP-storage shape (secret_encrypted,
totp_last_counter, label, timestamps, ...) is identical regardless of which principal owns
the factor - only the owning FK differs. user_id becomes nullable and a new nullable
platform_admin_id FK is added alongside it; a check constraint enforces that exactly one of
the two is set on every row (never both, never neither).

Revision ID: 0073_platform_admin_mfa
Revises: 0072_pg_stat_statements
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0073_platform_admin_mfa"
down_revision = "0072_pg_stat_statements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_mfa_factor",
        sa.Column("platform_admin_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_mfa_factor_platform_admin_id",
        "user_mfa_factor",
        "platform_admin",
        ["platform_admin_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("user_mfa_factor", "user_id", nullable=True)
    op.create_check_constraint(
        "ck_user_mfa_factor_single_owner",
        "user_mfa_factor",
        "(user_id IS NOT NULL AND platform_admin_id IS NULL) OR "
        "(user_id IS NULL AND platform_admin_id IS NOT NULL)",
    )
    op.create_index(
        "idx_user_mfa_factor_platform_admin", "user_mfa_factor", ["platform_admin_id", "factor_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_user_mfa_factor_platform_admin", table_name="user_mfa_factor")
    op.drop_constraint("ck_user_mfa_factor_single_owner", "user_mfa_factor", type_="check")
    # Any platform-admin-owned rows have no user_id and would violate the restored NOT NULL
    # constraint - this downgrade is only meant for a clean rollback before real admin MFA
    # data exists, matching this repo's existing downgrade rigor (see e.g.
    # 0066/0067/0068's public_id rollout, which has the same one-way-in-practice shape).
    op.execute("DELETE FROM user_mfa_factor WHERE platform_admin_id IS NOT NULL")
    op.alter_column("user_mfa_factor", "user_id", nullable=False)
    op.drop_constraint("fk_user_mfa_factor_platform_admin_id", "user_mfa_factor", type_="foreignkey")
    op.drop_column("user_mfa_factor", "platform_admin_id")
