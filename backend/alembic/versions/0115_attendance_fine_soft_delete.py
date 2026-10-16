"""Bussen mit Begründung löschen (Soft-Delete) und redundante CHECKs aus 0114 entfernen

Audit MAIN-BE-002 (Entscheidung 2026-10-16): Eine offene Busse, deren Ursprungsprotokoll schon
abgeschlossen ist, wird nicht mehr hart gelöscht, sondern mit Begründung als `deleted`
markiert und im Protokoll aufgeführt, in dem gelöscht wurde (`closed_in_protocol_id`, wie
beim Einkassieren). Die Spalte `delete_comment` und der Status `deleted` stammen aus dem
früheren Soft-Delete (Migration 0012/0013 vor dem Squash) und sind in der Baseline noch
vorhanden; neu sind Zeitpunkt und Person.

0114 hatte `ck_attendance_fine_status`/`ck_attendance_fine_type` ergänzt. Die Baseline
enthält aber bereits validierte CHECKs (`attendance_fine_status_check` inkl. `deleted`,
`attendance_fine_fine_type_check`). Die zusätzlichen Constraints sind redundant, und der
Status-CHECK schliesst `deleted` aus - beide werden entfernt.

Revision ID: 0115_attendance_fine_soft_delete
Revises: 0114_attendance_fine_checks
Create Date: 2026-10-16
"""
from alembic import op

revision = "0115_attendance_fine_soft_delete"
down_revision = "0114_attendance_fine_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS ck_attendance_fine_status")
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS ck_attendance_fine_type")
    # Baseline-CHECKs sicherstellen (Datenbanken, die nicht aus der Baseline stammen).
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS attendance_fine_status_check")
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT attendance_fine_status_check "
        "CHECK (status IN ('pending', 'collected', 'deleted'))"
    )
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS attendance_fine_fine_type_check")
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT attendance_fine_fine_type_check "
        "CHECK (fine_type IN ('late', 'absent'))"
    )
    op.execute("ALTER TABLE attendance_fine ADD COLUMN IF NOT EXISTS delete_comment text")
    op.execute("ALTER TABLE attendance_fine ADD COLUMN deleted_at timestamp with time zone")
    op.execute(
        "ALTER TABLE attendance_fine ADD COLUMN deleted_by_user_id bigint "
        "REFERENCES app_user(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX idx_attendance_fine_deleted_by ON attendance_fine (deleted_by_user_id)")
    # Ein gelöschter Eintrag braucht Begründung und Protokoll, in dem er aufgeführt wird.
    # NOT VALID: Altbestände aus dem früheren Soft-Delete (Kommentar war damals optional)
    # bleiben unangetastet.
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT ck_attendance_fine_deleted_reason "
        "CHECK (status <> 'deleted' OR (delete_comment IS NOT NULL AND btrim(delete_comment) <> '')) NOT VALID"
    )


def downgrade() -> None:
    # Gelöschte Bussen wären mit dem engeren Schema nicht darstellbar und würden ohne Spur
    # wieder offen - daher bewusst abbrechen statt Daten umzudeuten.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM attendance_fine WHERE status = 'deleted' AND deleted_at IS NOT NULL) "
        "THEN RAISE EXCEPTION 'Downgrade nicht möglich: es gibt mit Begründung gelöschte Bussen'; END IF; END $$"
    )
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS ck_attendance_fine_deleted_reason")
    op.execute("DROP INDEX IF EXISTS idx_attendance_fine_deleted_by")
    op.execute("ALTER TABLE attendance_fine DROP COLUMN IF EXISTS deleted_by_user_id")
    op.execute("ALTER TABLE attendance_fine DROP COLUMN IF EXISTS deleted_at")
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT ck_attendance_fine_status "
        "CHECK (status IN ('pending', 'collected')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT ck_attendance_fine_type "
        "CHECK (fine_type IN ('late', 'absent')) NOT VALID"
    )
