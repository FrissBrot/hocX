"""Keywords für Dateien und Fotos, Synonyme für die Suche (hocX 1.5.1).

- ``stored_file.keywords`` (``text[]``, leer als Standard): kurze Suchbegriffe je Datei, «weniger
  verbindlich als Tags» - nirgends prominent angezeigt, nur für die Suche. Gehört über die Datei
  zum Mandanten (``stored_file.tenant_id`` + bestehende RLS), daher keine eigene Tabelle. Die
  Spalte ist neu und leer, ein Backfill der Suchdokumente ist nicht nötig.
- Suchdokument (0204): ``hocx_photo_search_refresh`` nimmt die Keywords in die starken Wörter
  (``strong_terms``, Gewicht 1.0 wie Tags) und den Volltext (``haystack``) auf; damit landen sie
  auch im Wortschatz ``photo_search_term`` (Tippfehler-Toleranz). Der Statement-Trigger auf
  ``stored_file`` vergleicht zusätzlich ``keywords``, damit eine Änderung das Dokument neu baut.
  Die Funktionen entstehen aus dem (unveränderlichen) Text von 0204 mit drei geprüften Ersetzungen.
- ``search_synonym_group``: mandanteneigene Synonymgruppen (Mandanten-Einstellungen › Suche).
  ``words`` wie eingegeben, ``terms`` normalisiert wie ``hocx_search_terms`` (je Eintrag ein Wort).
  ``tenant_id`` NOT NULL, RLS ``tenant_isolation`` wie 0204. Der eingebaute Grundstock steht im
  Repo (``app/services/search_synonyms_builtin.json``), nicht in der Datenbank.

Revision ID: 0217_file_keywords_synonyms
Revises: 0208_platform_metrics
Create Date: 2026-11-21
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic import op

revision = "0217_file_keywords_synonyms"
down_revision = "0208_platform_metrics"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def _photo_search_migration():
    """Lädt 0204 (bereits produktiv, wird nie mehr geändert) als Modul, um dessen SQL wiederzuverwenden."""
    path = Path(__file__).with_name("0204_photo_search.py")
    spec = importlib.util.spec_from_file_location("hocx_migration_0204_photo_search", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_REPLACEMENTS = (
    (
        "concat_ws(' ', g.txt, pr.txt, wi.txt, su.txt, ex.txt, al.txt) AS ctx_text,",
        "concat_ws(' ', g.txt, pr.txt, wi.txt, su.txt, ex.txt, al.txt) AS ctx_text,\n"
        "                   array_to_string(sf.keywords, ' ') AS kw_text,",
    ),
    (
        "public.hocx_search_terms(concat_ws(' ', tag_text, ctx_text)) AS strong_terms,",
        "public.hocx_search_terms(concat_ws(' ', tag_text, kw_text, ctx_text)) AS strong_terms,",
    ),
    (
        "public.hocx_search_fold(concat_ws(' | ', original_name, tag_text, ctx_text, meta_text)) AS haystack,",
        "public.hocx_search_fold(concat_ws(' | ', original_name, tag_text, kw_text, ctx_text, meta_text)) AS haystack,",
    ),
)


def _functions_with_keywords(base_sql: str) -> str:
    sql = base_sql
    for old, new in _REPLACEMENTS:
        if sql.count(old) != 1:
            raise RuntimeError(f"0204-Funktionstext unerwartet, Baustein fehlt: {old}")
        sql = sql.replace(old, new)
    return sql


def _stored_file_trigger_sql(module, columns: str) -> str:
    cols = [column.strip() for column in columns.split(",")]
    update = (
        "SELECT n.id FROM nt n JOIN ot o ON o.id = n.id "
        f"WHERE ({', '.join('n.' + c for c in cols)}) IS DISTINCT FROM ({', '.join('o.' + c for c in cols)})"
    )
    events = {"INSERT": "SELECT id FROM nt", "UPDATE": update}
    return module._trigger_function_sql("stored_file", events)


def upgrade() -> None:
    base = _photo_search_migration()

    op.execute("ALTER TABLE stored_file ADD COLUMN keywords text[] NOT NULL DEFAULT '{}'")

    op.execute(
        """
        CREATE TABLE search_synonym_group (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            position integer NOT NULL DEFAULT 0,
            words text[] NOT NULL,
            terms text[] NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_search_synonym_group_size CHECK (
                cardinality(words) BETWEEN 2 AND 20 AND cardinality(terms) BETWEEN 2 AND 20
            )
        )
        """
    )
    op.execute("CREATE INDEX idx_search_synonym_group_tenant ON search_synonym_group (tenant_id, position)")
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.search_synonym_group FOR ALL USING {BASE} WITH CHECK {BASE}"  # sql-ok: feste Policy
    )
    op.execute("ALTER TABLE public.search_synonym_group ENABLE ROW LEVEL SECURITY")

    # Suchdokument mit Keywords; CREATE OR REPLACE behält Eigentümer und (entzogene) Rechte.
    op.execute(_functions_with_keywords(base.FUNCTIONS_SQL))
    op.execute(_stored_file_trigger_sql(base, base._STORED_FILE_COLUMNS + ", keywords"))


def downgrade() -> None:
    base = _photo_search_migration()
    op.execute(_stored_file_trigger_sql(base, base._STORED_FILE_COLUMNS))
    op.execute(base.FUNCTIONS_SQL)
    op.execute("DROP TABLE IF EXISTS search_synonym_group")
    # Suchdokumente mit Keywords neu bauen, bevor die Spalte verschwindet
    op.execute(
        "SELECT public.hocx_photo_search_refresh(ARRAY(SELECT id FROM stored_file WHERE cardinality(keywords) > 0))"
    )
    op.execute("ALTER TABLE stored_file DROP COLUMN IF EXISTS keywords")
