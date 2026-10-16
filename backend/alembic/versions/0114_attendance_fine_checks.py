"""CHECK-Constraints für attendance_fine.status und attendance_fine.fine_type

Audit MAIN-BE-016: Status und Typ einer Busse waren nur durch die Anwendungslogik
abgesichert; Import, Klon und künftige Pfade konnten beliebige Werte schreiben.

Die Constraints werden NOT VALID angelegt: Postgres prüft sie für jede neue bzw. geänderte
Zeile, bestehende Zeilen bleiben unangetastet (kein Abbruch der Migration wegen Altdaten,
keine Datenänderung). Ein späteres VALIDATE CONSTRAINT kann nach einer Prüfung der Altdaten
nachgezogen werden. Ein Unique-Index gegen doppelte Bussen fehlt bewusst noch - dafür müssten
bestehende Duplikate zuerst fachlich bereinigt werden (siehe Reparaturbericht).

Revision ID: 0114_attendance_fine_checks
Revises: 0113_element_config_schema
Create Date: 2026-10-16
"""
from alembic import op

revision = "0114_attendance_fine_checks"
down_revision = "0113_element_config_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT ck_attendance_fine_status "
        "CHECK (status IN ('pending', 'collected')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE attendance_fine ADD CONSTRAINT ck_attendance_fine_type "
        "CHECK (fine_type IN ('late', 'absent')) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS ck_attendance_fine_type")
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS ck_attendance_fine_status")
