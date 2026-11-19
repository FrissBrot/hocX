"""Einzelabgaben mit mehreren Abgabeelementen (``submission_manual_element``).

Bisher hatte eine Abgabe mit ``source_type = 'manual'`` genau ein Element: die Abgabe selbst
(``element_ref = 'manual'``, Einreichungen ohne ``event_id``/``list_entry_id``, Migration 0080).
Neu legt man die Elemente von Hand an: Name, optional Zeitfenster (Start/Ende) und Verantwortliche.
Sie verhalten sich wie Termin- und Listenelemente (eigene Kachel, eigene Pendenz, eigener Upload).

- ``submission_manual_element``: ``tenant_id`` NOT NULL, mandantengleicher Fremdschlüssel
  (tenant_id, assignment_id) → submission_assignment, ON DELETE CASCADE. Höchstens ein
  Standard-Element (``is_default``) je Abgabe; es behält die Referenz ``manual``, alle anderen heissen
  ``manual-<public_id>``. Verantwortliche als JSONB-Liste von Personen-IDs wie bei Terminen
  (``event.spezial1_ids``); das Backend prüft beim Schreiben, dass alle zum Mandanten gehören.
- ``submission_upload.manual_element_id``: Einreichung eines zusätzlichen Elements. Das
  Standard-Element bleibt beim bisherigen Schlüssel (alle drei Ziele NULL), damit bestehende
  Einreichungen, verknüpfte Dateien (``gallery_image.submission_element_ref = 'manual'``),
  Upload-Log, Pendenzen und persönliche Links unverändert dazu gehören. Der Fremdschlüssel
  (assignment_id, manual_element_id) → (assignment_id, id) verhindert, dass eine Einreichung auf ein
  Element einer anderen Abgabe zeigt - auch aus der Abgabebox.
- Backfill: jede bestehende Einzelabgabe bekommt genau ein Standard-Element, Name = Titel der
  Abgabe, Ende = bisheriger Stichtag. Der Stichtag der Abgabe selbst entfällt danach für Einzelabgaben
  (CHECK), es gilt das Zeitfenster je Element.
- RLS: ``tenant_isolation`` für hocx_app/hocx_photo_worker (Mandantenbindung wie 0132),
  ``tenant_isolation_abgabebox`` nur lesend für den Mandanten des gesetzten Upload-Links (0133).
  Die Abgabebox liest nur die Spalten, die sie zum Anzeigen braucht (keine Verantwortlichen).
- Trigger ``sync_todo_status_on_submission_file`` (0175) und die Zählfunktionen der Abgabebox
  ``submission_linked_file_counts`` (0181) und ``submission_withdrawn_elements`` (0182) kennen das
  neue Ziel; die beiden Funktionen liefern dafür eine zusätzliche Spalte ``manual_element_id``.

Downgrade: Einreichungen, verknüpfte Dateien und Upload-Log der zusätzlichen Elemente werden dem
einzigen Element der Einzelabgabe zugeschlagen (nichts wird gelöscht), persönliche Links der
zusätzlichen Elemente widerrufen; der Stichtag kommt vom Standard-Element zurück (ohne
Standard-Element: das späteste Ende). Pendenzen zusätzlicher Elemente bleiben als Verlauf stehen.

Revision ID: 0198_submission_manual_elements
Revises: 0197_photo_worker_columns
Create Date: 2026-11-19
"""

from alembic import op

revision = "0198_submission_manual_elements"
down_revision = "0197_photo_worker_columns"
branch_labels = None
depends_on = None

APP_ROLES = "hocx_app, hocx_photo_worker"
ABGABEBOX = "hocx_abgabebox"
SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
LINK_TENANT = "(SELECT public.hocx_rls_abgabebox_tenant())"
# Was die Abgabebox liest (app/models.py submission_manual_element_table) - keine Verantwortlichen
ABGABEBOX_COLUMNS = ("id", "public_id", "tenant_id", "assignment_id", "is_default", "name", "window_start", "window_end", "sort_index")

_DONE = 3

