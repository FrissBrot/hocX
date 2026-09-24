"""Korrigiert eine falsche Annahme aus 0085_plan_pricing: dort wurde 'custom_domain' als "rein
informativ" eingestuft, weil die Domain-Einrichtung angeblich schon durch den Plattform-Admin
gesperrt sei. Tatsaechlich ist POST /tenants/{id}/domains Self-Service fuer jeden
Mandanten-Admin (tenant_service.py::create_domain), nur ueber _require_manageable() geprueft -
keine Plan-Pruefung. Dieser Umbau schliesst die Luecke ueber require_feature, wie bei
'abgabebox' in 0085.

Backfill nach demselben Muster: jeder Bestandsmandant, der die eigene Domain heute schon selbst
einrichten koennte, darf das nach dem Umbau weiterhin - sonst waere das ein stiller
Feature-Entzug fuer alle, die es schon nutzen.

Revision ID: 0086_custom_domain_enforcement
Revises: 0085_plan_pricing
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0086_custom_domain_enforcement"
down_revision = "0085_plan_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("INSERT INTO tenant_feature (tenant_id, feature_code) SELECT id, 'custom_domain' FROM tenant")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM tenant_feature WHERE feature_code = 'custom_domain'"))
