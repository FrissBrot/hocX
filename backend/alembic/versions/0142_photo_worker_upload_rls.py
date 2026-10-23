"""Foto-Worker liest submission_upload_file wieder (Korrektur zu 0134_child_table_rls)

0134 hat die Eltern-Policy von submission_upload_file auch für hocx_photo_worker angelegt. Die
Bedingung prüft per EXISTS die Elterntabellen submission_upload und submission_assignment, und
PostgreSQL verlangt dafür das Leserecht des abfragenden Benutzers - das der Foto-Worker bewusst
nicht hat. Seine Abfrage, ob eine Datei aus der Abgabebox stammt (photo-analysis-worker
app/db.py::fetch_files), scheiterte deshalb mit "permission denied for table
submission_assignment", und die Gesichtsanalyse fiel aus.

Der Foto-Worker setzt keinen Mandanten (0132) und darf nur die Spalte stored_file_id lesen
(0113). Die Eltern-Policy gilt daher nur noch für hocx_app; für den Foto-Worker gibt es eine
eigene, reine Lese-Policy.

Revision ID: 0142_photo_worker_upload_rls
Revises: 0141_drop_fine_duplicates
Create Date: 2026-10-21
"""

from alembic import op

revision = "0142_photo_worker_upload_rls"
down_revision = "0141_drop_fine_duplicates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER POLICY tenant_isolation ON public.submission_upload_file TO hocx_app")
    op.execute(
        "CREATE POLICY photo_worker_read ON public.submission_upload_file FOR SELECT TO hocx_photo_worker USING (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS photo_worker_read ON public.submission_upload_file")
    op.execute("ALTER POLICY tenant_isolation ON public.submission_upload_file TO hocx_app, hocx_photo_worker")
