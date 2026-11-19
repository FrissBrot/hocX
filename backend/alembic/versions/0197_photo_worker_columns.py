"""Foto-Worker: UPDATE auf photo_analysis_job nur noch für die Spalten, die er setzt.

0067 gab hocx_photo_worker ``SELECT, UPDATE`` auf die ganze Tabelle photo_analysis_job. Der Worker
(photo-analysis-worker/app/db.py) setzt aber nur ``status``, ``started_at``, ``finished_at`` und
``error``. Mit dem Tabellenrecht hätte ein übernommener Worker auch ``tenant_id``, ``requested_by``
oder ``stored_file_ids`` eines Auftrags umschreiben können (Nachtlauf 2026-11-19, SECURITY-RULES
2.4: Laufzeitrollen nur mit den nötigen Rechten).

``SELECT ... FOR UPDATE SKIP LOCKED`` (Auftrag übernehmen) braucht nur UPDATE auf irgendeiner
Spalte und funktioniert mit den Spaltenrechten weiter. SELECT bleibt unverändert; stored_file hatte
schon nur Spaltenrechte (face_quality_score, face_analyzed_at).

Downgrade stellt das Tabellenrecht von 0067 wieder her.

Revision ID: 0197_photo_worker_columns
Revises: 0196_context_visibility
Create Date: 2026-11-19
"""

from alembic import op

revision = "0197_photo_worker_columns"
down_revision = "0196_context_visibility"
branch_labels = None
depends_on = None

ROLE = "hocx_photo_worker"
JOB_COLUMNS = "status, started_at, finished_at, error"


def _role_exists() -> bool:
    return bool(op.get_bind().exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = 'hocx_photo_worker'").scalar())


def upgrade():
    if not _role_exists():
        return
    # Das Tabellenrecht umfasst alle Spalten; erst entziehen, dann gezielt neu vergeben.
    op.execute(f"REVOKE UPDATE ON TABLE public.photo_analysis_job FROM {ROLE}")  # sql-ok: feste Bezeichner
    op.execute(f"GRANT UPDATE ({JOB_COLUMNS}) ON TABLE public.photo_analysis_job TO {ROLE}")  # sql-ok: feste Bezeichner


def downgrade():
    if not _role_exists():
        return
    op.execute(f"REVOKE UPDATE ({JOB_COLUMNS}) ON TABLE public.photo_analysis_job FROM {ROLE}")  # sql-ok: feste Bezeichner
    op.execute(f"GRANT UPDATE ON TABLE public.photo_analysis_job TO {ROLE}")  # sql-ok: feste Bezeichner
