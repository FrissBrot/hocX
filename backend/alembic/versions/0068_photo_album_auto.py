"""Auto-generated photo albums (per Zyklus/Periode, per Abgabe, per Abgabe-Element) and a
best-of ("Stern") selection within every album, manual or auto.

hocx_app already has table-wide DML on photo_album/photo_album_item via the ALTER DEFAULT
PRIVILEGES grant in baseline_schema.sql (see 0066's note) - no new GRANT needed. The
restricted hocx_abgabebox role was never granted anything on these two tables, so
submission-upload files are folded into their albums by a periodic sync in the trusted
backend (see app/services/photo_album_service.py / main.py's photo_album_sync_loop), never
inline in the public abgabebox upload request.
"""

revision = "0068_photo_album_auto"
down_revision = "0067_photo_analysis_job"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("photo_album", sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'manual'")))
    op.add_column("photo_album", sa.Column("cycle_config_id", sa.BigInteger(), nullable=True))
    op.add_column("photo_album", sa.Column("cycle_year", sa.SmallInteger(), nullable=True))
    op.add_column("photo_album", sa.Column("submission_assignment_id", sa.BigInteger(), nullable=True))
    op.add_column("photo_album", sa.Column("submission_element_ref", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_photo_album_cycle_config", "photo_album", "cycle_config", ["cycle_config_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_photo_album_submission_assignment",
        "photo_album",
        "submission_assignment",
        ["submission_assignment_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_check_constraint(
        "ck_photo_album_kind", "photo_album", "kind IN ('manual', 'cycle', 'submission', 'submission_element')"
    )
    # Ties `kind` to which of the auto-album reference columns must be set - mirrors
    # submission_assignment's own ck_submission_assignment_source_fields pattern.
    op.create_check_constraint(
        "ck_photo_album_kind_fields",
        "photo_album",
        "(kind = 'manual' AND cycle_config_id IS NULL AND cycle_year IS NULL "
        " AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR "
        "(kind = 'cycle' AND cycle_config_id IS NOT NULL AND cycle_year IS NOT NULL "
        " AND submission_assignment_id IS NULL AND submission_element_ref IS NULL) OR "
        "(kind = 'submission' AND cycle_config_id IS NULL AND cycle_year IS NULL "
        " AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NULL) OR "
        "(kind = 'submission_element' AND cycle_config_id IS NULL AND cycle_year IS NULL "
        " AND submission_assignment_id IS NOT NULL AND submission_element_ref IS NOT NULL)",
    )

    # Partial unique indexes so get_or_create_*_album() can rely on "at most one row for
    # this (tenant, target)" instead of racing two concurrent syncs into duplicate albums.
    op.create_index(
        "uq_photo_album_cycle",
        "photo_album",
        ["tenant_id", "cycle_config_id", "cycle_year"],
        unique=True,
        postgresql_where=sa.text("kind = 'cycle'"),
    )
    op.create_index(
        "uq_photo_album_submission",
        "photo_album",
        ["tenant_id", "submission_assignment_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'submission'"),
    )
    op.create_index(
        "uq_photo_album_submission_element",
        "photo_album",
        ["tenant_id", "submission_assignment_id", "submission_element_ref"],
        unique=True,
        postgresql_where=sa.text("kind = 'submission_element'"),
    )

    # is_best is the current, resolved state (auto-computed unless best_override pins it);
    # best_override records a manual "immer dabei"/"nie dabei" pick so a later automatic
    # recompute (new upload, rescoring) never silently reverts a user's explicit choice.
    op.add_column("photo_album_item", sa.Column("is_best", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column("photo_album_item", sa.Column("best_override", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_photo_album_item_best_override", "photo_album_item", "best_override IN ('include', 'exclude') OR best_override IS NULL"
    )


def downgrade():
    op.drop_constraint("ck_photo_album_item_best_override", "photo_album_item", type_="check")
    op.drop_column("photo_album_item", "best_override")
    op.drop_column("photo_album_item", "is_best")

    op.drop_index("uq_photo_album_submission_element", table_name="photo_album")
    op.drop_index("uq_photo_album_submission", table_name="photo_album")
    op.drop_index("uq_photo_album_cycle", table_name="photo_album")

    op.drop_constraint("ck_photo_album_kind_fields", "photo_album", type_="check")
    op.drop_constraint("ck_photo_album_kind", "photo_album", type_="check")

    op.drop_constraint("fk_photo_album_submission_assignment", "photo_album", type_="foreignkey")
    op.drop_constraint("fk_photo_album_cycle_config", "photo_album", type_="foreignkey")

    op.drop_column("photo_album", "submission_element_ref")
    op.drop_column("photo_album", "submission_assignment_id")
    op.drop_column("photo_album", "cycle_year")
    op.drop_column("photo_album", "cycle_config_id")
    op.drop_column("photo_album", "kind")
