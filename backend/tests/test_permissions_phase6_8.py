"""Plan «Berechtigungen» Phase 6 (öffentliche Links) und Phase 8 (Nachvollziehbarkeit).

- Rollen-Zuweisungen landen mit vorher/nachher im Verlauf - über jeden Weg, in derselben
  Transaktion (role_service.set_user_roles).
- Öffentliche Links: Erstellen und Widerrufen im Verlauf (public_link.*).
"""
from __future__ import annotations

import dataclasses

from sqlalchemy import text

from app.api.routes import share_links as share_links_routes
from app.schemas.files import ShareLinkCreate
from app.services import role_service
from app.services.role_service import system_role
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.test_share_link_routes import _make_file


def _audit(db, tenant_id: int, action: str) -> list[dict]:
    return [
        row.details_json for row in db.execute(
            text("SELECT details_json FROM audit_log WHERE tenant_id = :t AND action = :a ORDER BY id"), {"t": tenant_id, "a": action}
        )
    ]


def test_role_assignment_is_audited_with_before_and_after(db):
    tenant = make_tenant(db, "Audit Rollen")
    admin = make_app_user(db, "audit-admin@example.com", tenant_id=tenant.id, role_code="admin")
    member = make_app_user(db, "audit-mitglied@example.com", tenant_id=tenant.id, role_code="reader")
    actor = dataclasses.replace(make_current_user(tenant.id, role="admin", user_id=admin.id), mfa_verified=True)

    role_service.set_user_roles(db, actor, member, [system_role(db, tenant.id, "writer")])
    db.commit()

    [entry] = _audit(db, tenant.id, "user.roles_changed")
    assert entry == {"before": ["reader"], "after": ["writer"]}
    # Keine Änderung: kein Eintrag
    role_service.set_user_roles(db, actor, member, [system_role(db, tenant.id, "writer")])
    db.commit()
    assert len(_audit(db, tenant.id, "user.roles_changed")) == 1


def test_public_links_are_audited(db):
    tenant = make_tenant(db, "Audit Links")
    writer = make_current_user(tenant.id, role="writer")
    link = share_links_routes.create_share_link(ShareLinkCreate(name="Lagerfotos", file_ids=[_make_file(db, tenant.id).public_id]), db, writer)
    share_links_routes.revoke_share_link(link.id, db, writer)

    [created] = _audit(db, tenant.id, "public_link.created")
    [revoked] = _audit(db, tenant.id, "public_link.revoked")
    assert created["name"] == "Lagerfotos" and created["kind"] == "share_files" and created["file_count"] == 1
    assert revoked["link_id"] == str(link.id)
