"""Bussentarif je Protokollvorlage (Feature-Recovery-Audit FAR-002)

Seit 0113 gibt es nur noch einen zentralen Tarif je Mandant (fine_tariff); vorher trug jeder
Anwesenheitsblock eigene Beträge. Eine Vorlage kann den Mandantentarif jetzt optional
übersteuern (fine_tariff_override). Der Tarif wird beim Laden eines Protokolls live aus seiner
Vorlage gelesen - wie der Mandantentarif; bereits erfasste Bussen behalten ihren Betrag.

Die Spalten liegen auf template selbst (RLS über tenant_id seit 0132), das Konto muss zum
Mandanten der Vorlage gehören (fine_tariff_service.update_template_tariff, Trigger als zweite
Absicherung).

Revision ID: 0137_template_fine_tariff
Revises: 0136_drop_manual_storage_quota
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0137_template_fine_tariff"
down_revision = "0136_drop_manual_storage_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("template", sa.Column("fine_tariff_override", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column(
        "template",
        sa.Column("fine_account_id", sa.BigInteger(), sa.ForeignKey("finance_account.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("template", sa.Column("fine_amount_late", sa.Numeric(15, 2), nullable=False, server_default=sa.text("0")))
    op.add_column("template", sa.Column("fine_amount_absent", sa.Numeric(15, 2), nullable=False, server_default=sa.text("0")))
    op.create_check_constraint(
        "ck_template_fine_amounts", "template", "fine_amount_late >= 0 AND fine_amount_absent >= 0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_fine_account ON public.template (fine_account_id) "
        "WHERE fine_account_id IS NOT NULL"
    )
    # Konto nur aus dem eigenen Mandanten (Schutz gegen fremde IDs, auch ausserhalb des Services).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.hocx_template_fine_account_tenant() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public AS $$
        BEGIN
            IF NEW.fine_account_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM finance_account fa WHERE fa.id = NEW.fine_account_id AND fa.tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'Bussenkonto gehört nicht zum Mandanten der Vorlage' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_template_fine_account_tenant
        BEFORE INSERT OR UPDATE OF fine_account_id, tenant_id ON public.template
        FOR EACH ROW EXECUTE FUNCTION public.hocx_template_fine_account_tenant()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_template_fine_account_tenant ON public.template")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_template_fine_account_tenant()")
    op.execute("DROP INDEX IF EXISTS public.idx_template_fine_account")
    op.drop_constraint("ck_template_fine_amounts", "template", type_="check")
    op.drop_column("template", "fine_amount_absent")
    op.drop_column("template", "fine_amount_late")
    op.drop_column("template", "fine_account_id")
    op.drop_column("template", "fine_tariff_override")
