"""Speicher für wartende Fotoimporte reservieren; eng begrenzte Abgabebox-Abfragen."""
from alembic import op
import sqlalchemy as sa

revision = "0092_upload_capacity"
down_revision = "0091_custom_domain_description"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gallery_upload_job", sa.Column("reserved_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("""
        CREATE FUNCTION public.upload_storage_usage(p_tenant_id bigint) RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
          SELECT COALESCE((SELECT SUM(file_size_bytes) FROM public.stored_file WHERE tenant_id=p_tenant_id),0)::bigint
               + COALESCE((SELECT SUM(reserved_bytes) FROM public.gallery_upload_job
                   WHERE tenant_id=p_tenant_id AND status IN ('queued','running')),0)::bigint
        $$
    """)
    op.execute("""
        CREATE FUNCTION public.upload_path_referenced(p_path text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
          SELECT EXISTS(SELECT 1 FROM public.stored_file WHERE storage_path=p_path)
        $$
    """)
    for signature in ("upload_storage_usage(bigint)", "upload_path_referenced(text)"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO hocx_abgabebox, hocx_app")


def downgrade():
    op.execute("DROP FUNCTION public.upload_path_referenced(text)")
    op.execute("DROP FUNCTION public.upload_storage_usage(bigint)")
    op.drop_column("gallery_upload_job", "reserved_bytes")
