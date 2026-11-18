"""Listen mit beliebig vielen Spalten (Plan «Listen mit dynamischen Spalten», R1)

- Neue Tabelle list_column: eine Zeile je Spalte. ``key`` ist der Spalten-Key in
  list_entry.values_json und in Konfigurationen: zufällig, undurchsichtig, je Liste eindeutig
  (nicht global wie public_id) - Klonen und Mandanten-Import kopieren ihn unverändert, damit
  bleiben alle Verweise in Konfigurationen, Werten und Snapshots gültig, ohne Umschreiben. legacy_key ('column_one'/'column_two') nur für
  den Adapter alter Snapshots (app/services/list_legacy_adapter.py), wird nie neu gesetzt.
- list_entry.values_json: {"<spalten-key>": {"text_value"|"participant_id"|...}}, gleiche
  Wertform wie bisher je Spalte. GIN-Index für Personen-Bereinigung und Statistik.
- list_definition.label_column_id / responsible_column_id: Rollen statt Heuristik. Gesetzt wie
  die bisherige Heuristik, damit sich nichts ändert:
  * Bezeichnung: erste Text-Spalte (one vor two), sonst column_one (Statistik, Matrix; die
    Abgaben nahmen bisher immer column_one - weicht nur ab, wenn column_one kein Text ist und
    column_two Text; Entscheid 9.1 des Plans).
  * Verantwortliche: erste Personen-Spalte (responsible_label_service).
- RLS wie list_entry (0133/0134): sichtbar, wenn die Liste sichtbar ist; die Abgabebox liest mit.
- Die alten Spalten bleiben (nur nicht mehr NOT NULL) und werden nicht mehr geschrieben. Der
  Downgrade baut sie aus den neuen Daten wieder auf (die ersten zwei Spalten). Entfernt werden sie
  in einem späteren Release.

Revision ID: 0186_list_columns
Revises: 0185_document_page_fingerprints
Create Date: 2026-11-18
"""
from alembic import op

revision = "0186_list_columns"
down_revision = "0185_document_page_fingerprints"
branch_labels = None
depends_on = None

