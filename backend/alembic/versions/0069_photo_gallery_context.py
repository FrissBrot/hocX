"""Photo-culling/gallery-redesign support: a real "has this file been through Phase 3"
marker on stored_file, and the Termin a gallery upload was assigned to (previously
collected by the upload picker but never persisted).

face_analyzed_at fixes a latent bug rather than just adding a feature: photo-analysis-
worker's score_face_quality() legitimately returns None when no face is detected (see
worker.py/face_quality.py), and write_face_quality_score() writes that None back as-is -
so `face_quality_score IS NOT NULL` can never mean "analyzed", only "analyzed and a face
was found". FileService.create_pending_analysis_jobs() has been using exactly that wrong
predicate, so every faceless photo (group shots from far away, landscapes, ...) gets
re-queued and re-scored by the worker every single off-peak run, forever. Introducing an
explicit "processed" timestamp - set by the worker regardless of the score's value -
is the only way to express "done, no face found" separately from "not done yet".

gallery_image.event_id lets a direct gallery upload remember the Termin the uploader
picked (GalleryUploadModal already offers this choice to route the photos into that
Termin's auto-album - see photo_album_service.get_or_create_cycle_album's sibling for
events - but the id was previously discarded after use). It backs the new date-grouped
Fotos view's "which Termin/Zyklus does this date belong to" header context.
"""

revision = "0069_photo_gallery_context"
down_revision = "0068_photo_album_auto"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op

PHOTO_WORKER_ROLE = "hocx_photo_worker"


def upgrade():
    op.add_column("stored_file", sa.Column("face_analyzed_at", sa.DateTime(timezone=True), nullable=True))
    # Existing rows that already carry a Phase-3 score (face found or not - either way the
    # worker had already run) count as analyzed from the moment this migration runs.
    op.execute("UPDATE stored_file SET face_analyzed_at = NOW() WHERE face_quality_score IS NOT NULL")
    # Backs the auto-queue's "find images still needing Phase 3" scan (mirrors the shape of
    # create_pending_analysis_jobs' query) now that it filters on this column instead.
    op.create_index(
        "idx_stored_file_face_pending",
        "stored_file",
        ["tenant_id"],
        postgresql_where=sa.text("face_analyzed_at IS NULL"),
    )
    # 0067 granted hocx_photo_worker column-level UPDATE on face_quality_score only - without
    # this grant, the worker's UPDATE (now also setting face_analyzed_at) starts failing
    # with a permission error the moment it runs.
    op.execute(f"GRANT UPDATE(face_analyzed_at) ON TABLE public.stored_file TO {PHOTO_WORKER_ROLE}")

    op.add_column("gallery_image", sa.Column("event_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_gallery_image_event", "gallery_image", "event", ["event_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("idx_gallery_image_event", "gallery_image", ["event_id"])


def downgrade():
    op.drop_index("idx_gallery_image_event", table_name="gallery_image")
    op.drop_constraint("fk_gallery_image_event", "gallery_image", type_="foreignkey")
    op.drop_column("gallery_image", "event_id")

    op.execute(f"REVOKE UPDATE(face_analyzed_at) ON TABLE public.stored_file FROM {PHOTO_WORKER_ROLE}")
    op.drop_index("idx_stored_file_face_pending", table_name="stored_file")
    op.drop_column("stored_file", "face_analyzed_at")
