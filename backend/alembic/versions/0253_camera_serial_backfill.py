"""Kamera-Kürzel für bestehende Fotos nachtragen (Upload-Verlauf 1.6, User-Entscheid E-13).

``camera_serial_backfill`` hält je Mandant den Fortschritt des Hintergrundjobs
``camera_serial_backfill`` (services/camera_serial_backfill.py): bis zu welcher Datei-ID gelesen
wurde (``last_file_id``), bis wohin der Lauf überhaupt geht (``upper_file_id`` = grösste Bild-ID
beim Start; neuere Fotos bekommen das Kürzel schon beim Upload) und Zähler für die Admin-Ansicht.
Der Job liest je Charge die Seriennummer aus der EXIF der Originaldatei und speichert nur das
Kürzel (HMAC je Mandant, services/camera_serial.py) in ``stored_file.camera_serial_key`` - die
Seriennummer selbst wird nie gespeichert. Wiederaufnehmbar: jede Charge committet ihren Stand.

Mandantentrennung: ``tenant_id`` NOT NULL (zugleich Primärschlüssel) und RLS ``tenant_isolation``.

Revision ID: 0253_camera_serial_backfill
Revises: 0252_upload_history_abgabebox
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op

revision = "0253_camera_serial_backfill"
down_revision = "0252_upload_history_abgabebox"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE camera_serial_backfill (
            tenant_id bigint PRIMARY KEY REFERENCES tenant(id) ON DELETE CASCADE,
            upper_file_id bigint NOT NULL DEFAULT 0,
            last_file_id bigint NOT NULL DEFAULT 0,
            checked integer NOT NULL DEFAULT 0,
            keyed integer NOT NULL DEFAULT 0,
            no_serial integer NOT NULL DEFAULT 0,
            missing integer NOT NULL DEFAULT 0,
            failed integer NOT NULL DEFAULT 0,
            started_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT ck_camera_serial_backfill_cursor CHECK (last_file_id >= 0 AND upper_file_id >= 0)
        )
        """
    )
    op.execute("CREATE INDEX idx_camera_serial_backfill_open ON camera_serial_backfill (updated_at NULLS FIRST) WHERE finished_at IS NULL")
    op.execute(f"CREATE POLICY tenant_isolation ON public.camera_serial_backfill FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy
    op.execute("ALTER TABLE public.camera_serial_backfill ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS camera_serial_backfill")