APP_ROLES = "hocx_app, hocx_photo_worker"
ABGABEBOX = "hocx_abgabebox"
UNSCOPED = "(SELECT public.hocx_rls_tenant()) IS NULL"
PARENT_VISIBLE = "EXISTS (SELECT 1 FROM public.list_definition p WHERE p.id = list_column.list_definition_id)"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.list_column (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT public.uuidv7() UNIQUE,
            list_definition_id bigint NOT NULL REFERENCES public.list_definition(id) ON DELETE CASCADE,
            key text NOT NULL DEFAULT (public.uuidv7())::text,
            title text NOT NULL,
            value_type text NOT NULL,
            sort_index integer NOT NULL DEFAULT 0,
            legacy_key text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_list_column_value_type CHECK (value_type IN ('text', 'participant', 'participants', 'event')),
            CONSTRAINT ck_list_column_legacy_key CHECK (legacy_key IN ('column_one', 'column_two')),
            CONSTRAINT uq_list_column_key UNIQUE (list_definition_id, key)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_list_column_legacy_key ON public.list_column (list_definition_id, legacy_key) "
        "WHERE legacy_key IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_list_column_definition_sort ON public.list_column (list_definition_id, sort_index)")
    op.execute(
        "CREATE TRIGGER trg_list_column_updated_at BEFORE UPDATE ON public.list_column "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.execute("ALTER TABLE public.list_entry ADD COLUMN values_json jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("CREATE INDEX idx_list_entry_values_json ON public.list_entry USING gin (values_json jsonb_path_ops)")
    op.execute(
        "ALTER TABLE public.list_definition "
        "ADD COLUMN label_column_id bigint REFERENCES public.list_column(id) ON DELETE SET NULL, "
        "ADD COLUMN responsible_column_id bigint REFERENCES public.list_column(id) ON DELETE SET NULL"
    )

    copy_legacy_data(op.execute)
    # Alte Felder werden nicht mehr geschrieben (Downgrade baut sie wieder auf)
    for column in ("column_one_title", "column_one_value_type", "column_two_title", "column_two_value_type"):
        op.execute(f"ALTER TABLE public.list_definition ALTER COLUMN {column} DROP NOT NULL")  # sql-ok: feste Spaltennamen

    # Rechte und RLS wie list_entry (0133_abgabebox_rls, 0134_child_table_rls)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.list_column TO hocx_app")
    op.execute("GRANT SELECT, USAGE ON SEQUENCE public.list_column_id_seq TO hocx_app")
    op.execute(f"GRANT SELECT ON TABLE public.list_column TO {ABGABEBOX}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.list_column FOR ALL TO {APP_ROLES} "
        f"USING (({UNSCOPED} OR {PARENT_VISIBLE})) WITH CHECK (({UNSCOPED} OR {PARENT_VISIBLE}))"
    )
    op.execute(f"CREATE POLICY tenant_isolation_abgabebox ON public.list_column FOR ALL TO {ABGABEBOX} USING ({PARENT_VISIBLE}) WITH CHECK ({PARENT_VISIBLE})")
    op.execute("ALTER TABLE public.list_column ENABLE ROW LEVEL SECURITY")



def copy_legacy_data(execute) -> None:
    """Übernahme der festen Spalten in list_column/values_json und Rollen. Idempotent (nur Listen
    ohne Spalten, nur leere values_json, nur fehlende Rollen) - so auch gegen Altdaten testbar
    (tests/test_migration_list_columns.py)."""
    execute(
        """
        INSERT INTO public.list_column (list_definition_id, title, value_type, sort_index, legacy_key)
        SELECT d.id, x.title, x.value_type, x.sort_index, x.legacy_key
          FROM public.list_definition d
         CROSS JOIN LATERAL (VALUES
             (d.column_one_title, d.column_one_value_type, 10, 'column_one'),
             (d.column_two_title, d.column_two_value_type, 20, 'column_two')
         ) AS x(title, value_type, sort_index, legacy_key)
         WHERE x.title IS NOT NULL AND x.value_type IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM public.list_column c WHERE c.list_definition_id = d.id)
        """
    )
    execute(
        """
        UPDATE public.list_entry e
           SET values_json = jsonb_strip_nulls(jsonb_build_object(
                   c1.key, NULLIF(e.column_one_value_json, '{}'::jsonb),
                   c2.key, NULLIF(e.column_two_value_json, '{}'::jsonb)))
          FROM public.list_column c1, public.list_column c2
         WHERE c1.list_definition_id = e.list_definition_id AND c1.legacy_key = 'column_one'
           AND c2.list_definition_id = e.list_definition_id AND c2.legacy_key = 'column_two'
           AND e.values_json = '{}'::jsonb
        """
    )
    execute(
        """
        UPDATE public.list_definition d
           SET label_column_id = COALESCE(
                   (SELECT c.id FROM public.list_column c WHERE c.list_definition_id = d.id AND c.value_type = 'text'
                     ORDER BY c.sort_index LIMIT 1),
                   (SELECT c.id FROM public.list_column c WHERE c.list_definition_id = d.id AND c.legacy_key = 'column_one'))
         WHERE d.label_column_id IS NULL
        """
    )
    execute(
        """
        UPDATE public.list_definition d
           SET responsible_column_id =
                   (SELECT c.id FROM public.list_column c WHERE c.list_definition_id = d.id
                       AND c.value_type IN ('participant', 'participants')
                     ORDER BY c.sort_index LIMIT 1)
         WHERE d.responsible_column_id IS NULL
        """
    )

def downgrade() -> None:
    # Alte Felder aus den neuen Daten aufbauen: die ersten zwei Spalten jeder Liste (nach
    # sort_index; Listen mit nur einer Spalte bekommen eine leere Text-Spalte dazu).
    op.execute(
        """
        WITH ranked AS (
            SELECT c.*, row_number() OVER (PARTITION BY c.list_definition_id ORDER BY c.sort_index, c.id) AS position
              FROM public.list_column c
        )
        UPDATE public.list_definition d
           SET column_one_title = COALESCE(one.title, ''), column_one_value_type = COALESCE(one.value_type, 'text'),
               column_two_title = COALESCE(two.title, ''), column_two_value_type = COALESCE(two.value_type, 'text')
          FROM public.list_definition d2
          LEFT JOIN ranked one ON one.list_definition_id = d2.id AND one.position = 1
          LEFT JOIN ranked two ON two.list_definition_id = d2.id AND two.position = 2
         WHERE d2.id = d.id
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT c.list_definition_id, c.key AS key,
                   row_number() OVER (PARTITION BY c.list_definition_id ORDER BY c.sort_index, c.id) AS position
              FROM public.list_column c
        )
        UPDATE public.list_entry e
           SET column_one_value_json = COALESCE(e.values_json -> (SELECT key FROM ranked r WHERE r.list_definition_id = e.list_definition_id AND r.position = 1), '{}'::jsonb),
               column_two_value_json = COALESCE(e.values_json -> (SELECT key FROM ranked r WHERE r.list_definition_id = e.list_definition_id AND r.position = 2), '{}'::jsonb)
        """
    )
    op.execute("UPDATE public.list_definition SET column_one_title = '' WHERE column_one_title IS NULL")
    op.execute("UPDATE public.list_definition SET column_two_title = '' WHERE column_two_title IS NULL")
    op.execute("UPDATE public.list_definition SET column_one_value_type = 'text' WHERE column_one_value_type IS NULL")
    op.execute("UPDATE public.list_definition SET column_two_value_type = 'text' WHERE column_two_value_type IS NULL")
    for column in ("column_one_title", "column_one_value_type", "column_two_title", "column_two_value_type"):
        op.execute(f"ALTER TABLE public.list_definition ALTER COLUMN {column} SET NOT NULL")  # sql-ok: feste Spaltennamen
    op.execute("ALTER TABLE public.list_definition DROP COLUMN responsible_column_id, DROP COLUMN label_column_id")
    op.execute("DROP INDEX public.idx_list_entry_values_json")
    op.execute("ALTER TABLE public.list_entry DROP COLUMN values_json")
    op.execute("DROP TABLE public.list_column")
