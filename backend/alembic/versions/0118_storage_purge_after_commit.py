"""Objektspeicher: Löschen erst nach dem Commit (S3-008).

Bisher löschte ObjectStore.delete das Objekt sofort physisch und registrierte die Löschung in der
Transaktion des Aufrufers. Rollte diese zurück (z. B. weil das Entfernen der Datenbankzeile
scheiterte), zeigte die Zeile auf ein Objekt, das es nicht mehr gab. Ab jetzt:

- delete registriert nur einen Tombstone (status 'deleted', purge_pending = true) in der
  Transaktion des Aufrufers. Ein Rollback nimmt ihn mit zurück, das Objekt bleibt erhalten.
- Der Job storage_purge löscht nach dem Commit physisch. storage_purge_claim sperrt die Zeilen
  (FOR UPDATE SKIP LOCKED), storage_purge_done quittiert nur, wenn die Version noch dieselbe ist.
  Ein neuer put desselben Keys setzt purge_pending zurück; zusätzlich halten Schreiber und Job
  denselben Advisory-Lock je Key, damit das verzögerte Löschen nie neuen Inhalt trifft.

Rein additiv: neue Spalte mit Default, CREATE OR REPLACE der Registerfunktion (Signatur und
Rechte unverändert), zwei neue Funktionen nur für hocx_app. Der Downgrade stellt die Fassung aus
0115 wieder her; noch nicht gelöschte Tombstones bleiben dann als Objekte liegen (der
Prüfbericht der Migration zeigt sie als verwaist).

Revision ID: 0118_storage_purge_after_commit
Revises: 0117_s3_merge_main
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0118_storage_purge_after_commit"
down_revision = "0117_s3_merge_main"
branch_labels = None
depends_on = None


def _register_write_sql(*, with_purge: bool) -> str:
    # Eingefroren: Text der Fassung aus 0115_storage_role_scoping, nur purge_pending ergänzt.
    insert_columns = "namespace, key, size_bytes, sha256, content_type, version, status, generation"
    insert_values = (
        "p_namespace, p_key, p_size, p_sha256, p_content_type, 1,\n"
        "                  CASE WHEN p_op = 'put' THEN 'active' ELSE 'deleted' END, p_generation"
    )
    update_purge = ""
    if with_purge:
        insert_columns += ", purge_pending"
        insert_values += ", p_op = 'delete'"
        update_purge = "\n            purge_pending = EXCLUDED.purge_pending,"
    return rf"""
        CREATE OR REPLACE FUNCTION public.storage_register_write(
            p_namespace text, p_key text, p_op text, p_size bigint, p_sha256 text, p_content_type text,
            p_generation bigint
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_active_generation bigint;
          v_version bigint;
        BEGIN
          IF p_namespace NOT IN ('main', 'abgabebox') THEN
            RAISE EXCEPTION 'invalid storage namespace: %', p_namespace;
          END IF;
          IF p_key IS NULL OR length(p_key) = 0 OR length(p_key) > 1024 OR p_key ~ '[[:cntrl:]\\]'
             OR p_key ~ '(^/|//|(^|/)\.\.?(/|$))' THEN
            RAISE EXCEPTION 'invalid storage key';
          END IF;
          -- Die öffentlich erreichbare Abgabebox schreibt nur in ihren eigenen Namespace; ein
          -- Journaleintrag für "main" könnte sonst bei der nächsten Migration Daten im Ziel löschen.
          IF session_user = 'hocx_abgabebox' AND p_namespace <> 'abgabebox' THEN
            RAISE EXCEPTION 'storage namespace % not permitted for %', p_namespace, session_user USING ERRCODE = '42501';
          END IF;
          IF p_op NOT IN ('put', 'delete') THEN
            RAISE EXCEPTION 'invalid storage op: %', p_op;
          END IF;
          IF p_sha256 IS NOT NULL AND p_sha256 !~ '^[0-9a-f]{{64}}$' THEN
            RAISE EXCEPTION 'invalid sha256';
          END IF;
          -- Der Aufrufer muss vorher storage_begin_write() in derselben Transaktion aufgerufen
          -- haben; die Generation muss noch die aktive sein (sonst hat ein Cutover dazwischen
          -- stattgefunden und der Schreibvorgang landete in der falschen Quelle).
          SELECT s.active_generation INTO v_active_generation FROM public.storage_state s WHERE s.id = 1 FOR SHARE;
          IF v_active_generation <> p_generation THEN
            RAISE EXCEPTION 'HOCX_STORAGE_GENERATION_CHANGED' USING ERRCODE = '40001';
          END IF;

          INSERT INTO public.storage_object AS o ({insert_columns})
          VALUES ({insert_values})
          ON CONFLICT (namespace, key) DO UPDATE SET
            size_bytes = CASE WHEN p_op = 'put' THEN EXCLUDED.size_bytes ELSE o.size_bytes END,
            sha256 = CASE WHEN p_op = 'put' THEN EXCLUDED.sha256 ELSE o.sha256 END,
            content_type = CASE WHEN p_op = 'put' THEN EXCLUDED.content_type ELSE o.content_type END,
            version = o.version + 1,
            status = EXCLUDED.status,{update_purge}
            generation = EXCLUDED.generation,
            updated_at = NOW()
          RETURNING o.version INTO v_version;

          INSERT INTO public.storage_change_outbox (namespace, key, op, size_bytes, sha256, version, generation)
          VALUES (p_namespace, p_key, p_op, p_size, p_sha256, v_version, p_generation);
          RETURN v_version;
        END
        $$
    """


def upgrade() -> None:
    op.add_column(
        "storage_object",
        sa.Column("purge_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "idx_storage_object_purge_pending", "storage_object", ["updated_at"],
        postgresql_where=sa.text("purge_pending"),
    )
    op.execute(_register_write_sql(with_purge=True))
    op.execute(r"""
        CREATE FUNCTION public.storage_purge_claim(p_limit integer)
        RETURNS TABLE (namespace text, key text, version bigint, generation bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          -- Die Zeilensperren gelten bis zum Ende der Transaktion des Aufrufers: ein paralleler
          -- put desselben Keys wartet, ein noch offener (gesperrter) wird übersprungen.
          RETURN QUERY
            SELECT o.namespace, o.key, o.version, o.generation
            FROM public.storage_object o
            WHERE o.purge_pending AND o.status = 'deleted'
            ORDER BY o.updated_at
            LIMIT GREATEST(LEAST(p_limit, 1000), 1)
            FOR UPDATE SKIP LOCKED;
        END
        $$
    """)
    op.execute(r"""
        CREATE FUNCTION public.storage_purge_done(p_namespace text, p_key text, p_version bigint)
        RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          UPDATE public.storage_object o SET purge_pending = false
          WHERE o.namespace = p_namespace AND o.key = p_key AND o.version = p_version AND o.purge_pending;
          RETURN FOUND;
        END
        $$
    """)
    for signature in ("storage_purge_claim(integer)", "storage_purge_done(text, text, bigint)"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO hocx_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.storage_purge_done(text, text, bigint)")
    op.execute("DROP FUNCTION IF EXISTS public.storage_purge_claim(integer)")
    op.execute(_register_write_sql(with_purge=False))
    op.drop_index("idx_storage_object_purge_pending", table_name="storage_object")
    op.drop_column("storage_object", "purge_pending")
