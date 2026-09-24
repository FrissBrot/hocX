"""Beschreibung des Features 'custom_domain' korrigieren: der Zusatz "(Einrichtung durch hocX)"
aus 0085_plan_pricing stimmt nicht - Mandanten richten ihre Domain selbst ein (DNS-Verifizierung
im Tab «Domains»).

Revision ID: 0091_custom_domain_description
Revises: 0090_abgabebox_quota_grant
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0091_custom_domain_description"
down_revision = "0090_abgabebox_quota_grant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE feature SET description = 'Eigene Domain statt der hocX-Standarddomain' WHERE code = 'custom_domain'")
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE feature SET description = 'Eigene Domain statt der hocX-Standarddomain (Einrichtung durch hocX)' "
            "WHERE code = 'custom_domain'"
        )
    )
