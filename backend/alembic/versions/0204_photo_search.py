"""Fotosuche: Suchdokument je Datei und Wortschatz je Mandant (unscharf, gerankt).

Die Suche der Fotos-/Dateienseite verglich bisher die ganze Eingabe per ``ILIKE`` mit Dateiname,
Bezug, Herkunft und Tags - ohne Index, ohne Tippfehler-Toleranz, Reihenfolge der Wörter musste
stimmen. Neu (``app/services/photo_search.py``):

- ``photo_search_doc``: ein Suchdokument je ``stored_file`` mit normalisierten Wörtern nach Feld
  (``strong_terms``: Tags, Termin, Abgabe/Element, Zyklus, Album, Protokoll/Block, Word-Import;
  ``name_terms``: Dateiname; ``meta_terms``: Hochgeladen von, Kamera, Herkunft), allen Wörtern
  (``terms``, GIN), dem gefalteten Volltext (``haystack``, GIN-Trigramm für Teilstrings wie früher)
  und den Daten (``capture_on`` = wirksames Aufnahmedatum wie ``capture_date.py``, ``context_from``/
  ``context_to`` = Termin/Protokoll).
- ``photo_search_term``: Wortschatz je Mandant (Begriff + sortierte Buchstaben). Die Eingabe wird
  zuerst gegen diesen kleinen Wortschatz aufgelöst (exakt, Präfix, Teilwort, Trigramm-Ähnlichkeit,
  Levenshtein, Buchstabendreher) und erst die gefundenen Begriffe gegen die Dokumente gesucht -
  so bleibt auch die unscharfe Suche indexgestützt.

Normalisierung (einzige Stelle, Abfrage und Dokument nutzen dieselbe Funktion):
``hocx_search_fold`` = ``lower(unaccent(...))`` (ä→a, é→e, ß→ss), ``hocx_search_terms`` faltet
zusätzlich ae/oe/ue → a/o/u (Mueller = Müller = Muller) und zerlegt in Wörter aus [a-z0-9].

Aktuell gehalten durch Statement-Trigger (Übergangstabellen, ein Aufruf je Anweisung) auf allen
Quelltabellen; ``hocx_photo_search_refresh`` baut die betroffenen Dokumente neu. Die Funktionen
laufen ``SECURITY DEFINER`` mit festem ``search_path``, weil auch die Abgabebox und der Foto-Worker
Quelltabellen ändern und die Dokumente unabhängig von deren Rechten und Mandantenbindung entstehen
müssen. Sie schreiben nur in die beiden Suchtabellen und geben nichts zurück.

Papierkorb: Dokumente bleiben für Dateien im Papierkorb bestehen (Wiederherstellen), die Suche
läuft immer über die ORM-Übersicht, die ``deleted_at`` ausblendet. Endgültiges Löschen entfernt das
Dokument per ``ON DELETE CASCADE``. Der Wortschatz wächst nur (verwaiste Wörter finden nichts und
werden nie angezeigt).

RLS: ``tenant_isolation`` wie die übrigen Mandantentabellen.

Extensions ``pg_trgm``, ``unaccent``, ``fuzzystrmatch`` (contrib, im offiziellen Postgres-Image
enthalten, seit PG 13 «trusted»). Die Migration läuft mit dem Superuser-Zugang (DATABASE_URL), der
sie anlegen darf.

Revision ID: 0204_photo_search
Revises: 0203_capture_date_in_file
Create Date: 2026-11-20
"""

from alembic import op

revision = "0204_photo_search"
down_revision = "0203_capture_date_in_file"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
BACKFILL_BATCH = 2000

