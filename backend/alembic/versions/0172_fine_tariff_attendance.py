"""Tarife auch für Anwesenheitsbussen (Verspätung, Abwesenheit).

Bisher galten die Tarife (fine_tariff_group, 0169) nur für Pendenzen-Bussen. Jetzt kann jeder
Tarif eigene Beträge für Verspätung und Abwesenheit haben. NULL heisst: der Vereinstarif
(fine_tariff) gilt. Eine Vorlage mit eigenem Tarif (template.fine_tariff_override) bleibt
für alle Personen gleich, siehe fine_tariff_service.tariff_block_values.

Revision ID: 0172_fine_tariff_attendance
Revises: 0171_account_tokens
Create Date: 2026-11-11
"""

from alembic import op

revision = "0172_fine_tariff_attendance"
down_revision = "0171_account_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE fine_tariff_group
            ADD COLUMN amount_late numeric(10, 2),
            ADD COLUMN amount_absent numeric(10, 2),
            ADD CONSTRAINT ck_fine_tariff_group_amount_late CHECK (amount_late IS NULL OR amount_late >= 0),
            ADD CONSTRAINT ck_fine_tariff_group_amount_absent CHECK (amount_absent IS NULL OR amount_absent >= 0)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE fine_tariff_group
            DROP CONSTRAINT IF EXISTS ck_fine_tariff_group_amount_absent,
            DROP CONSTRAINT IF EXISTS ck_fine_tariff_group_amount_late,
            DROP COLUMN IF EXISTS amount_absent,
            DROP COLUMN IF EXISTS amount_late
        """
    )
