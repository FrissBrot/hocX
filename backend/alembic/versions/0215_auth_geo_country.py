"""Länder-Geolocation als Risikosignal (Auth-Audit 7.2 «Neues Land»): nur Ländercode, nie die IP.

- ``auth_event.src_country``: Land der Quelle (DB-IP «IP to Country Lite», lokal) - Grundlage für
  das Signal ``new_country`` (90 Tage erfolgreicher Anmeldungen). Gelöscht mit dem Ereignis nach
  ``AUTH_EVENT_RETENTION_DAYS``.
- ``auth_session.country`` und ``auth_known_device.last_country``: Anzeige unter «Angemeldete
  Geräte»; gelöscht mit der Session bzw. dem Gerät (Job ``auth_security_maintenance``).

Bestehende Tabellen mit RLS; nur neue, nullable Spalten mit CHECK auf zwei Grossbuchstaben.
"""
from __future__ import annotations

from alembic import op

revision = "0215_auth_geo_country"
down_revision = "0208_platform_metrics"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("auth_event", "src_country"),
    ("auth_session", "country"),
    ("auth_known_device", "last_country"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN {column} text")  # sql-ok: feste Bezeichner aus dem Code
        # NOT VALID: die neue Spalte ist in allen Bestandszeilen NULL, ein Prüf-Scan über die ganze
        # (grosse) auth_event unter dem Tabellenlock wäre unnötig; neue Zeilen prüft der CHECK trotzdem.
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_{column} CHECK ({column} IS NULL OR {column} ~ '^[A-Z]{{2}}$') NOT VALID"  # sql-ok: feste Bezeichner
        )


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_{column}")  # sql-ok: feste Bezeichner
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")  # sql-ok: feste Bezeichner
