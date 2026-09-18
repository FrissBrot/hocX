"""Gallery upload ingestion becomes an async job (see backend/app/main.py's
gallery_upload_ingest_loop) instead of running inline in the upload request - lets ZIP
uploads scale to several GB without buffering the whole batch in the request handler's
memory. Mirrors photo_analysis_job (migration 0067), minus its separate worker role: this
job stays inside the backend's own hocx_app role and reuses its existing ClamAV
connectivity, so no new restricted role is needed."""

revision = "0072_gallery_upload_job"
down_revision = "0071_upload_pipeline_indexes"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def upgrade():
    op.create_table(
        "gallery_upload_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        # Storage-relative paths of the raw upload(s) staged by the request handler (one
        # ZIP, or several individually-selected images) - the loop reads/extracts these
        # itself instead of the request handler passing decoded bytes.
        sa.Column("staged_paths", postgresql.JSONB(), nullable=False),
        # Same order as staged_paths - filenames on disk are randomized, so this carries
        # each one's real client-supplied name (used for a non-ZIP entry's
        # StoredFile.original_name; a ZIP's own entries keep their in-archive names).
        sa.Column("original_filenames", postgresql.JSONB(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # At most one of these three targets is ever set - see upload_gallery_images' own
        # mutual-exclusion check, unchanged by this migration.
        sa.Column("upload_event_id", sa.BigInteger(), sa.ForeignKey("event.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "upload_assignment_id", sa.BigInteger(), sa.ForeignKey("submission_assignment.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("upload_element_ref", sa.Text(), nullable=True),
        # Resolved once at request time (see upload_gallery_images) - saves the ingest loop
        # from re-resolving it via submission_service on every job.
        sa.Column("upload_element_label", sa.Text(), nullable=True),
        sa.Column(
            "upload_cycle_config_id", sa.BigInteger(), sa.ForeignKey("cycle_config.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("requested_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        # Unknown until a ZIP is opened and its matching entries counted; known immediately
        # for a batch of individually-selected images.
        sa.Column("total_files", sa.Integer(), nullable=True),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # StoredFile.public_id values (as str) - see GalleryUploadJob's docstring for why
        # this differs from photo_analysis_job.stored_file_ids' internal bigints.
        sa.Column("imported_file_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Per-file problems (too large, unsupported format, infected, corrupt ZIP entry, ...)
        # - same partial-success shape GalleryUploadResult.errors already had.
        sa.Column("errors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Fatal/unexpected exception text, distinct from the per-file `errors` above.
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backs both the "next queued job" claim in the ingest loop and the tenant-wide
    # active-jobs listing the frontend's status bar polls.
    op.create_index("idx_gallery_upload_job_tenant_status", "gallery_upload_job", ["tenant_id", "status"])


def downgrade():
    op.drop_index("idx_gallery_upload_job_tenant_status", table_name="gallery_upload_job")
    op.drop_table("gallery_upload_job")
