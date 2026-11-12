"""Neue Domain ersetzt die aktive desselben Zwecks erst nach erfolgreicher Prüfung

Audit 08 (2026-11): uq_tenant_domain_tenant_purpose erlaubte genau eine Zeile je Mandant und
Zweck. «Domain hinzufügen» musste darum die laufende Domain sofort löschen - ein Tippfehler legte
die Vereins-Domain lahm, bis die neue verifiziert war. Jetzt dürfen je Zweck eine aktive und eine
ausstehende (pending) Domain nebeneinander bestehen; verify_domain tauscht sie in einem Schritt.

Revision ID: 0179_domain_pending_replacement
Revises: 0178_event_cycle_backfill
Create Date: 2026-11-12
"""

from alembic import op

revision = "0179_domain_pending_replacement"
down_revision = "0178_event_cycle_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.tenant_domain DROP CONSTRAINT IF EXISTS uq_tenant_domain_tenant_purpose")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_domain_purpose_active ON public.tenant_domain (tenant_id, purpose) "
        "WHERE status = 'active'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_domain_purpose_pending ON public.tenant_domain (tenant_id, purpose) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    # Die alte Regel kennt nur eine Zeile je Zweck: ausstehende Ersatz-Domains neben einer aktiven
    # verwerfen (die aktive Domain bleibt, es gehen nur unbestätigte Einträge verloren).
    op.execute(
        """
        DELETE FROM public.tenant_domain d
        USING public.tenant_domain keep
        WHERE d.tenant_id = keep.tenant_id
          AND d.purpose = keep.purpose
          AND d.status = 'pending'
          AND keep.status = 'active'
        """
    )
    op.execute("DROP INDEX IF EXISTS public.uq_tenant_domain_purpose_pending")
    op.execute("DROP INDEX IF EXISTS public.uq_tenant_domain_purpose_active")
    op.create_unique_constraint("uq_tenant_domain_tenant_purpose", "tenant_domain", ["tenant_id", "purpose"])
