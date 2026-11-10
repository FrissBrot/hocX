"""Gestaltung auf Abruf: Herkunft übernommener Katalog-Designs.

Designs aus dem Katalog (Alpin, Kreide …, app.documents.examples) werden beim Übernehmen nicht
mehr mit eigenem Brand-Profil und Beispielbildern in den Verein kopiert, sondern als eine
Vorlage, die das Erscheinungsbild des Vereins nutzt. ``catalog_key`` merkt sich, aus welchem
Design sie stammt («Aus Katalog · Alpin»). Kopien von Systemvorlagen tragen ihre Herkunft
weiterhin über ``source_template_id``.

Revision ID: 0160_template_catalog_key
Revises: 0159_brand_section_gap
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0160_template_catalog_key"
down_revision = "0159_brand_section_gap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_template", sa.Column("catalog_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_template", "catalog_key")
