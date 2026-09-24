"""Abgabebox-Uploads gegen das echte Mandanten-Kontingent statt einer globalen Konstante pruefen
(Security-Audit-Fund, 2026-09-24): der oeffentliche abgabebox-backend-Service verglich bislang
gegen settings.tenant_storage_quota_mb (ein einziger Wert fuer alle Mandanten), nicht gegen
Tenant.storage_quota_bytes - ein Mandant mit kleinem Plan konnte sich ueber den Abgabebox-Kanal
kostenlosen Zusatzspeicher bis zur globalen Obergrenze verschaffen.

Grant nach demselben minimalen Spalten-Muster wie die anderen Abgabebox-Grants (siehe
0085_plan_pricing.py): die restricted Rolle darf nur (id, storage_quota_bytes) lesen, keine
anderen Tenant-Spalten (Name, Slug, Pricing-Felder etc.).

Revision ID: 0090_abgabebox_quota_grant
Revises: 0089_plan_catalog_details
Create Date: 2026-09-24
"""

from alembic import op

revision = "0090_abgabebox_quota_grant"
down_revision = "0089_plan_catalog_details"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"


def upgrade() -> None:
    op.execute(f"GRANT SELECT (id, storage_quota_bytes) ON TABLE tenant TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT (id, storage_quota_bytes) ON TABLE tenant FROM {ABGABEBOX_ROLE}")
