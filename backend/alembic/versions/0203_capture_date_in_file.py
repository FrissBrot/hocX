"""Fotos: korrigiertes Aufnahmedatum auch in die Bilddatei schreiben (Original bleibt in hocX).

Bisher stand die Korrektur (0200) nur in der Datenbank, Downloads bekamen sie über eine
Exportkopie. Jetzt schreibt der Job capture_date_file_sync sie in die Datei selbst
(services/exif_date_write.py, services/capture_date_file_sync.py). Das ursprüngliche Datum
bleibt in hocX: exif_taken_at unverändert, die ursprünglichen Rohbytes der Datei-Datumsfelder in
capture_exif_original - damit «Original wiederherstellen» die Datei wieder auf den
Originalzustand zurückschreibt.

stored_file:
- capture_exif_original JSONB: Rückweg für die Datei (überschriebene Rohwerte, eingefügtes oder
  ersetztes EXIF-Segment). Nur beim ERSTEN Schreiben gesetzt, nach erfolgreicher
  Wiederherstellung wieder NULL. Gesetzt heisst auch: die Datumsfelder der Datei stammen von
  hocX und dürfen nie als EXIF-Original eingelesen werden (image_metadata_service).
- capture_file_state: Abgleich der Datei mit der DB - pending (Job steht aus), written (Datei
  enthält die aktuelle Korrektur), unsupported (Format kann es nicht, Datei unverändert), failed
  (Fehlerprotokoll); NULL = nichts zu tun. Die Anzeige in hocX liest nie diesen Status, sondern
  wie bisher capture_corrected_at/exif_taken_at.

Rechte: hocx_abgabebox darf zusätzlich source_checksum_sha256 lesen. Schreibt hocX das Datum in
eine Abgabebox-Datei, ändert sich ihr checksum_sha256; die Duplikatprüfung der Abgabebox
vergleicht deshalb auch mit dem ursprünglichen Hash (abgabebox-backend repository.py). Zeilen sieht
die Rolle weiterhin nur über die Policies aus 0133/0183/0199.

Revision ID: 0203_capture_date_in_file
Revises: 0201_abgabebox_scan_status
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0203_capture_date_in_file"
# Beim Zusammenführen auf 0202_submission_todo_tags umbiegen (0202 liegt auf einem anderen Zweig).
down_revision = "0201_abgabebox_scan_status"
branch_labels = None
depends_on = None

ROLE = "hocx_abgabebox"


def _role_exists() -> bool:
    return op.get_bind().exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = 'hocx_abgabebox'").first() is not None


def upgrade() -> None:
    op.add_column("stored_file", sa.Column("capture_exif_original", postgresql.JSONB(), nullable=True))
    op.add_column("stored_file", sa.Column("capture_file_state", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_stored_file_capture_file_state",
        "stored_file",
        "capture_file_state IS NULL OR capture_file_state IN ('pending', 'written', 'unsupported', 'failed')",
    )
    # Der Job sucht nur offene Zeilen - klein, weil fast alle NULL sind.
    op.create_index(
        "idx_stored_file_capture_file_pending",
        "stored_file",
        ["id"],
        postgresql_where=sa.text("capture_file_state = 'pending'"),
    )
    # Bestand: vorhandene Korrekturen auch in die Dateien schreiben.
    op.execute("UPDATE stored_file SET capture_file_state = 'pending' WHERE capture_corrected_at IS NOT NULL")
    if _role_exists():
        op.execute(f"GRANT SELECT (source_checksum_sha256) ON public.stored_file TO {ROLE}")  # sql-ok: feste Bezeichner


def downgrade() -> None:
    # Achtung: Dateien, in die schon geschrieben wurde, behalten das korrigierte Datum; mit der
    # Spalte capture_exif_original geht der Rückweg verloren. Vorher alle Korrekturen
    # zurücksetzen und den Job laufen lassen, wenn das Original in der Datei gebraucht wird.
    if _role_exists():
        op.execute(f"REVOKE SELECT (source_checksum_sha256) ON public.stored_file FROM {ROLE}")  # sql-ok: feste Bezeichner
    op.drop_index("idx_stored_file_capture_file_pending", table_name="stored_file")
    op.drop_constraint("ck_stored_file_capture_file_state", "stored_file", type_="check")
    op.drop_column("stored_file", "capture_file_state")
    op.drop_column("stored_file", "capture_exif_original")