SOURCE_FIELDS_NEW = (
    "(source_type = 'events' AND tag_filter IS NOT NULL "
    "AND list_definition_id IS NULL AND deadline IS NULL) OR "
    "(source_type = 'list' AND list_definition_id IS NOT NULL "
    "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL) OR "
    "(source_type = 'manual' AND tag_filter IS NULL AND list_definition_id IS NULL "
    "AND offset_days_before IS NULL AND offset_days_after IS NULL AND deadline IS NULL)"
)
SOURCE_FIELDS_OLD = (
    "(source_type = 'events' AND tag_filter IS NOT NULL "
    "AND list_definition_id IS NULL AND deadline IS NULL) OR "
    "(source_type = 'list' AND list_definition_id IS NOT NULL "
    "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL) OR "
    "(source_type = 'manual' AND tag_filter IS NULL AND list_definition_id IS NULL "
    "AND offset_days_before IS NULL AND offset_days_after IS NULL)"
)


def _todo_trigger(manual_branch: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION public.sync_todo_status_on_submission_file() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        DECLARE
            v_upload submission_upload%ROWTYPE;
            v_refs TEXT[];
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM stored_file sf WHERE sf.id = NEW.stored_file_id AND sf.scan_status = 'clean'
            ) THEN
                RETURN NEW;
            END IF;
            SELECT * INTO v_upload FROM submission_upload u WHERE u.id = NEW.upload_id;
            IF NOT FOUND OR v_upload.status <> 'submitted' OR v_upload.submitted_at IS NULL THEN
                RETURN NEW;
            END IF;

            IF v_upload.event_id IS NOT NULL THEN
                SELECT ARRAY['event-' || e.public_id::TEXT, 'event-' || e.id::TEXT]
                  INTO v_refs FROM event e WHERE e.id = v_upload.event_id;
            ELSIF v_upload.list_entry_id IS NOT NULL THEN
                SELECT ARRAY['entry-' || le.public_id::TEXT, 'entry-' || le.id::TEXT]
                  INTO v_refs FROM list_entry le WHERE le.id = v_upload.list_entry_id;
{manual_branch}            ELSE
                v_refs := ARRAY['manual'];
            END IF;
            IF v_refs IS NULL THEN
                RETURN NEW;
            END IF;

            UPDATE protocol_todo
            SET todo_status_id = {_DONE},
                completed_at = v_upload.submitted_at
            WHERE submission_assignment_id = v_upload.assignment_id
              AND element_ref = ANY(v_refs)
              AND todo_status_id <> {_DONE};
            RETURN NEW;
        END;
    $$;
"""  # sql-ok: nur feste Status-IDs und Code-Bausteine aus diesem Modul


_MANUAL_BRANCH = """            ELSIF v_upload.manual_element_id IS NOT NULL THEN
                SELECT ARRAY[CASE WHEN m.is_default THEN 'manual' ELSE 'manual-' || m.public_id::TEXT END]
                  INTO v_refs FROM submission_manual_element m WHERE m.id = v_upload.manual_element_id;
"""

_COUNTS = """
CREATE FUNCTION public.submission_linked_file_counts(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT, manual_element_id BIGINT, file_count INTEGER)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT e.id, le.id, m.id, COUNT(*)::INTEGER
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        LEFT JOIN submission_manual_element m
          ON g.submission_element_ref = 'manual-' || m.public_id::TEXT AND m.assignment_id = a.id AND NOT m.is_default
        WHERE g.submission_assignment_id = p_assignment_id
          AND g.submission_withdrawn_at IS NULL
          -- nur der Mandant des gesetzten Upload-Links (wie die RLS der Abgabebox, 0133)
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR m.id IS NOT NULL OR g.submission_element_ref = 'manual')
        GROUP BY e.id, le.id, m.id
    $$;
"""

_COUNTS_OLD = """
CREATE FUNCTION public.submission_linked_file_counts(p_assignment_id BIGINT)
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

_WITHDRAWN = """
CREATE FUNCTION public.submission_withdrawn_elements(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT, manual_element_id BIGINT)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT DISTINCT u.event_id, u.list_entry_id, u.manual_element_id
        FROM submission_upload_file f
        JOIN submission_upload u ON u.id = f.upload_id
        JOIN submission_assignment a ON a.id = u.assignment_id
        WHERE u.assignment_id = p_assignment_id
          AND f.withdrawn_at IS NOT NULL
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
        UNION
        SELECT e.id, le.id, m.id
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        LEFT JOIN submission_manual_element m
          ON g.submission_element_ref = 'manual-' || m.public_id::TEXT AND m.assignment_id = a.id AND NOT m.is_default
        WHERE g.submission_assignment_id = p_assignment_id
          AND g.submission_withdrawn_at IS NOT NULL
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR m.id IS NOT NULL OR g.submission_element_ref = 'manual')
    $$;
"""

