"""Wartungsmodus während eines Updates - aufgerufen von scripts/deploy.sh (RUNBOOK Abschnitt 20).

    docker compose run --rm --no-deps backend python -m app.maintenance_cli begin-deploy --version <v> [--from-version <alt>]
    docker compose run --rm --no-deps backend python -m app.maintenance_cli end-deploy --outcome success
    docker compose run --rm --no-deps backend python -m app.maintenance_cli status

begin-deploy legt ein volles, sofort aktives Wartungsfenster an (source_job_type="deploy"):
das noch laufende alte Backend sperrt die API (503 "maintenance"), das alte Frontend zeigt
angemeldeten Nutzern seine Wartungsansicht, die Abgabebox ihr Wartungsbanner - statt Fehlern
gegen ein Schema, das die Migration gerade ändert. end-deploy beendet nur Deploy-Fenster, nie ein
von Admins geplantes oder ein Speicher-Fenster. Beide sind idempotent und auditiert.

Existiert die Tabelle maintenance_window noch nicht (erste Installation), wird übersprungen.
Exit-Codes: 0 ok oder übersprungen, 1 Fehler.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

OUTCOMES = ("success", "rollback", "aborted")


def _tables_exist(db) -> bool:
    return bool(db.execute(text(
        "SELECT to_regclass('public.maintenance_window') IS NOT NULL AND to_regclass('public.maintenance_event') IS NOT NULL"
    )).scalar())


def begin_deploy(db, *, version: str | None, from_version: str | None = None) -> str:
    from app.services import maintenance_service
    from app.services.audit_service import AuditService

    if not _tables_exist(db):
        return "übersprungen (Wartungstabellen fehlen - erste Installation)"
    window, created = maintenance_service.begin_deploy_window(db, version=version, from_version=from_version)
    db.commit()
    AuditService().log(
        db, action="admin.maintenance_deploy_started", actor_email=maintenance_service.DEPLOY_ACTOR,
        entity_type="maintenance_window",
        details={"window_id": str(window.id), "version": version, "from_version": from_version, "created": created},
    )
    return f"Wartung aktiv (Fenster {window.id}, {'neu' if created else 'bereits offen'})"


def end_deploy(db, *, outcome: str) -> str:
    from app.services import maintenance_service
    from app.services.audit_service import AuditService

    if not _tables_exist(db):
        return "übersprungen (Wartungstabellen fehlen)"
    windows = maintenance_service.end_deploy_windows(db, outcome=outcome)
    db.commit()
    if not windows:
        return "kein offenes Deploy-Fenster"
    AuditService().log(
        db, action="admin.maintenance_deploy_ended", actor_email=maintenance_service.DEPLOY_ACTOR,
        entity_type="maintenance_window", details={"window_ids": [str(w.id) for w in windows], "outcome": outcome},
    )
    return f"Wartung beendet ({len(windows)} Fenster, {outcome})"


def status(db) -> str:
    from app.services import maintenance_service

    if not _tables_exist(db):
        return "keine Wartungstabellen"
    windows = maintenance_service.open_deploy_windows(db)
    db.rollback()
    if not windows:
        return "kein offenes Deploy-Fenster"
    return "; ".join(f"{w.id} {w.state} seit {w.started_at}" for w in windows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.maintenance_cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("begin-deploy", help="Wartung für das Update starten (idempotent)")
    begin.add_argument("--version", default=None, help="Ziel-Release (Verlauf, Audit, öffentliche Update-Seite)")
    begin.add_argument("--from-version", default=None, help="laufendes Release (Verlauf, Audit, öffentliche Update-Seite)")
    end = sub.add_parser("end-deploy", help="Deploy-Wartung beenden (idempotent)")
    end.add_argument("--outcome", choices=OUTCOMES, default="success")
    sub.add_parser("status", help="offene Deploy-Fenster anzeigen")
    args = parser.parse_args(argv)

    from app.core.db import SessionLocal

    try:
        with SessionLocal() as db:
            if args.command == "begin-deploy":
                message = begin_deploy(db, version=args.version, from_version=args.from_version)
            elif args.command == "end-deploy":
                message = end_deploy(db, outcome=args.outcome)
            else:
                message = status(db)
    except Exception as exc:  # noqa: BLE001 - CLI: Fehler als Meldung, deploy.sh wertet den Exit-Code aus
        print(f"maintenance_cli {args.command}: FEHLER {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"maintenance_cli {args.command}: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