FUNCTIONS_SQL = r"""
CREATE OR REPLACE FUNCTION public.hocx_search_fold(p text) RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE SET search_path = pg_catalog, public
    AS $$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, coalesce(p, ''))) $$;

CREATE OR REPLACE FUNCTION public.hocx_search_terms(p text) RETURNS text[]
    LANGUAGE sql STABLE PARALLEL SAFE SET search_path = pg_catalog, public
    AS $$
        SELECT coalesce(array_agg(w ORDER BY first_pos), '{}'::text[])
          FROM (
            SELECT t.w, min(t.pos) AS first_pos
              FROM regexp_split_to_table(
                       regexp_replace(public.hocx_search_fold(p), '([aou])e', '\1', 'g'),
                       '[^a-z0-9]+'
                   ) WITH ORDINALITY AS t(w, pos)
             WHERE t.w <> '' AND length(t.w) <= 64
             GROUP BY t.w
          ) s
    $$;

CREATE OR REPLACE FUNCTION public.hocx_search_sorted(p text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog, public
    AS $$ SELECT coalesce(string_agg(c, '' ORDER BY c), '') FROM regexp_split_to_table(p, '') AS c $$;

CREATE OR REPLACE FUNCTION public.hocx_photo_search_refresh(p_ids bigint[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    BEGIN
        IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
            RETURN;
        END IF;
        WITH src AS (
            SELECT sf.id, sf.tenant_id, sf.original_name,
                   (SELECT string_agg(t, ' ')
                      FROM jsonb_array_elements_text(
                               CASE WHEN jsonb_typeof(sf.tags) = 'array' THEN sf.tags ELSE '[]'::jsonb END
                           ) AS t) AS tag_text,
                   concat_ws(' ', g.txt, pr.txt, wi.txt, su.txt, ex.txt, al.txt) AS ctx_text,
                   concat_ws(' ', u.display_name, sf.camera_make, sf.camera_model,
                             g.origin, pr.origin, wi.origin, su.origin, ex.origin) AS meta_text,
                   -- wie capture_date.effective_capture_date: Korrektur/EXIF sind «floating»
                   -- (lokale Kamerazeit als UTC gespeichert), Upload zählt als Schweizer Tag
                   coalesce((sf.capture_corrected_at AT TIME ZONE 'UTC')::date,
                            (sf.exif_taken_at AT TIME ZONE 'UTC')::date,
                            sf.estimated_taken_on,
                            (sf.created_at AT TIME ZONE 'Europe/Zurich')::date) AS capture_on,
                   coalesce(pr.d_from, wi.d_from, ex.d_from, g.d_from, su.d_from) AS d_from,
                   coalesce(pr.d_to, wi.d_to, ex.d_to, g.d_to, su.d_to) AS d_to
              FROM stored_file sf
              LEFT JOIN app_user u ON u.id = sf.created_by AND u.tenant_id = sf.tenant_id
              LEFT JOIN LATERAL (
                  SELECT concat_ws(' ', e.title, sa.title, gi.submission_element_label, cc.name) AS txt,
                         'Direkt hochgeladen'::text AS origin,
                         e.event_date AS d_from, coalesce(e.event_end_date, e.event_date) AS d_to
                    FROM gallery_image gi
                    LEFT JOIN event e ON e.id = gi.event_id AND e.tenant_id = gi.tenant_id
                    LEFT JOIN submission_assignment sa
                           ON sa.id = gi.submission_assignment_id AND sa.tenant_id = gi.tenant_id
                    LEFT JOIN cycle_config cc ON cc.id = gi.cycle_config_id AND cc.tenant_id = gi.tenant_id
                   WHERE gi.stored_file_id = sf.id
                   LIMIT 1
              ) g ON true
              LEFT JOIN LATERAL (
                  SELECT concat_ws(' ', p.protocol_number, p.title,
                                   b.block_title_snapshot, b.display_title_snapshot, b.title_snapshot) AS txt,
                         concat('Protokoll ', p.protocol_number, ' – ',
                                coalesce(b.block_title_snapshot, b.display_title_snapshot, b.title_snapshot)) AS origin,
                         p.protocol_date AS d_from, p.protocol_date AS d_to
                    FROM protocol_image pi
                    JOIN protocol_element_block b ON b.id = pi.protocol_element_block_id
                    JOIN protocol_element pe ON pe.id = b.protocol_element_id
                    JOIN protocol p ON p.id = pe.protocol_id AND p.tenant_id = sf.tenant_id
                   WHERE pi.stored_file_id = sf.id
                   LIMIT 1
              ) pr ON true
              LEFT JOIN LATERAL (
                  SELECT w.display_name AS txt, concat('Word-Import: ', w.display_name) AS origin,
                         w.protocol_date AS d_from, w.protocol_date AS d_to
                    FROM word_import_document w
                   WHERE w.stored_file_id = sf.id
                   LIMIT 1
              ) wi ON true
              LEFT JOIN LATERAL (
                  SELECT concat_ws(' ', sa.title, e.title, m.name) AS txt, concat('Abgabe: ', sa.title) AS origin,
                         e.event_date AS d_from, coalesce(e.event_end_date, e.event_date) AS d_to
                    FROM submission_upload_file f
                    JOIN submission_upload up ON up.id = f.upload_id
                    JOIN submission_assignment sa ON sa.id = up.assignment_id AND sa.tenant_id = sf.tenant_id
                    LEFT JOIN event e ON e.id = up.event_id AND e.tenant_id = sa.tenant_id
                    LEFT JOIN submission_manual_element m ON m.id = up.manual_element_id AND m.tenant_id = sa.tenant_id
                   WHERE f.stored_file_id = sf.id AND f.delete_comment IS NULL
                   LIMIT 1
              ) su ON true
              LEFT JOIN LATERAL (
                  SELECT concat_ws(' ', p.protocol_number, p.title) AS txt,
                         concat('Protokoll ', p.protocol_number, ' – Export') AS origin,
                         p.protocol_date AS d_from, p.protocol_date AS d_to
                    FROM document_file df
                    JOIN document_version dv ON dv.id = df.document_version_id
                    JOIN document d ON d.id = dv.document_id AND d.source_kind = 'protocol_export'
                                   AND d.tenant_id = sf.tenant_id
                    JOIN protocol p ON p.id = d.protocol_id
                   WHERE df.stored_file_id = sf.id AND df.role = 'original'
                   LIMIT 1
              ) ex ON true
              LEFT JOIN LATERAL (
                  -- nur Alben des eigenen Mandanten (geteilte Alben eines Partners nicht)
                  SELECT string_agg(a.name, ' ') AS txt
                    FROM photo_album_item ai
                    JOIN photo_album a ON a.id = ai.album_id AND a.tenant_id = sf.tenant_id
                   WHERE ai.file_id = sf.public_id
              ) al ON true
             WHERE sf.id = ANY(p_ids)
        ), docs AS (
            SELECT id, tenant_id,
                   public.hocx_search_terms(original_name) AS name_terms,
                   public.hocx_search_terms(concat_ws(' ', tag_text, ctx_text)) AS strong_terms,
                   public.hocx_search_terms(meta_text) AS meta_terms,
                   public.hocx_search_fold(concat_ws(' | ', original_name, tag_text, ctx_text, meta_text)) AS haystack,
                   capture_on, d_from, d_to
              FROM src
        ), upserted AS (
            INSERT INTO photo_search_doc AS d (
                stored_file_id, tenant_id, terms, strong_terms, name_terms, meta_terms, haystack,
                capture_on, context_from, context_to, updated_at
            )
            SELECT id, tenant_id,
                   ARRAY(SELECT DISTINCT x FROM unnest(name_terms || strong_terms || meta_terms) AS x),
                   strong_terms, name_terms, meta_terms, haystack, capture_on, d_from, d_to, now()
              FROM docs
            ON CONFLICT (stored_file_id) DO UPDATE
               SET tenant_id = EXCLUDED.tenant_id, terms = EXCLUDED.terms, strong_terms = EXCLUDED.strong_terms,
                   name_terms = EXCLUDED.name_terms, meta_terms = EXCLUDED.meta_terms, haystack = EXCLUDED.haystack,
                   capture_on = EXCLUDED.capture_on, context_from = EXCLUDED.context_from,
                   context_to = EXCLUDED.context_to, updated_at = EXCLUDED.updated_at
            RETURNING d.tenant_id, d.terms
        )
        INSERT INTO photo_search_term (tenant_id, term, sorted)
        SELECT DISTINCT upserted.tenant_id, t, public.hocx_search_sorted(t)
          FROM upserted, unnest(upserted.terms) AS t
        ON CONFLICT DO NOTHING;
    END;
    $$;
"""

