"""Persönlicher Link für Verantwortliche einer Abgabe (docs/SUBMISSION_OWNER_ACCESS.md, Teil 3).

- ``submission_assignment.owner_access``: ``off`` (Standard für bestehende Abgaben), ``view``
  (eigene Abgabe ansehen) oder ``manage`` (ansehen, zurückziehen, neu abgeben).
- ``submission_access_token``: ein persönlicher Link je Zeile, gebunden an Mandant, Abgabe,
  Element und Person. Gespeichert wird nur der SHA-256-Hash; das Token entsteht beim Versand der
  Mail und steht nur dort, im URL-Fragment. RLS wie account_token.
- Zurückziehen löscht nichts: ``submission_upload_file.withdrawn_at`` bzw.
  ``gallery_image.submission_withdrawn_at`` markieren die Dateien, sie zählen danach nirgends mehr
  (Element, Höchstzahl, Abgabebox) und lassen sich von der Verwaltung wiederherstellen.
- ``submission_linked_file_counts`` (0175) zählt zurückgezogene, in der App verknüpfte Dateien nicht.

Revision ID: 0181_submission_owner_access
Revises: 0180_tenant_finance_currency
Create Date: 2026-11-14
"""

from alembic import op

revision = "0181_submission_owner_access"
down_revision = "0180_tenant_finance_currency"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"

_COUNTS = """
CREATE OR REPLACE FUNCTION public.submission_linked_file_counts(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT, file_count INTEGER)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT e.id, le.id, COUNT(*)::INTEGER
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        WHERE g.submission_assignment_id = p_assignment_id
          AND g.submission_withdrawn_at IS NULL
          -- nur der Mandant des gesetzten Upload-Links (wie die RLS der Abgabebox, 0133)
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR g.submission_element_ref = 'manual')
        GROUP BY e.id, le.id
    $$;
"""

_COUNTS_OLD = _COUNTS.replace("          AND g.submission_withdrawn_at IS NULL\n", "")


def upgrade() -> None:
    op.execute("ALTER TABLE submission_assignment ADD COLUMN owner_access text NOT NULL DEFAULT 'off'")
    op.execute(
        "ALTER TABLE submission_assignment ADD CONSTRAINT ck_submission_assignment_owner_access "
        "CHECK (owner_access IN ('off', 'view', 'manage'))"
    )
    op.execute("ALTER TABLE submission_upload_file ADD COLUMN withdrawn_at timestamptz")
    op.execute("ALTER TABLE gallery_image ADD COLUMN submission_withdrawn_at timestamptz")
    op.execute(
        """
        CREATE TABLE submission_access_token (
            id bigserial PRIMARY KEY,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            assignment_id bigint NOT NULL REFERENCES submission_assignment(id) ON DELETE CASCADE,
            element_ref text NOT NULL,
            participant_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            token_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            revoked_at timestamptz,
            last_used_at timestamptz,
            CONSTRAINT uq_submission_access_token_hash UNIQUE (token_hash)
        )
        """
    )
    op.execute("CREATE INDEX idx_submission_access_token_tenant ON submission_access_token (tenant_id)")
    op.execute("CREATE INDEX idx_submission_access_token_element ON submission_access_token (assignment_id, element_ref, participant_id)")
    op.execute(f"CREATE POLICY tenant_isolation ON public.submission_access_token FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.submission_access_token ENABLE ROW LEVEL SECURITY")
    op.execute(_COUNTS)


def downgrade() -> None:
    op.execute(_COUNTS_OLD)
    op.execute("DROP TABLE IF EXISTS submission_access_token")
    op.execute("ALTER TABLE gallery_image DROP COLUMN IF EXISTS submission_withdrawn_at")
    op.execute("ALTER TABLE submission_upload_file DROP COLUMN IF EXISTS withdrawn_at")
    op.execute("ALTER TABLE submission_assignment DROP CONSTRAINT IF EXISTS ck_submission_assignment_owner_access")
    op.execute("ALTER TABLE submission_assignment DROP COLUMN IF EXISTS owner_access")
