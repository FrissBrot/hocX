#!/usr/bin/env python3
"""Lasttest-Daten für einen ISOLIERTEN hocX-Stack anlegen (nie Produktion, nie die Dev-Instanz).

Legt N Mandanten nach dem Muster von backend/scripts/seed_test_tenant.py an (Vorlage, Teilnehmende,
Liste, Termine, Protokolle mit Text-/Todo-/Bildblöcken, Galerie, Abgabe) und pro Mandant zusätzlich
W Schreibkonten. Für jedes Konto wird ein Session-Token mit der Signatur des Backends erzeugt -
der Lasttest braucht so keinen Login (Traefik begrenzt /api/auth/login auf 10/min je IP).

Ausgabe: JSON auf stdout (oder --out), Format siehe README.md ("tokens.json").

Aufruf im Backend-Container des Lasttest-Stacks (Repo-Root als /app gemountet oder Datei kopiert):
    HOCX_LOADTEST=1 python /loadtest/seed/seed_loadtest.py --tenants 10 --writers 10 --out /loadtest/tokens.json

Schutz: bricht ab bei HOCX_ENVIRONMENT=production, ohne HOCX_LOADTEST=1 und wenn der Datenbankname
nicht auf einen Wegwerf-Stack hindeutet (enthält "loadtest", "e2e" oder "test").
Wiederholbar: vorhandene Lasttest-Mandanten (Name beginnt mit "LT ") werden vorher gelöscht.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.core.security import create_session_token, hash_password  # noqa: E402
from app.models.entities import AppUser, Role, SubmissionAssignment, SubmissionLink, Tenant, TenantFeature  # noqa: E402

import scripts.seed_test_tenant as demo  # noqa: E402  (backend/scripts, liegt im Image unter /app/scripts)

PREFIX = "LT "
SEED_FEATURES = ("abgabebox", "finance")


def _guard() -> None:
    if settings.is_production:
        sys.exit("FATAL: HOCX_ENVIRONMENT=production - Lasttest-Seed verweigert.")
    if os.environ.get("HOCX_LOADTEST") != "1":
        sys.exit("FATAL: HOCX_LOADTEST=1 fehlt - nur auf einem ausdrücklich freigegebenen, isolierten Stack ausführen.")
    database = (make_url(settings.app_database_url or settings.database_url).database or "").lower()
    if not any(marker in database for marker in ("loadtest", "e2e", "test")):
        sys.exit(f"FATAL: Datenbank '{database}' sieht nicht nach einem Wegwerf-Stack aus.")


def _wipe(db) -> None:
    from app.services.admin_tenant_service import AdminTenantService

    for tenant in db.scalars(select(Tenant).where(Tenant.name.like(f"{PREFIX}%"))).all():
        AdminTenantService().delete_tenant(db, tenant.id)
    db.query(AppUser).filter(AppUser.email.like("%@lt%.hocx.local")).delete(synchronize_session=False)
    db.commit()


def _seed_tenant(db, index: int, writers: int, password_hash: str, writer_role_id: int) -> dict:
    demo.DEMO_TENANT_NAME = f"{PREFIX}{index:03d}"
    demo.DEMO_TENANT_SLUG = f"lt{index:03d}"
    tenant, users = demo.create_tenant_and_users(db)
    template = demo.create_template_structure(db, tenant, users["admin"])
    participants = demo.create_participants(db, tenant)
    list_definition = demo.create_participant_list(db, tenant, participants)
    events = demo.create_events(db, tenant)
    db.commit()
    photos = sorted((demo.SEED_ASSETS_DIR / "photos").glob("*.jpg"))
    demo.create_protocols(db, tenant, template, events, users["admin"], list(photos))
    db.commit()
    demo.create_gallery(db, tenant, users["writer"], list(photos[:5]))
    db.commit()
    demo.create_submission_assignment(db, tenant, list_definition)
    # Gebuchte Module wie bei einem Verein mit Abo: ohne "abgabebox" weist die öffentliche
    # Abgabebox jeden Link mit 403 ab (Upload-Sturm fand keine Elemente), ohne "finance" fehlt
    # die Finanzlast.
    for code in SEED_FEATURES:
        db.add(TenantFeature(tenant_id=tenant.id, feature_code=code))
    db.commit()

    accounts = [users["writer"]]
    for number in range(writers):
        user = AppUser(
            tenant_id=tenant.id,
            role_id=writer_role_id,
            first_name="Last",
            last_name=f"{index:03d}-{number:03d}",
            display_name=f"Last {index:03d}-{number:03d}",
            email=f"writer{number:03d}@lt{index:03d}.hocx.local",
            password_hash=password_hash,
            login_enabled=True,
            is_active=True,
        )
        db.add(user)
        accounts.append(user)
    # Abgabe ohne Dateilimit, damit der Upload-Sturm nicht an max_files_per_element endet.
    assignment = db.scalars(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == tenant.id)).first()
    if assignment is not None:
        assignment.max_files_per_element = 100000
    db.commit()
    link = db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == tenant.id, SubmissionLink.is_default.is_(True))).first()
    return {
        "tenant": tenant.name,
        "tenant_public_id": str(tenant.public_id),
        "abgabebox": {
            "link_token": link.token if link else None,
            "assignment_slug": assignment.public_slug if assignment else None,
        },
        "sessions": [create_session_token(user.id, mfa_verified=True) for user in accounts],
        # Admin braucht einen MFA-Faktor (DEMO_TOTP_SEED beim Seed setzen), sonst lehnt
        # get_optional_current_user die Session ab - nur für Vereinsexport/Studio-Szenarien.
        "admin_session": create_session_token(users["admin"].id, mfa_verified=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenants", type=int, default=10)
    parser.add_argument("--writers", type=int, default=10, help="zusätzliche Schreibkonten je Mandant")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    _guard()
    password_hash = hash_password(os.urandom(24).hex())  # Konten sind nur per Token nutzbar
    with SessionLocal() as db:
        writer_role_id = db.scalar(select(Role.id).where(Role.code == "writer"))
        _wipe(db)
        result = {
            "cookie_name": settings.auth_session_cookie,
            "tenants": [_seed_tenant(db, i, args.writers, password_hash, writer_role_id) for i in range(1, args.tenants + 1)],
        }
    payload = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"{sum(len(t['sessions']) for t in result['tenants'])} Sessions in {len(result['tenants'])} Mandanten -> {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