# Je Quelltabelle: welche stored_file-IDs eine Änderung betrifft. «nt»/«ot» sind die
# Übergangstabellen (neue/alte Zeilen) der Statement-Trigger. Nur feste SQL-Bausteine.
_STORED_FILE_COLUMNS = (
    "original_name, tags, created_by, camera_make, camera_model, exif_taken_at, estimated_taken_on, "
    "capture_corrected_at, tenant_id"
)
TRIGGERS: dict[str, dict[str, str]] = {
    "stored_file": {
        "INSERT": "SELECT id FROM nt",
        "UPDATE": (
            "SELECT n.id FROM nt n JOIN ot o ON o.id = n.id "
            f"WHERE ({', '.join('n.' + c.strip() for c in _STORED_FILE_COLUMNS.split(','))}) "
            f"IS DISTINCT FROM ({', '.join('o.' + c.strip() for c in _STORED_FILE_COLUMNS.split(','))})"
        ),
    },
    "gallery_image": {
        "INSERT": "SELECT stored_file_id FROM nt",
        "UPDATE": "SELECT stored_file_id FROM nt UNION SELECT stored_file_id FROM ot",
        "DELETE": "SELECT stored_file_id FROM ot",
    },
    "protocol_image": {
        "INSERT": "SELECT stored_file_id FROM nt",
        "DELETE": "SELECT stored_file_id FROM ot",
    },
    "word_import_document": {
        "INSERT": "SELECT stored_file_id FROM nt",
        "UPDATE": (
            "SELECT n.stored_file_id FROM nt n JOIN ot o ON o.id = n.id "
            "WHERE (n.display_name, n.protocol_date) IS DISTINCT FROM (o.display_name, o.protocol_date)"
        ),
    },
    "submission_upload_file": {
        "INSERT": "SELECT stored_file_id FROM nt",
        "UPDATE": (
            "SELECT n.stored_file_id FROM nt n JOIN ot o ON o.id = n.id "
            "WHERE n.delete_comment IS DISTINCT FROM o.delete_comment"
        ),
    },
    "submission_upload": {
        "UPDATE": (
            "SELECT f.stored_file_id FROM nt n JOIN ot o ON o.id = n.id "
            "JOIN submission_upload_file f ON f.upload_id = n.id "
            "WHERE (n.assignment_id, n.event_id, n.manual_element_id) "
            "IS DISTINCT FROM (o.assignment_id, o.event_id, o.manual_element_id)"
        ),
    },
    "document_file": {
        "INSERT": "SELECT stored_file_id FROM nt WHERE role = 'original'",
    },
    "photo_album_item": {
        "INSERT": "SELECT sf.id FROM nt JOIN stored_file sf ON sf.public_id = nt.file_id",
        "DELETE": "SELECT sf.id FROM ot JOIN stored_file sf ON sf.public_id = ot.file_id",
    },
    "photo_album": {
        "UPDATE": (
            "SELECT sf.id FROM nt n JOIN ot o ON o.id = n.id AND o.name IS DISTINCT FROM n.name "
            "JOIN photo_album_item ai ON ai.album_id = n.id JOIN stored_file sf ON sf.public_id = ai.file_id"
        ),
    },
    "event": {
        "UPDATE": (
            "WITH changed AS (SELECT n.id FROM nt n JOIN ot o ON o.id = n.id "
            "WHERE (n.title, n.event_date, n.event_end_date) IS DISTINCT FROM (o.title, o.event_date, o.event_end_date)) "
            "SELECT gi.stored_file_id FROM gallery_image gi JOIN changed c ON gi.event_id = c.id "
            "UNION SELECT f.stored_file_id FROM submission_upload up JOIN changed c ON up.event_id = c.id "
            "JOIN submission_upload_file f ON f.upload_id = up.id"
        ),
    },
    "submission_assignment": {
        "UPDATE": (
            "WITH changed AS (SELECT n.id FROM nt n JOIN ot o ON o.id = n.id WHERE n.title IS DISTINCT FROM o.title) "
            "SELECT gi.stored_file_id FROM gallery_image gi JOIN changed c ON gi.submission_assignment_id = c.id "
            "UNION SELECT f.stored_file_id FROM submission_upload up JOIN changed c ON up.assignment_id = c.id "
            "JOIN submission_upload_file f ON f.upload_id = up.id"
        ),
    },
    "submission_manual_element": {
        "UPDATE": (
            "SELECT f.stored_file_id FROM nt n JOIN ot o ON o.id = n.id AND o.name IS DISTINCT FROM n.name "
            "JOIN submission_upload up ON up.manual_element_id = n.id "
            "JOIN submission_upload_file f ON f.upload_id = up.id"
        ),
    },
    "cycle_config": {
        "UPDATE": (
            "SELECT gi.stored_file_id FROM nt n JOIN ot o ON o.id = n.id AND o.name IS DISTINCT FROM n.name "
            "JOIN gallery_image gi ON gi.cycle_config_id = n.id"
        ),
    },
    "protocol": {
        "UPDATE": (
            "WITH changed AS (SELECT n.id FROM nt n JOIN ot o ON o.id = n.id "
            "WHERE (n.protocol_number, n.title, n.protocol_date) IS DISTINCT FROM (o.protocol_number, o.title, o.protocol_date)) "
            "SELECT pi.stored_file_id FROM changed c JOIN protocol_element pe ON pe.protocol_id = c.id "
            "JOIN protocol_element_block b ON b.protocol_element_id = pe.id "
            "JOIN protocol_image pi ON pi.protocol_element_block_id = b.id "
            "UNION SELECT df.stored_file_id FROM changed c JOIN document d ON d.protocol_id = c.id "
            "JOIN document_version dv ON dv.document_id = d.id "
            "JOIN document_file df ON df.document_version_id = dv.id AND df.role = 'original'"
        ),
    },
    "protocol_element_block": {
        "UPDATE": (
            "SELECT pi.stored_file_id FROM nt n JOIN ot o ON o.id = n.id "
            "AND (n.block_title_snapshot, n.display_title_snapshot, n.title_snapshot) "
            "IS DISTINCT FROM (o.block_title_snapshot, o.display_title_snapshot, o.title_snapshot) "
            "JOIN protocol_image pi ON pi.protocol_element_block_id = n.id"
        ),
    },
    "app_user": {
        "UPDATE": (
            "SELECT sf.id FROM nt n JOIN ot o ON o.id = n.id AND o.display_name IS DISTINCT FROM n.display_name "
            "JOIN stored_file sf ON sf.created_by = n.id"
        ),
    },
}

