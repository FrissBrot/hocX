"""Wanderplaner Phase 5 (Rekognoszierung): Checkliste + Freigabe-Audit (Auftrag Abschnitt 17).

`reconnoitered_at`/`reconnoitered_by_user_id` und `approved_at`/`approved_by_user_id` folgen
demselben Muster wie `attendance_fine.collected_by_user_id` (Wer/Wann-Audit einer bewussten
Nutzeraktion, `ON DELETE SET NULL` - eine geloeschte Person darf die Rekognoszierung/Freigabe
selbst nicht mit sich reissen).

Revision ID: 0101_wanderplaner_reconnaissance
Revises: 0100_wanderplaner_auto_analysis
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0101_wanderplaner_reconnaissance"
down_revision = "0100_wanderplaner_auto_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hiking_tour", sa.Column("reconnaissance_checklist_json", postgresql.JSONB(), nullable=True))
    op.add_column("hiking_tour", sa.Column("reconnaissance_remarks", sa.Text(), nullable=True))
    op.add_column("hiking_tour", sa.Column("reconnoitered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hiking_tour", sa.Column("reconnoitered_by_user_id", sa.BigInteger(), nullable=True))
    op.add_column("hiking_tour", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hiking_tour", sa.Column("approved_by_user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_hiking_tour_reconnoitered_by", "hiking_tour", "app_user", ["reconnoitered_by_user_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key("fk_hiking_tour_approved_by", "hiking_tour", "app_user", ["approved_by_user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_hiking_tour_approved_by", "hiking_tour", type_="foreignkey")
    op.drop_constraint("fk_hiking_tour_reconnoitered_by", "hiking_tour", type_="foreignkey")
    op.drop_column("hiking_tour", "approved_by_user_id")
    op.drop_column("hiking_tour", "approved_at")
    op.drop_column("hiking_tour", "reconnoitered_by_user_id")
    op.drop_column("hiking_tour", "reconnoitered_at")
    op.drop_column("hiking_tour", "reconnaissance_remarks")
    op.drop_column("hiking_tour", "reconnaissance_checklist_json")
