"""Notausgang für Plattform-Admins (RUNBOOK Abschnitt 22).

Admins melden sich nur mit Passwort + Passkey an. Diese Befehle laufen nur auf dem Host, im
Backend-Container - es gibt bewusst keine HTTP-Route dafür (wer sie ausführen kann, hat ohnehin
Zugriff auf den Server):

    docker compose -p <projekt> exec backend python -m app.admin_cli reset-passkeys --email admin@example.ch
    docker compose -p <projekt> exec backend python -m app.admin_cli reset-password --email admin@example.ch

reset-passkeys: löscht alle Passkeys des Kontos; beim nächsten Login richtet es nach dem Passwort einen
neuen ein (Trust on first use).
reset-password: setzt ein neues zufälliges Passwort und zeigt es genau einmal an.

Beide beenden alle Sessions und offenen Login-Vorgänge (session_revoke_at), löschen die Sperrzähler
des Kontos und schreiben den Audit-Eintrag (actor «cli») in derselben Transaktion.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import PlatformAdmin
from app.services.admin_mfa_service import AdminMfaService, clear_admin_lockouts
from app.services.audit_service import AuditService

CLI_ACTOR = "cli"


def _admin(db, email: str) -> PlatformAdmin | None:
    admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == email.strip()).with_for_update().one_or_none()
    if admin is None:
        print(f"Kein Plattform-Admin mit der E-Mail {email!r}.", file=sys.stderr)
    return admin


def reset_passkeys(email: str) -> int:
    with SessionLocal() as db:
        admin = _admin(db, email)
        if admin is None:
            return 1
        removed = AdminMfaService().reset_passkeys(db, admin, commit=False)
        AuditService().log(
            db, action="admin.passkeys_reset", actor_email=CLI_ACTOR, entity_type="platform_admin", entity_id=admin.id,
            details={"admin_email": admin.email, "removed": removed}, commit=False,
        )
        db.commit()
        clear_admin_lockouts(admin)
        print(f"{removed} Passkey(s) von {admin.email} entfernt, Sessions beendet. "
              "Beim nächsten Login wird ein neuer Passkey eingerichtet - sofort selbst anmelden.")
        return 0


def reset_password(email: str) -> int:
    with SessionLocal() as db:
        admin = _admin(db, email)
        if admin is None:
            return 1
        password = secrets.token_urlsafe(18)
        admin.password_hash = hash_password(password)
        admin.session_revoke_at = datetime.now(UTC)
        db.add(admin)
        AuditService().log(
            db, action="admin.password_reset", actor_email=CLI_ACTOR, entity_type="platform_admin", entity_id=admin.id,
            details={"admin_email": admin.email}, commit=False,
        )
        db.commit()
        clear_admin_lockouts(admin)
        print(f"Neues Passwort für {admin.email} (wird nur jetzt angezeigt, sofort ändern):")
        print(password)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin_cli", description="Notausgang Plattform-Admin")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("reset-passkeys", "Passkeys eines Admins löschen, Sessions beenden"),
        ("reset-password", "Neues zufälliges Passwort setzen, Sessions beenden"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--email", required=True, help="E-Mail des Plattform-Admins")
    args = parser.parse_args(argv)
    if args.command == "reset-passkeys":
        return reset_passkeys(args.email)
    return reset_password(args.email)


if __name__ == "__main__":
    sys.exit(main())