_REFERENCING = {
    "INSERT": "REFERENCING NEW TABLE AS nt",
    "UPDATE": "REFERENCING OLD TABLE AS ot NEW TABLE AS nt",
    "DELETE": "REFERENCING OLD TABLE AS ot",
}


def _function_name(table: str) -> str:
    return f"hocx_photo_search_touch_{table}"


def _trigger_name(table: str, event: str) -> str:
    return f"trg_photo_search_{event.lower()}"


def _trigger_function_sql(table: str, events: dict[str, str]) -> str:
    branches = "\n".join(
        f"""        {'IF' if index == 0 else 'ELSIF'} TG_OP = '{event}' THEN
            PERFORM public.hocx_photo_search_refresh(ARRAY(SELECT DISTINCT x.id FROM ({query}) AS x(id) WHERE x.id IS NOT NULL));"""
        for index, (event, query) in enumerate(events.items())
    )
    return f"""
CREATE OR REPLACE FUNCTION public.{_function_name(table)}() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    BEGIN
{branches}
        END IF;
        RETURN NULL;
    END;
    $$;
"""  # sql-ok: nur feste Tabellennamen und SQL-Bausteine aus diesem Modul


def upgrade() -> None:
    for extension in ("pg_trgm", "unaccent", "fuzzystrmatch"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension} WITH SCHEMA public")  # sql-ok: feste Extension-Namen

    op.execute(
        """
        CREATE TABLE photo_search_doc (
            stored_file_id bigint PRIMARY KEY REFERENCES stored_file(id) ON DELETE CASCADE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            terms text[] NOT NULL DEFAULT '{}',
            strong_terms text[] NOT NULL DEFAULT '{}',
            name_terms text[] NOT NULL DEFAULT '{}',
            meta_terms text[] NOT NULL DEFAULT '{}',
            haystack text NOT NULL DEFAULT '',
            capture_on date,
            context_from date,
            context_to date,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_photo_search_doc_tenant ON photo_search_doc (tenant_id)")
    op.execute("CREATE INDEX idx_photo_search_doc_terms ON photo_search_doc USING gin (terms)")
    op.execute("CREATE INDEX idx_photo_search_doc_haystack ON photo_search_doc USING gin (haystack gin_trgm_ops)")
    op.execute("CREATE INDEX idx_photo_search_doc_capture ON photo_search_doc (tenant_id, capture_on)")
    op.execute("CREATE INDEX idx_photo_search_doc_context ON photo_search_doc (tenant_id, context_from, context_to)")
    op.execute(
        """
        CREATE TABLE photo_search_term (
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            term text COLLATE "C" NOT NULL,
            sorted text NOT NULL,
            PRIMARY KEY (tenant_id, term)
        )
        """
    )
    op.execute("CREATE INDEX idx_photo_search_term_trgm ON photo_search_term USING gin (term gin_trgm_ops)")
    op.execute("CREATE INDEX idx_photo_search_term_length ON photo_search_term (tenant_id, length(term))")
    # Album-Namen und Album-Trigger suchen Einträge nach Datei (der Primärschlüssel beginnt mit album_id)
    op.execute("CREATE INDEX IF NOT EXISTS idx_photo_album_item_file ON photo_album_item (file_id)")

    for table in ("photo_search_doc", "photo_search_term"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Tabellen/Policy
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname

    op.execute(FUNCTIONS_SQL)
    for table, events in TRIGGERS.items():
        op.execute(_trigger_function_sql(table, events))
        for event in events:
            op.execute(
                f"CREATE TRIGGER {_trigger_name(table, event)} AFTER {event} ON public.{table} "  # sql-ok: feste Bezeichner
                f"{_REFERENCING[event]} FOR EACH STATEMENT EXECUTE FUNCTION public.{_function_name(table)}()"
            )

    # Bestand indexieren, in Portionen (je Aufruf ein Satz IDs)
    bind = op.get_bind()
    last_id = 0
    while True:
        ids = [
            row[0]
            for row in bind.exec_driver_sql(
                "SELECT id FROM stored_file WHERE id > %(last)s ORDER BY id LIMIT %(n)s",
                {"last": last_id, "n": BACKFILL_BATCH},
            ).all()
        ]
        if not ids:
            break
        bind.exec_driver_sql("SELECT public.hocx_photo_search_refresh(%(ids)s::bigint[])", {"ids": ids})
        last_id = ids[-1]


def downgrade() -> None:
    for table, events in TRIGGERS.items():
        for event in events:
            op.execute(f"DROP TRIGGER IF EXISTS {_trigger_name(table, event)} ON public.{table}")  # sql-ok: feste Bezeichner
        op.execute(f"DROP FUNCTION IF EXISTS public.{_function_name(table)}()")  # sql-ok: fester Funktionsname
    op.execute("DROP FUNCTION IF EXISTS public.hocx_photo_search_refresh(bigint[])")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_search_sorted(text)")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_search_terms(text)")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_search_fold(text)")
    op.execute("DROP INDEX IF EXISTS idx_photo_album_item_file")
    op.execute("DROP TABLE IF EXISTS photo_search_term")
    op.execute("DROP TABLE IF EXISTS photo_search_doc")
    # Extensions bleiben bewusst bestehen (harmlos, evtl. später anderweitig genutzt).