_WITHDRAWN_OLD = """
CREATE FUNCTION public.submission_withdrawn_elements(p_assignment_id BIGINT)
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


def _replace_abgabebox_functions(counts: str, withdrawn: str) -> None:
    # Andere Rückgabespalten: CREATE OR REPLACE geht nicht, Rechte danach neu setzen
    op.execute("DROP FUNCTION IF EXISTS public.submission_linked_file_counts(BIGINT)")
    op.execute("DROP FUNCTION IF EXISTS public.submission_withdrawn_elements(BIGINT)")
    op.execute(counts)
    op.execute(withdrawn)
    for function in ("submission_linked_file_counts", "submission_withdrawn_elements"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}(BIGINT) FROM PUBLIC")  # sql-ok: feste Funktionsnamen
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{function}(BIGINT) TO {ABGABEBOX}")  # sql-ok: feste Funktionsnamen


def backfill_default_elements(execute) -> None:
    """Je bestehender Einzelabgabe ohne Elemente genau ein Standard-Element: Name = Titel, Ende =
    bisheriger Stichtag. Idempotent (tests/test_submission_manual_elements.py)."""
    execute(
        """
        INSERT INTO public.submission_manual_element (tenant_id, assignment_id, is_default, name, window_end, sort_index)
        SELECT a.tenant_id, a.id, true, COALESCE(NULLIF(left(btrim(a.title), 200), ''), 'Abgabe'), a.deadline, 0
          FROM public.submission_assignment a
         WHERE a.source_type = 'manual'
           AND NOT EXISTS (SELECT 1 FROM public.submission_manual_element m WHERE m.assignment_id = a.id)
        """
    )
    execute("UPDATE public.submission_assignment SET deadline = NULL WHERE source_type = 'manual' AND deadline IS NOT NULL")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.submission_manual_element (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT public.uuidv7(),
            tenant_id bigint NOT NULL REFERENCES public.tenant(id) ON DELETE CASCADE,
            assignment_id bigint NOT NULL,
            is_default boolean NOT NULL DEFAULT false,
            name text NOT NULL,
            window_start date,
            window_end date,
            responsible_participant_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            sort_index integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_submission_manual_element_public_id UNIQUE (public_id),
            -- Ziel des Fremdschlüssels aus submission_upload (Element gehört zur Abgabe der Einreichung)
            CONSTRAINT uq_submission_manual_element_assignment_id UNIQUE (assignment_id, id),
            CONSTRAINT fk_submission_manual_element_assignment FOREIGN KEY (tenant_id, assignment_id)
                REFERENCES public.submission_assignment (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_submission_manual_element_name CHECK (length(btrim(name)) BETWEEN 1 AND 200),
            CONSTRAINT ck_submission_manual_element_window
                CHECK (window_start IS NULL OR window_end IS NULL OR window_start <= window_end),
            CONSTRAINT ck_submission_manual_element_responsible CHECK (jsonb_typeof(responsible_participant_ids) = 'array')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_submission_manual_element_default ON public.submission_manual_element (assignment_id) WHERE is_default"
    )
    op.execute("CREATE INDEX idx_submission_manual_element_tenant ON public.submission_manual_element (tenant_id)")
    op.execute("CREATE INDEX idx_submission_manual_element_assignment ON public.submission_manual_element (assignment_id, sort_index)")
    op.execute(
        "CREATE TRIGGER trg_submission_manual_element_updated_at BEFORE UPDATE ON public.submission_manual_element "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.submission_manual_element TO hocx_app")
    op.execute("GRANT SELECT, USAGE ON SEQUENCE public.submission_manual_element_id_seq TO hocx_app")
    op.execute(f"GRANT SELECT ({', '.join(ABGABEBOX_COLUMNS)}) ON TABLE public.submission_manual_element TO {ABGABEBOX}")  # sql-ok: feste Spaltennamen
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.submission_manual_element FOR ALL TO {APP_ROLES} "
        f"USING {BASE} WITH CHECK {BASE}"
    )  # sql-ok: feste Policy-Ausdrücke
    op.execute(
        f"CREATE POLICY tenant_isolation_abgabebox ON public.submission_manual_element FOR SELECT TO {ABGABEBOX} "
        f"USING (tenant_id = {LINK_TENANT})"
    )  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.submission_manual_element ENABLE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE public.submission_upload ADD COLUMN manual_element_id bigint")
    op.execute(
        "ALTER TABLE public.submission_upload ADD CONSTRAINT fk_submission_upload_manual_element "
        "FOREIGN KEY (assignment_id, manual_element_id) REFERENCES public.submission_manual_element (assignment_id, id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX idx_submission_upload_manual_element ON public.submission_upload (manual_element_id) WHERE manual_element_id IS NOT NULL")
    op.execute("ALTER TABLE public.submission_upload DROP CONSTRAINT ck_submission_upload_at_most_one_target")
    op.execute(
        "ALTER TABLE public.submission_upload ADD CONSTRAINT ck_submission_upload_at_most_one_target "
        "CHECK (num_nonnulls(event_id, list_entry_id, manual_element_id) <= 1)"
    )
    op.execute(f"GRANT SELECT (manual_element_id), INSERT (manual_element_id) ON TABLE public.submission_upload TO {ABGABEBOX}")

    backfill_default_elements(op.execute)
    op.execute("ALTER TABLE public.submission_assignment DROP CONSTRAINT ck_submission_assignment_source_fields")
    op.execute(f"ALTER TABLE public.submission_assignment ADD CONSTRAINT ck_submission_assignment_source_fields CHECK ({SOURCE_FIELDS_NEW})")  # sql-ok: feste Bedingung

    op.execute(_todo_trigger(_MANUAL_BRANCH))
    _replace_abgabebox_functions(_COUNTS, _WITHDRAWN)


def downgrade() -> None:
    _replace_abgabebox_functions(_COUNTS_OLD, _WITHDRAWN_OLD)
    op.execute(_todo_trigger(""))

    op.execute("ALTER TABLE public.submission_assignment DROP CONSTRAINT ck_submission_assignment_source_fields")
    op.execute(f"ALTER TABLE public.submission_assignment ADD CONSTRAINT ck_submission_assignment_source_fields CHECK ({SOURCE_FIELDS_OLD})")  # sql-ok: feste Bedingung
    op.execute(
        """
        UPDATE public.submission_assignment a
           SET deadline = COALESCE(
                   (SELECT m.window_end FROM public.submission_manual_element m WHERE m.assignment_id = a.id AND m.is_default),
                   (SELECT max(m.window_end) FROM public.submission_manual_element m WHERE m.assignment_id = a.id))
         WHERE a.source_type = 'manual'
        """
    )
    # Zusätzliche Elemente gehen im einen Element der Einzelabgabe auf (nichts wird gelöscht)
    op.execute(
        """
        UPDATE public.gallery_image g SET submission_element_ref = 'manual'
          FROM public.submission_assignment a
         WHERE a.id = g.submission_assignment_id AND a.source_type = 'manual' AND g.submission_element_ref LIKE 'manual-%'
        """
    )
    op.execute(
        """
        UPDATE public.submission_upload_log l SET element_ref = 'manual'
          FROM public.submission_assignment a
         WHERE a.id = l.assignment_id AND a.source_type = 'manual' AND l.element_ref LIKE 'manual-%'
        """
    )
    op.execute(
        "UPDATE public.submission_access_token SET revoked_at = now() "
        "WHERE element_ref LIKE 'manual-%' AND revoked_at IS NULL"
    )
    op.execute("ALTER TABLE public.submission_upload DROP CONSTRAINT IF EXISTS fk_submission_upload_manual_element")
    op.execute("UPDATE public.submission_upload SET manual_element_id = NULL WHERE manual_element_id IS NOT NULL")
    op.execute("ALTER TABLE public.submission_upload DROP CONSTRAINT ck_submission_upload_at_most_one_target")
    op.execute(
        "ALTER TABLE public.submission_upload ADD CONSTRAINT ck_submission_upload_at_most_one_target "
        "CHECK (event_id IS NULL OR list_entry_id IS NULL)"
    )
    op.execute("DROP INDEX IF EXISTS public.idx_submission_upload_manual_element")
    op.execute("ALTER TABLE public.submission_upload DROP COLUMN manual_element_id")
    op.execute("DROP TABLE IF EXISTS public.submission_manual_element")
