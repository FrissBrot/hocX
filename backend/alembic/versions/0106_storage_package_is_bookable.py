"""Speicherpakete bekommen analog zu plan.is_bookable eine Verfügbarkeit. Der JSON-Import des
Preiskatalogs (catalog_config_service) löscht im Überschreiben-Modus ein Paket, das noch
Mandanten zugewiesen ist, nicht (tenant_storage_package hängt per ON DELETE CASCADE daran),
sondern setzt es auf nicht buchbar. Die Übersicht "Umbuchen" im Adminportal listet solche
Mandanten. Bestehende Pakete bleiben buchbar.

Revision ID: 0106_storage_package_is_bookable
Revises: 0105_system_job_status
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0106_storage_package_is_bookable"
down_revision = "0105_system_job_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storage_package", sa.Column("is_bookable", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")))


def downgrade() -> None:
    op.drop_column("storage_package", "is_bookable")
