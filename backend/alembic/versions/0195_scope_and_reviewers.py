"""Reichweite «zugewiesene» und Prüfer je Abgabe-Auftrag (Plan «Berechtigungen», Phase 4).

- ``tenant_role_permission.scope``: Reichweite eines Rechts in einer Rolle. NULL = alle (bisheriges
  Verhalten, alle bestehenden Zeilen), ``'assigned'`` = nur zugewiesene Objekte. Welche Rechte eine
  Reichweite haben, steht im Katalog (``permissions/catalog.json``, Feld ``scopes``); die Datenbank
  erlaubt eine Reichweite nur für diese Rechte (zweite Sicherung neben role_service).
- ``resource_assignment``: Zuweisung eines Kontos zu einem Objekt in einer Funktion, vorerst nur
  Prüfer (``function = 'reviewer'``) eines Abgabe-Auftrags. Fremdschlüssel mandantengleich über
  (tenant_id, …) wie user_role (0156): ein Konto kann nie einem Auftrag eines anderen Mandanten
  zugewiesen werden. Löschen des Auftrags oder des Kontos löscht die Zuweisung mit. Solange
  ``resource_type`` nur ``'submission_assignment'`` kennt, hängt ``resource_id`` per Fremdschlüssel
  am Auftrag; kommt ein weiterer Typ dazu, ersetzt eine neue Revision den Schlüssel durch Trigger.
- RLS wie die übrigen Mandantentabellen (0181): sichtbar nur im eigenen Mandanten.

Downgrade entfernt Tabelle und Spalte; Rollen mit «nur zugewiesene» wirken danach wieder auf alle
Aufträge (wie vor 0195).

Revision ID: 0195_scope_and_reviewers
Revises: 0194_plan_prices_complete
Create Date: 2026-11-18
"""

from alembic import op

revision = "0195_scope_and_reviewers"
down_revision = "0194_plan_prices_complete"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
# Rechte mit Reichweite (permissions/catalog.json, "scopes") - neue erfordern eine neue Revision.
SCOPED_KEYS = "('submissions.read', 'submissions.review')"


def upgrade() -> None:
    op.execute("ALTER TABLE public.tenant_role_permission ADD COLUMN scope text")
    op.execute(
        "ALTER TABLE public.tenant_role_permission ADD CONSTRAINT ck_tenant_role_permission_scope "
        f"CHECK (scope IS NULL OR (scope IN ('all', 'assigned') AND permission_key IN {SCOPED_KEYS}))"  # sql-ok: feste Liste aus dem Katalog
    )

    # Ziel des mandantengleichen Fremdschlüssels (wie uq_app_user_tenant_id in 0156)
    op.execute("ALTER TABLE public.submission_assignment ADD CONSTRAINT uq_submission_assignment_tenant_id UNIQUE (tenant_id, id)")
    op.execute(
        """
        CREATE TABLE public.resource_assignment (
            id bigserial PRIMARY KEY,
            tenant_id bigint NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            resource_type text NOT NULL,
            resource_id bigint NOT NULL,
            user_id bigint NOT NULL,
            function text NOT NULL DEFAULT 'reviewer',
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by bigint REFERENCES public.app_user(id) ON DELETE SET NULL,
            CONSTRAINT ck_resource_assignment_type CHECK (resource_type IN ('submission_assignment')),
            CONSTRAINT ck_resource_assignment_function CHECK (function IN ('reviewer')),
            CONSTRAINT uq_resource_assignment UNIQUE (tenant_id, resource_type, resource_id, user_id, function),
            CONSTRAINT fk_resource_assignment_user FOREIGN KEY (tenant_id, user_id)
                REFERENCES public.app_user (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_resource_assignment_submission FOREIGN KEY (tenant_id, resource_id)
                REFERENCES public.submission_assignment (tenant_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX idx_resource_assignment_user ON public.resource_assignment (user_id, resource_type)")
    op.execute("CREATE INDEX idx_resource_assignment_resource ON public.resource_assignment (resource_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.resource_assignment TO hocx_app")
    op.execute("GRANT SELECT, USAGE ON SEQUENCE public.resource_assignment_id_seq TO hocx_app")
    op.execute(f"CREATE POLICY tenant_isolation ON public.resource_assignment FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.resource_assignment ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.resource_assignment")
    op.execute("ALTER TABLE public.submission_assignment DROP CONSTRAINT IF EXISTS uq_submission_assignment_tenant_id")
    op.execute("ALTER TABLE public.tenant_role_permission DROP CONSTRAINT IF EXISTS ck_tenant_role_permission_scope")
    op.execute("ALTER TABLE public.tenant_role_permission DROP COLUMN IF EXISTS scope")
