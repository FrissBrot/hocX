"""Abgabebox: Lesrecht auf stored_file.scan_status (Duplikatprüfung).

Die Abgabebox quittiert eine Datei, deren SHA-256 im Element schon vorkommt, still als Erfolg
und speichert sie nicht noch einmal. Dabei zählten auch Dateien, deren Virenprüfung im
Nachscan gescheitert ist (``error``, in der Verwaltung dauerhaft gesperrt) oder die als
Schadware eingestuft wurden (``infected``). Wer auf Bitte des Vereins dieselbe Datei erneut
abgab, bekam «erfolgreich», aber es kam nichts an. Die Prüfung filtert diese Zeilen jetzt aus
und braucht dafür die Spalte ``scan_status``.

Nur dieses eine Spaltenrecht dazu; Zeilen sieht die Rolle weiterhin nur über die Policies aus
0133/0183/0199 (eigener Link, kein Papierkorb).

Revision ID: 0201_abgabebox_scan_status
Revises: 0200_photo_capture_override
Create Date: 2026-11-20
"""

from alembic import op

revision = "0201_abgabebox_scan_status"
down_revision = "0200_photo_capture_override"
branch_labels = None
depends_on = None

ROLE = "hocx_abgabebox"


def _role_exists() -> bool:
    return op.get_bind().exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = 'hocx_abgabebox'").first() is not None


def upgrade() -> None:
    if _role_exists():
        op.execute(f"GRANT SELECT (scan_status) ON public.stored_file TO {ROLE}")  # sql-ok: feste Bezeichner


def downgrade() -> None:
    if _role_exists():
        op.execute(f"REVOKE SELECT (scan_status) ON public.stored_file FROM {ROLE}")  # sql-ok: feste Bezeichner
