"""Custom-Domains nur unter aktiven Einträgen eindeutig

Security-Audit release/1.2.0 (SEC-004): uq_tenant_domain_domain galt auch für unbestätigte
(pending) Domains, die ohne Besitznachweis angelegt werden und nie verfallen - ein Mandant
konnte so die Domain eines anderen Vereins unbefristet blockieren. Eindeutig ist jetzt nur
noch eine aktive (per TXT/DNS verifizierte) Domain; pending-Einträge dürfen sich überschneiden,
die Verifizierung lehnt ab, wenn die Domain inzwischen anderswo aktiv ist.

Revision ID: 0129_domain_active_unique
Revises: 0128_todo_notes_files
Create Date: 2026-10-17
"""

from alembic import op

revision = "0129_domain_active_unique"
down_revision = "0128_todo_notes_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_tenant_domain_domain", "tenant_domain", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_domain_active_domain ON public.tenant_domain (domain) WHERE status = 'active'"
    )


def downgrade() -> None:
    # Vor der alten, strengeren Regel überzählige pending-Einträge entfernen: je Domain bleibt der
    # aktive Eintrag, sonst der älteste.
    op.execute(
        """
        DELETE FROM public.tenant_domain d
        USING public.tenant_domain keep
        WHERE d.domain = keep.domain
          AND d.id <> keep.id
          AND d.status = 'pending'
          AND (keep.status = 'active' OR (keep.status = 'pending' AND keep.id < d.id))
        """
    )
    op.execute("DROP INDEX IF EXISTS public.uq_tenant_domain_active_domain")
    op.create_unique_constraint("uq_tenant_domain_domain", "tenant_domain", ["domain"])
