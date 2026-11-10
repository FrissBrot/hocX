"""Manuelles Speicherkontingent vollständig entfernt (Feature-Recovery-Audit FAR-008)

0088 hat die Oberfläche entfernt, aber Endpunkt PATCH /api/admin/tenants/{id}/storage-quota und
das Flag tenant.storage_quota_manual_override blieben: ein per API gesetzter Wert war in keiner
Oberfläche sichtbar oder rücksetzbar. Das Kontingent ergibt sich jetzt ausnahmslos aus Plan +
Zusatzpaketen.

Mandanten, deren Override 0088 bewusst stehen liess (Einschränkung unter Plan + Pakete), werden
hier nach derselben Regel wie AdminTenantService.apply_effective_storage_quota neu berechnet und
damit wieder auf Plan + Pakete gesetzt. Ihre IDs und alten Werte stehen im Migrationslog; wer eine
Einschränkung braucht, weist einen passenden Plan zu.

Revision ID: 0136_drop_manual_storage_quota
Revises: 0135_db_performance
Create Date: 2026-10-21
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "0136_drop_manual_storage_quota"
down_revision = "0135_db_performance"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Als Modulkonstante, damit tests/test_storage_packages.py genau diese Anweisung prüfen kann.
RESET_REMAINING_OVERRIDES_SQL = """
    WITH computed AS (
        SELECT
            t2.id AS tenant_id,
            CASE
                WHEN p.included_storage_bytes IS NULL AND COALESCE(pk.package_bytes, 0) = 0 THEN NULL
                ELSE COALESCE(p.included_storage_bytes, 0) + COALESCE(pk.package_bytes, 0)
            END AS computed_bytes
        FROM tenant t2
        LEFT JOIN plan p ON p.code = t2.plan_code
        LEFT JOIN (
            SELECT tsp.tenant_id, SUM(sp.bytes * tsp.quantity) AS package_bytes
            FROM tenant_storage_package tsp
            JOIN storage_package sp ON sp.code = tsp.package_code
            GROUP BY tsp.tenant_id
        ) pk ON pk.tenant_id = t2.id
    ),
    reset AS (
        UPDATE tenant t
        SET storage_quota_bytes = c.computed_bytes
        FROM computed c, tenant old
        WHERE t.id = c.tenant_id
          AND old.id = t.id
          AND t.storage_quota_manual_override
        RETURNING t.id, old.storage_quota_bytes AS old_bytes, t.storage_quota_bytes AS new_bytes
    )
    SELECT id, old_bytes, new_bytes FROM reset ORDER BY id
"""


def upgrade() -> None:
    for row in op.get_bind().execute(sa.text(RESET_REMAINING_OVERRIDES_SQL)):
        logger.warning(
            "Manuelles Speicherkontingent entfernt: Mandant %s %s -> %s Bytes (Plan + Pakete)",
            row.id, row.old_bytes, row.new_bytes,
        )
    op.drop_column("tenant", "storage_quota_manual_override")


def downgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("storage_quota_manual_override", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
