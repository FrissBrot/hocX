"""Disable legacy demo accounts installed by the original base migration.

Revision ID: 0074_demo_account_lockout
Revises: 0073_platform_admin_mfa
Create Date: 2026-08-27
"""

from alembic import context, op

revision = "0074_demo_account_lockout"
down_revision = "0073_platform_admin_mfa"
branch_labels = None
depends_on = None

_DEMO_EMAILS = (
    "superadmin@hocx.local",
    "admin@hocx.local",
    "writer@hocx.local",
    "reader@hocx.local",
)


def upgrade() -> None:
    # Fresh, explicitly seeded dev/E2E databases need these accounts. Every normal migration
    # path (including production) revokes login for legacy copies. We deliberately do not
    # delete tenants here: an old installation may have turned tenant 1 into real customer
    # data, and an automatic cascading cleanup would be destructive.
    seed_demo = context.get_x_argument(as_dictionary=True).get("seed_demo", "").lower() == "true"
    if seed_demo:
        return
    quoted = ", ".join(f"'{email}'" for email in _DEMO_EMAILS)
    op.execute(f"UPDATE app_user SET is_active = FALSE WHERE lower(email) IN ({quoted})")


def downgrade() -> None:
    # Re-enabling known-password accounts would be unsafe and cannot reconstruct prior state.
    pass
