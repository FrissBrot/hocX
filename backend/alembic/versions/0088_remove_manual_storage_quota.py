"""Manuelles Speicherkontingent aus dem Adminportal entfernt: das Kontingent ergibt sich nur noch
aus Plan + Zusatzpaketen. Bestandsmandanten mit gesetztem storage_quota_manual_override werden
zurueckgesetzt und ihr storage_quota_bytes nach derselben Regel wie
AdminTenantService.recompute_effective_storage_quota() neu berechnet - sonst blieben sie ohne
UI-Moeglichkeit auf dem alten manuellen Wert stehen.

Security fix (audit 2026-09-24): der urspruengliche Reset war unconditional fuer JEDEN Tenant mit
storage_quota_manual_override=TRUE - das ist korrekt fuer einen Override, der das Kontingent
grosszuegiger gemacht hat (der Regelfall, siehe test_storage_packages.py), haette aber genauso
einen Override, der ein Kontingent bewusst UNTER das Plan+Paket-Total EINGESCHRAENKT hat (z.B. eine
Abuse-/Billing-Massnahme), kommentarlos wieder aufgehoben - ein manueller Fix wird nur noch
zurueckgesetzt, wenn er eine Erweiterung war (aktueller Wert >= neu berechnetem Plan+Paket-Total).
Ein restriktiver Override (aktueller Wert kleiner, oder Plan+Pakete ergeben "unbegrenzt") bleibt
bestehen (weiterhin storage_quota_manual_override=TRUE) - im Zweifel die sicherere, nicht
kontingent-erweiternde Richtung. Fuer diese verbleibenden Faelle braucht es weiterhin eine manuelle
Admin-Entscheidung (die GUI-Moeglichkeit dafuer wurde in diesem Umbau bewusst entfernt), das ist
hier ausserhalb des Scopes.

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

# Modulkonstante (statt inline in upgrade()), damit backend/tests/test_storage_packages.py diese
# exakte Anweisung direkt gegen die Test-DB ausfuehren und das Grant/Restriktion-Verhalten
# regressionssichern kann, ohne eine volle Alembic-Migrationsumgebung aufzusetzen.
RESET_GRANTED_OVERRIDES_SQL = """
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
    )
    UPDATE tenant t
    SET storage_quota_manual_override = FALSE,
        storage_quota_bytes = c.computed_bytes
    FROM computed c
    WHERE t.id = c.tenant_id
      AND t.storage_quota_manual_override
      -- Nur Overrides zuruecksetzen, die das Kontingent erweitert hatten (>= dem neu
      -- berechneten Plan+Paket-Total). c.computed_bytes IS NULL bedeutet "Plan+Pakete
      -- waeren unbegrenzt" - ein vorhandener endlicher manueller Wert war dann immer eine
      -- bewusste Einschraenkung, nie eine Erweiterung, und bleibt daher unangetastet.
      AND c.computed_bytes IS NOT NULL
      AND t.storage_quota_bytes >= c.computed_bytes
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(RESET_GRANTED_OVERRIDES_SQL))


def downgrade() -> None:
    # Die frueheren manuellen Werte sind nicht wiederherstellbar.
    pass
