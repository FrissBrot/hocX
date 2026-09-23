"""Manuelles Speicherkontingent aus dem Adminportal entfernt: das Kontingent ergibt sich nur noch
aus Plan + Zusatzpaketen. Bestandsmandanten mit gesetztem storage_quota_manual_override werden
zurueckgesetzt und ihr storage_quota_bytes nach derselben Regel wie
AdminTenantService.recompute_effective_storage_quota() neu berechnet - sonst blieben sie ohne
UI-Moeglichkeit auf dem alten manuellen Wert stehen.

Revision ID: 0088_remove_manual_storage_quota
Revises: 0087_storage_packages
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0088_remove_manual_storage_quota"
down_revision = "0087_storage_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE tenant t
            SET storage_quota_manual_override = FALSE,
                storage_quota_bytes = CASE
                    WHEN p.included_storage_bytes IS NULL AND COALESCE(pk.package_bytes, 0) = 0 THEN NULL
                    ELSE COALESCE(p.included_storage_bytes, 0) + COALESCE(pk.package_bytes, 0)
                END
            FROM tenant t2
            LEFT JOIN plan p ON p.code = t2.plan_code
            LEFT JOIN (
                SELECT tsp.tenant_id, SUM(sp.bytes * tsp.quantity) AS package_bytes
                FROM tenant_storage_package tsp
                JOIN storage_package sp ON sp.code = tsp.package_code
                GROUP BY tsp.tenant_id
            ) pk ON pk.tenant_id = t2.id
            WHERE t.id = t2.id AND t.storage_quota_manual_override
            """
        )
    )


def downgrade() -> None:
    # Die frueheren manuellen Werte sind nicht wiederherstellbar.
    pass
