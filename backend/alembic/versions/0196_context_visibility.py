"""Kontext-Freigaben: wer sieht welche Dateien (Plan «Berechtigungen», Phase 5).

``context_visibility`` hält je Mandant
- einen **Modul-Standard** (``context_id`` NULL) für ``abgabe``, ``protokoll`` und ``album`` und
- optionale **Objekt-Overrides** (``context_id`` gesetzt), vorerst nur je Abgabe-Auftrag.

Felder:
- ``audience``: ``role_only`` (nur über Rollenrechte, keine zusätzliche Freigabe),
  ``all_participants`` (jedes Konto mit Login des Vereins), ``own_submissions`` (nur eigene
  Einreichungen; nur Abgaben).
- ``file_filter``: ``all`` oder ``images`` (nur ``image/*``).

Eine Freigabe gibt nur Lesezugriff und wirkt nur zusätzlich zu den Rollenrechten
(app/services/context_visibility_service.py). Protokolle bleiben fest ``role_only``: ihre Dateien
folgen dem Protokoll (Entwurf, Teilnehmer-Zuordnung) - eine Freigabe würde den Entwurfsschutz
umgehen.

**Seed:** jeder bestehende und jeder neue Mandant bekommt alle drei Module mit ``role_only`` -
damit wird nach dem Update nichts sichtbar, was vorher unsichtbar war (Leser/Kassier haben kein
``photos.read``; der Plan-Standard «Alben/Abgaben → alle Teilnehmenden» wäre eine
Rechteausweitung). Die Dateitypen sind wie im Plan vorbelegt (Abgaben nur Bilder, sonst alle), so
dass ein Verein nur noch «alle Teilnehmenden» wählen muss. Neue Mandanten bekommen die Zeilen per
Trigger (wie die Standardrollen, 0156).

RLS wie die übrigen Mandantentabellen (0181/0195). Der Override hängt mandantengleich am Auftrag
(Fremdschlüssel (tenant_id, context_id) → submission_assignment, ON DELETE CASCADE).

Downgrade entfernt Trigger, Funktion und Tabelle; danach gelten wieder nur Rollenrechte.

Revision ID: 0196_context_visibility
Revises: 0195_scope_and_reviewers
Create Date: 2026-11-18
"""

from alembic import op

revision = "0196_context_visibility"
down_revision = "0195_scope_and_reviewers"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"

SEED_FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_seed_context_visibility(p_tenant_id bigint) RETURNS void
    LANGUAGE plpgsql
    SET search_path = public
AS $$
BEGIN
    INSERT INTO context_visibility (tenant_id, module, context_id, audience, file_filter)
    VALUES (p_tenant_id, 'abgabe', NULL, 'role_only', 'images'),
           (p_tenant_id, 'protokoll', NULL, 'role_only', 'all'),
           (p_tenant_id, 'album', NULL, 'role_only', 'all')
    ON CONFLICT DO NOTHING;
END
$$
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.context_visibility (
            id bigserial PRIMARY KEY,
            tenant_id bigint NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            module text NOT NULL,
            context_id bigint,
            audience text NOT NULL,
            file_filter text NOT NULL DEFAULT 'all',
            updated_at timestamptz NOT NULL DEFAULT now(),
            updated_by bigint REFERENCES public.app_user(id) ON DELETE SET NULL,
            CONSTRAINT ck_context_visibility_module CHECK (module IN ('abgabe', 'protokoll', 'album')),
            CONSTRAINT ck_context_visibility_audience CHECK (audience IN ('role_only', 'all_participants', 'own_submissions')),
            CONSTRAINT ck_context_visibility_file_filter CHECK (file_filter IN ('all', 'images')),
            -- Protokoll-Dateien folgen immer dem Protokoll (Entwurfsschutz)
            CONSTRAINT ck_context_visibility_protocol CHECK (module <> 'protokoll' OR audience = 'role_only'),
            -- «Eigene Einreichungen» gibt es nur bei Abgaben
            CONSTRAINT ck_context_visibility_own CHECK (audience <> 'own_submissions' OR module = 'abgabe'),
            -- Overrides vorerst nur je Abgabe-Auftrag
            CONSTRAINT ck_context_visibility_override CHECK (context_id IS NULL OR module = 'abgabe'),
            CONSTRAINT uq_context_visibility UNIQUE NULLS NOT DISTINCT (tenant_id, module, context_id),
            CONSTRAINT fk_context_visibility_assignment FOREIGN KEY (tenant_id, context_id)
                REFERENCES public.submission_assignment (tenant_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX idx_context_visibility_context ON public.context_visibility (context_id) WHERE context_id IS NOT NULL")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.context_visibility TO hocx_app")
    op.execute("GRANT SELECT, USAGE ON SEQUENCE public.context_visibility_id_seq TO hocx_app")
    op.execute(f"CREATE POLICY tenant_isolation ON public.context_visibility FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.context_visibility ENABLE ROW LEVEL SECURITY")

    op.execute(SEED_FUNCTION)
    op.execute(
        """
        CREATE FUNCTION public.hocx_tenant_seed_context_visibility_trigger() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = public
        AS $$
        BEGIN
            PERFORM public.hocx_seed_context_visibility(NEW.id);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_tenant_seed_context_visibility AFTER INSERT ON public.tenant "
        "FOR EACH ROW EXECUTE FUNCTION public.hocx_tenant_seed_context_visibility_trigger()"
    )
    # Bestand: Standards für alle Mandanten (nur Rolle = keine Änderung gegenüber vorher)
    op.execute("SELECT public.hocx_seed_context_visibility(id) FROM public.tenant")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tenant_seed_context_visibility ON public.tenant")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_tenant_seed_context_visibility_trigger()")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_seed_context_visibility(bigint)")
    op.execute("DROP TABLE IF EXISTS public.context_visibility")
