"""Doppelte Bussen zusammenführen und per Unique-Index ausschliessen

Audit MAIN-BE-016 (Entscheidung 2026-10-16: Duplikate automatisch zusammenführen). Pro
Protokoll, Teilnehmer und Bussentyp darf es nur eine Busse geben; create_fine prüft das schon
(find_existing_fine), die Datenbank bisher nicht. Teilnehmer ohne Verknüpfung (Freitext oder
gelöschter Teilnehmer, participant_id NULL) werden wie in find_existing_fine über den
Namens-Snapshot unterschieden.

Zusammenführen: Pro Gruppe bleibt die Busse mit dem «stärksten» Status (kassiert vor offen
vor gelöscht), bei Gleichstand die älteste. Die übrigen Zeilen werden vor dem Löschen
vollständig nach `attendance_fine_merged_duplicate` kopiert (mit `merged_into_id`), damit
nichts verloren geht und sich jede Zusammenführung nachvollziehen lässt. Buchungen kassierter
Duplikate bleiben unverändert stehen (Finanz-Historie, siehe MAIN-BE-008).

Revision ID: 0116_attendance_fine_unique
Revises: 0115_attendance_fine_soft_delete
Create Date: 2026-10-16
"""
from alembic import op

revision = "0116_attendance_fine_unique"
down_revision = "0115_attendance_fine_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE attendance_fine_merged_duplicate AS
        SELECT af.*, NULL::bigint AS merged_into_id, now() AS merged_at
        FROM attendance_fine af
        WITH NO DATA
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                FIRST_VALUE(id) OVER w AS keeper_id,
                ROW_NUMBER() OVER w AS rank
            FROM attendance_fine
            WINDOW w AS (
                PARTITION BY protocol_id, fine_type,
                    COALESCE('id:' || participant_id::text, 'name:' || participant_name_snapshot)
                ORDER BY CASE status WHEN 'collected' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                         created_at, id
            )
        )
        INSERT INTO attendance_fine_merged_duplicate
        SELECT af.*, ranked.keeper_id, now()
        FROM attendance_fine af
        JOIN ranked ON ranked.id = af.id
        WHERE ranked.rank > 1
        """
    )
    op.execute("DELETE FROM attendance_fine WHERE id IN (SELECT id FROM attendance_fine_merged_duplicate)")
    op.execute(
        "CREATE UNIQUE INDEX uq_attendance_fine_participant ON attendance_fine (protocol_id, participant_id, fine_type) "
        "WHERE participant_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_attendance_fine_name ON attendance_fine (protocol_id, participant_name_snapshot, fine_type) "
        "WHERE participant_id IS NULL"
    )
    # Personenbezogene Kopien verschwinden mit dem Protokoll bzw. Mandanten.
    op.execute(
        "ALTER TABLE attendance_fine_merged_duplicate ADD CONSTRAINT fk_attendance_fine_merged_duplicate_protocol "
        "FOREIGN KEY (protocol_id) REFERENCES protocol(id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX idx_attendance_fine_merged_duplicate_protocol ON attendance_fine_merged_duplicate (protocol_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_attendance_fine_name")
    op.execute("DROP INDEX IF EXISTS uq_attendance_fine_participant")
    # Die zusammengeführten Zeilen werden nicht zurückgespielt: der Unique-Index fehlt danach,
    # die Daten bleiben in attendance_fine_merged_duplicate zur Prüfung erhalten.
