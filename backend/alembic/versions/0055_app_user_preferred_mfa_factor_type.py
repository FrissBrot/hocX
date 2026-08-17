"""store preferred MFA method per user

Adds a nullable preference on app_user that records which MFA method type should be used as the
default during login. Existing users are backfilled to preserve the prior behavior: prefer a
passkey when one exists, otherwise fall back to TOTP.

Revision ID: 0055_app_user_preferred_mfa_factor_type
Revises: 0054_user_mfa_factor
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0055_app_user_preferred_mfa_factor_type"
down_revision = "0054_user_mfa_factor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("preferred_mfa_factor_type", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_app_user_preferred_mfa_factor_type",
        "app_user",
        "preferred_mfa_factor_type IN ('totp', 'webauthn')",
    )
    op.execute(
        """
        UPDATE app_user AS u
        SET preferred_mfa_factor_type = CASE
            WHEN EXISTS (
                SELECT 1
                FROM user_mfa_factor AS f
                WHERE f.user_id = u.id
                  AND f.factor_type = 'webauthn'
            ) THEN 'webauthn'
            WHEN EXISTS (
                SELECT 1
                FROM user_mfa_factor AS f
                WHERE f.user_id = u.id
                  AND f.factor_type = 'totp'
            ) THEN 'totp'
            ELSE NULL
        END
        WHERE EXISTS (
            SELECT 1
            FROM user_mfa_factor AS f
            WHERE f.user_id = u.id
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_app_user_preferred_mfa_factor_type", "app_user", type_="check")
    op.drop_column("app_user", "preferred_mfa_factor_type")
