"""Abgaben abschliessen und persönlicher Link fertig (docs/SUBMISSION_OWNER_ACCESS.md, Teil 2/3).

- ``submission_assignment.completed_at``: gesetzt, sobald alle Elemente abgegeben oder geschlossen
  sind und nichts mehr dazukommen kann (``submission_service.assignment_completion``); die Liste
  zeigt solche Abgaben im Reiter «Abgeschlossen». Der Job ``submission_todo_sync`` hält das Feld
  aktuell, dazu jede Änderung an einem Element über das Backend.
- ``owner_access_days`` (1–90, Standard 30): Gültigkeit des persönlichen Links.
- ``owner_resubmit_only_personal``: nach einem Zurückziehen nimmt die Abgabebox für dieses Element
  nichts mehr über den gemeinsamen Link an, nur noch über den persönlichen Link.
- ``submission_withdrawn_elements(assignment_id)``: Elemente mit zurückgezogenen Dateien, für die
  Abgabebox (die ``gallery_image`` nicht lesen darf), nur für den Mandanten des gesetzten Links.

Revision ID: 0182_submission_completion
Revises: 0181_submission_owner_access
Create Date: 2026-11-15
"""

from alembic import op

revision = "0182_submission_completion"
down_revision = "0181_submission_owner_access"
branch_labels = None
depends_on = None

_WITHDRAWN = """
CREATE OR REPLACE FUNCTION public.submission_withdrawn_elements(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT DISTINCT u.event_id, u.list_entry_id
        FROM submission_upload_file f
        JOIN submission_upload u ON u.id = f.upload_id
        JOIN submission_assignment a ON a.id = u.assignment_id
        WHERE u.assignment_id = p_assignment_id
          AND f.withdrawn_at IS NOT NULL
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
        UNION
        SELECT e.id, le.id
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        WHERE g.submission_assignment_id = p_assignment_id
          AND g.submission_withdrawn_at IS NOT NULL
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR g.submission_element_ref = 'manual')
    $$;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE submission_assignment ADD COLUMN completed_at timestamptz")
    op.execute("ALTER TABLE submission_assignment ADD COLUMN owner_access_days integer NOT NULL DEFAULT 30")
    op.execute(
        "ALTER TABLE submission_assignment ADD CONSTRAINT ck_submission_assignment_owner_access_days "
        "CHECK (owner_access_days BETWEEN 1 AND 90)"
    )
    op.execute("ALTER TABLE submission_assignment ADD COLUMN owner_resubmit_only_personal boolean NOT NULL DEFAULT false")
    op.execute(_WITHDRAWN)
    op.execute("REVOKE ALL ON FUNCTION public.submission_withdrawn_elements(BIGINT) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.submission_withdrawn_elements(BIGINT) TO hocx_abgabebox")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.submission_withdrawn_elements(BIGINT)")
    op.execute("ALTER TABLE submission_assignment DROP COLUMN IF EXISTS owner_resubmit_only_personal")
    op.execute("ALTER TABLE submission_assignment DROP CONSTRAINT IF EXISTS ck_submission_assignment_owner_access_days")
    op.execute("ALTER TABLE submission_assignment DROP COLUMN IF EXISTS owner_access_days")
    op.execute("ALTER TABLE submission_assignment DROP COLUMN IF EXISTS completed_at")
