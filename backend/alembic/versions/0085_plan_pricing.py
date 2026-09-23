"""Preiskatalog: plan/plan_feature ergaenzen den bestehenden feature/tenant_feature-Unterbau
(0084) um Pakete mit Preis. tenant_feature bleibt die alleinige Quelle der Wahrheit fuers
Enforcement (require_feature prueft nur dort) - plan_feature beschreibt nur, welche Features ein
Plan beim Zuweisen im Adminportal automatisch in tenant_feature eintraegt. Preise als Rappen
(Integer), nie Franken/Float - siehe Planungs-Notiz "Preisspeicherung".

Zwei weitere Katalog-Features kommen hier dazu: 'abgabebox' (bisher komplett ungated, jeder
Mandant konnte sie nutzen) und 'custom_domain' (rein informativ fuer die Preisliste - die
eigene Domain wird weiterhin nur vom Plattform-Admin eingerichtet, technisch also bereits
gesperrt, siehe tenants.py/domain_verification_service.py).

Backfill: jeder Bestandsmandant bekommt den Plan 'legacy' (kein Preis, keine Limits - die Katalog-
Plaene 'starter'/'standard'/'premium' sind fuer Neukunden gedacht) und eine tenant_feature-Zeile
fuer 'abgabebox', damit niemand durch den Umbau Zugriff verliert (Abgabebox lief bisher
ungated). 'finance' ist bereits in 0084 gebackfillt.

Revision ID: 0085_plan_pricing
Revises: 0084_tenant_feature
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0085_plan_pricing"
down_revision = "0084_tenant_feature"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"


def upgrade() -> None:
    op.add_column("feature", sa.Column("standalone_price_monthly_rp", sa.Integer(), nullable=True))

    op.create_table(
        "plan",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price_monthly_rp", sa.Integer(), nullable=True),
        sa.Column("price_yearly_rp", sa.Integer(), nullable=True),
        sa.Column("included_user_limit", sa.Integer(), nullable=True),
        sa.Column("included_storage_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "plan_feature",
        sa.Column("plan_code", sa.Text(), sa.ForeignKey("plan.code", ondelete="CASCADE"), primary_key=True),
        sa.Column("feature_code", sa.Text(), sa.ForeignKey("feature.code", ondelete="CASCADE"), primary_key=True),
    )

    op.add_column("tenant", sa.Column("plan_code", sa.Text(), sa.ForeignKey("plan.code", ondelete="SET NULL"), nullable=True))
    op.add_column(
        "tenant",
        sa.Column("billing_cycle", sa.Text(), nullable=False, server_default=sa.text("'monthly'")),
    )
    op.add_column("tenant", sa.Column("user_limit_override", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_tenant_billing_cycle", "tenant", "billing_cycle IN ('monthly', 'yearly')")

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO feature (code, name, description) VALUES "
            "('abgabebox', 'Abgabebox', 'Öffentliche Upload-Seite für Teilnehmer-Abgaben'), "
            "('custom_domain', 'Eigene Domain', 'Eigene Domain statt der hocX-Standarddomain (Einrichtung durch hocX)')"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO plan (code, name, price_monthly_rp, price_yearly_rp, included_user_limit, included_storage_bytes, sort_order) "
            "VALUES "
            "('legacy', 'Bestandsmandanten', NULL, NULL, NULL, NULL, 0), "
            "('starter', 'Starter', 9900, 99000, 10, 5368709120, 1), "
            "('standard', 'Standard', 19900, 199000, 30, 21474836480, 2), "
            "('premium', 'Premium', 34900, 349000, NULL, 107374182400, 3)"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO plan_feature (plan_code, feature_code) VALUES "
            "('starter', 'abgabebox'), "
            "('standard', 'abgabebox'), ('standard', 'finance'), "
            "('premium', 'abgabebox'), ('premium', 'finance'), ('premium', 'custom_domain')"
        )
    )

    bind.execute(sa.text("UPDATE tenant SET plan_code = 'legacy'"))
    bind.execute(
        sa.text("INSERT INTO tenant_feature (tenant_id, feature_code) SELECT id, 'abgabebox' FROM tenant")
    )

    op.execute(f"GRANT SELECT (tenant_id, feature_code) ON TABLE tenant_feature TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.drop_constraint("ck_tenant_billing_cycle", "tenant", type_="check")
    op.drop_column("tenant", "user_limit_override")
    op.drop_column("tenant", "billing_cycle")
    op.drop_column("tenant", "plan_code")
    op.drop_table("plan_feature")
    op.drop_table("plan")
    op.drop_column("feature", "standalone_price_monthly_rp")
