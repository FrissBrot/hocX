"""Notausgang für Plattform-Admins (RUNBOOK Abschnitt 21).

Admins melden sich nur mit Passwort + Passkey an. Geht der letzte Passkey verloren, setzt dieser
Befehl die Passkeys eines Kontos zurück - nur auf dem Host, im Backend-Container:

    docker compose -p <projekt> exec backend python -m app.admin_cli reset-passkeys --email admin@example.ch

Löscht alle Passkeys des Kontos, beendet seine Sessions und offenen Login-Vorgänge
(session_revoke_at) und schreibt einen Audit-Eintrag. Beim nächsten Login richtet das Konto nach
dem Passwort einen neuen Passkey ein (Trust on first use). Es gibt dafür bewusst keine HTTP-Route:
wer den Befehl ausführen kann, hat ohnehin Zugriff auf den Server.
"""
from __future__ import annotations

import argparse
import sys

from app.core.db import SessionLocal
from app.models import PlatformAdmin
from app.services.admin_mfa_service import AdminMfaService
from app.services.audit_service import AuditService


def reset_passkeys(email: str) -> int:
    with SessionLocal() as db:
        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == email.strip()).one_or_none()
        if admin is None:
            print(f"Kein Plattform-Admin mit der E-Mail {email!r}.", file=sys.stderr)
            return 1
        removed = AdminMfaService().reset_passkeys(db, admin)
        AuditService().log(
            db,
            action="admin.passkeys_reset",
            actor_email=admin.email,
            details={"via": "admin_cli", "removed": removed},
        )
        print(f"{removed} Passkey(s) von {admin.email} entfernt, Sessions beendet. "
              "Beim nächsten Login wird ein neuer Passkey eingerichtet.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin_cli", description="Notausgang Plattform-Admin")
    commands = parser.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset-passkeys", help="Passkeys eines Admins löschen und Sessions beenden")
    reset.add_argument("--email", required=True, help="E-Mail des Plattform-Admins")
    args = parser.parse_args(argv)
    if args.command == "reset-passkeys":
        return reset_passkeys(args.email)
    return 2


if __name__ == "__main__":
    sys.exit(main())
