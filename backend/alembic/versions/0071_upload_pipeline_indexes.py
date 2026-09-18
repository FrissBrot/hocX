"""Indexes supporting the unified upload pipeline's pending-scan lookups.

gallery_image had no index on stored_file_id (unlike protocol_image/word_import_document,
which already have idx_protocol_image_stored_file/idx_word_import_document_stored_file) -
StoredFileRepository.list_pending_internal_files (see app/services/upload_pipeline.py) joins
against all three, and the admin cross-tenant pipeline-status query (_files_overview_branches)
also depends on it. stored_file.scan_status itself has never been indexed - harmless at the
per-tenant scale the "Dateien" page queries at, but the new admin-panel aggregation scans
across all tenants, so a partial index on the non-'clean' rows (pending/infected are always a
small minority) keeps that query cheap without bloating the index with every clean row.

Revision ID: 0071_upload_pipeline_indexes
Revises: 0070_stored_file_dimensions
Create Date: 2026-09-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0071_upload_pipeline_indexes"
down_revision = "0070_stored_file_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_gallery_image_stored_file", "gallery_image", ["stored_file_id"])
    op.create_index(
        "idx_stored_file_scan_status_pending",
        "stored_file",
        ["scan_status"],
        postgresql_where=sa.text("scan_status <> 'clean'"),
    )


def downgrade() -> None:
    op.drop_index("idx_stored_file_scan_status_pending", table_name="stored_file")
    op.drop_index("idx_gallery_image_stored_file", table_name="gallery_image")
