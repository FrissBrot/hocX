"""Währung je Mandant (tenant.finance_currency) statt je Konto.

Bussen und Konten eines Vereins laufen in einer Währung; sie wird in den Mandanten-Einstellungen
gesetzt. finance_account.currency_label bleibt als abgeleitete Kopie bestehen (alle Lesepfade,
Exporte und Statistiken nutzen sie), wird aber nur noch zusammen mit der Mandantenwährung geändert
(routes/finance_settings.py).

Übernahme: je Mandant die am häufigsten verwendete Kontowährung (bei Gleichstand die des ältesten
Kontos), sonst CHF. Danach tragen alle Konten des Mandanten diese Währung. Es ist nur eine
Bezeichnung, Beträge werden nicht umgerechnet.

Revision ID: 0180_tenant_finance_currency
Revises: 0179_domain_pending_replacement
Create Date: 2026-11-13
"""

from alembic import op

revision = "0180_tenant_finance_currency"
down_revision = "0179_domain_pending_replacement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN IF NOT EXISTS finance_currency text NOT NULL DEFAULT 'CHF'")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_tenant_finance_currency') THEN
            ALTER TABLE tenant ADD CONSTRAINT ck_tenant_finance_currency
              CHECK (length(btrim(finance_currency)) BETWEEN 1 AND 20);
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE tenant AS t
        SET finance_currency = top.currency
        FROM (
          SELECT DISTINCT ON (tenant_id) tenant_id, btrim(currency_label) AS currency
          FROM finance_account
          WHERE length(btrim(currency_label)) BETWEEN 1 AND 20
          GROUP BY tenant_id, btrim(currency_label)
          ORDER BY tenant_id, count(*) DESC, min(id)
        ) AS top
        WHERE top.tenant_id = t.id
        """
    )
    op.execute(
        """
        UPDATE finance_account AS a
        SET currency_label = t.finance_currency
        FROM tenant AS t
        WHERE t.id = a.tenant_id AND a.currency_label IS DISTINCT FROM t.finance_currency
        """
    )


def downgrade() -> None:
    # Die Konten behalten die vereinheitlichte Währung (frühere Einzelwerte sind nicht gespeichert)
    op.execute("ALTER TABLE tenant DROP CONSTRAINT IF EXISTS ck_tenant_finance_currency")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS finance_currency")
