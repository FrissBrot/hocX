"""Fehlende Monats- bzw. Jahrespreise von Plänen und Speicherpaketen nachtragen.

Gleiche Regel wie app.services.plan_pricing.complete: Monat = Jahr / 12 × 1.2, Jahr = Monat × 12 / 1.2,
auf 5 Rappen gerundet. Vorher berechnete nur das Admin-Formular den Monats- aus dem Jahrespreis;
Pläne mit nur einem Monatspreis hatten keinen Jahrespreis (Website «Jährlich», Jahresabos).

Downgrade setzt nichts zurück (ergänzte Preise sind gültige Werte, die vorherigen NULL lassen sich
nicht mehr unterscheiden).

Revision ID: 0194_plan_prices_complete
Revises: 0193_drop_slug_and_member_rule
Create Date: 2026-11-18
"""

from alembic import op

revision = "0194_plan_prices_complete"
down_revision = "0193_drop_slug_and_member_rule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("plan", "storage_package"):
        op.execute(
            f"UPDATE public.{table} SET price_yearly_rp = (round(price_monthly_rp * 12 / 1.2 / 5) * 5)::int "  # sql-ok: feste Tabellennamen
            "WHERE price_yearly_rp IS NULL AND price_monthly_rp IS NOT NULL"
        )
        op.execute(
            f"UPDATE public.{table} SET price_monthly_rp = (round(price_yearly_rp / 12.0 * 1.2 / 5) * 5)::int "  # sql-ok: feste Tabellennamen
            "WHERE price_monthly_rp IS NULL AND price_yearly_rp IS NOT NULL"
        )


def downgrade() -> None:
    pass
