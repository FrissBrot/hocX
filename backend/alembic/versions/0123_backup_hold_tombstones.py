"""Backup-Hold sichert auch Tombstones vor dem physischen Löschen (Release 1.2.0)

Zwei Zweige trafen sich erst im Release: feature/borg-backup-restore (0115_backup_system) sichert
per Copy-on-Write jedes Objekt, das während eines Backup-Holds überschrieben oder gelöscht wird -
storage_backup_hold() liefert dafür nur Objekte mit status = 'active'. Seit
0118_storage_purge_after_commit (S3-008) markiert delete das Objekt aber nur als Tombstone
(status 'deleted', purge_pending); physisch löscht erst der Job storage_purge. Ohne diese
Revision fände der Purge-Job während eines Holds keinen Registerstand mehr und zerstörte Inhalte,
die das laufende Backup noch lesen will.

Neu liefert storage_backup_hold() auch noch nicht gelöschte Tombstones (purge_pending). Der
Purge-Job ruft den Hold vor backend.delete auf (objstore_client.purge_deleted).

Revision ID: 0123_backup_hold_tombstones
Revises: 0122_release_merge_backup
Create Date: 2026-10-16
"""

from alembic import op

revision = "0123_backup_hold_tombstones"
down_revision = "0122_release_merge_backup"
branch_labels = None
depends_on = None

ROLES = "hocx_app, hocx_abgabebox"


def _function(status_condition: str) -> str:
    return rf"""
        CREATE OR REPLACE FUNCTION public.storage_backup_hold(p_namespace text, p_key text, p_generation bigint)
        RETURNS TABLE (hold_id uuid, sha256 text, size_bytes bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
          SELECT s.backup_hold_id, o.sha256, o.size_bytes
          FROM public.storage_state s
          JOIN public.storage_object o ON o.namespace = p_namespace AND o.key = p_key
          WHERE s.id = 1 AND s.backup_hold_id IS NOT NULL AND s.backup_hold_generation = p_generation
            AND {status_condition} AND o.sha256 IS NOT NULL
        $$
    """


def upgrade() -> None:
    op.execute(_function("(o.status = 'active' OR (o.status = 'deleted' AND o.purge_pending))"))
    op.execute("REVOKE ALL ON FUNCTION public.storage_backup_hold(text, text, bigint) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.storage_backup_hold(text, text, bigint) TO {ROLES}")


def downgrade() -> None:
    op.execute(_function("o.status = 'active'"))
    op.execute("REVOKE ALL ON FUNCTION public.storage_backup_hold(text, text, bigint) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.storage_backup_hold(text, text, bigint) TO {ROLES}")
