"""Leak-Prüfung bestehender Passwörter beim Login (Release 1.5.2, User-Entscheid 2026-11-23).

Neue, nullable Spalten auf ``app_user`` und ``platform_admin`` (beide Tabellen behalten ihre
RLS-Policies; keine neue Tabelle):

- ``password_breached_at``: Zeitpunkt, an dem das aktuelle Passwort bei einer Anmeldung als aus
  einem Datenleck bekannt erkannt wurde (HIBP-Range-API mit k-Anonymität bzw. lokale Liste,
  ``app/core/password_leak.py``). Solange gesetzt: Anmeldung nur mit zweitem Faktor oder
  E-Mail-Code, Hinweis in der App, Pflicht zur Änderung. Wird beim Setzen eines neuen Passworts
  geleert (``app/auth_security/breach.py``).
- ``last_breach_check_at``: letzte erfolgreiche Prüfung (HIBP oder lokale Liste) - ungeprüfte
  Anmeldungen bei Ausfall (fail-open) setzen sie nicht.
- ``breach_check_due_at``: vom Nachtjob ``password_breach_recheck`` gesetzt, wenn die letzte
  Prüfung älter als ``PASSWORD_BREACH_RECHECK_DAYS`` ist. Die nächste Anmeldung prüft dann ohne
  Präfix-Cache.

Es wird nie ein Passwort-Hash, SHA-1 oder Präfix gespeichert - nur Zeitpunkte.
"""
from __future__ import annotations

from alembic import op

revision = "0219_password_breach_check"
down_revision = "0218_album_item_auto_source"
branch_labels = None
depends_on = None

_TABLES = ("app_user", "platform_admin")
_COLUMNS = ("password_breached_at", "last_breach_check_at", "breach_check_due_at")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} timestamptz")  # sql-ok: feste Bezeichner aus dem Code
    # Nachtjob: nur Konten mit Login und veralteter Prüfung (Teilindex, klein)
    op.execute(
        "CREATE INDEX idx_app_user_breach_check_pending ON app_user (last_breach_check_at) "
        "WHERE login_enabled AND breach_check_due_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_app_user_breach_check_pending")
    for table in reversed(_TABLES):
        for column in reversed(_COLUMNS):
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")  # sql-ok: feste Bezeichner aus dem Code
