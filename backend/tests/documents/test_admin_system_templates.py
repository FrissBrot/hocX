"""Adminportal «Dokumentvorlagen» (FAR-010): Plattform-Admins sehen die mitgelieferten
Systemvorlagen, setzen je Dokumentart den Plattform-Standard und archivieren/reaktivieren
Vorlagen. Vorher gab es die Routen, aber keine Oberfläche."""
from __future__ import annotations

import uuid
from collections import Counter

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import admin_document_templates as routes
from app.core.admin_security import CurrentAdmin
from app.models import DocumentTemplate
from tests.factories import make_tenant


def _admin() -> CurrentAdmin:
    return CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="admin@example.org", display_name="Admin", role="owner")


def _defaults_by_type(db) -> Counter:
    return Counter(row.document_type for row in routes.list_system_templates(db=db, admin=_admin()) if row.is_platform_default)


def _alternative(db) -> DocumentTemplate:
    """Eine aktive Systemvorlage, die nicht Standard ist, für eine Dokumentart mit Standard."""
    defaults = {t.document_type for t in db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None), DocumentTemplate.is_platform_default.is_(True)))}
    candidate = db.scalar(
        select(DocumentTemplate).where(
            DocumentTemplate.tenant_id.is_(None),
            DocumentTemplate.status == "active",
            DocumentTemplate.is_platform_default.is_(False),
            DocumentTemplate.document_type.in_(defaults),
        )
    )
    if candidate is None:
        pytest.skip("keine zweite Systemvorlage für eine Dokumentart mit Standard")
    return candidate


def test_list_shows_only_system_templates_with_name_and_at_most_one_default_per_type(db):
    tenant = make_tenant(db)
    db.add(DocumentTemplate(tenant_id=tenant.id, name="Eigene", document_type="protocol"))
    db.flush()

    rows = routes.list_system_templates(db=db, admin=_admin())

    assert rows and all(row.system_key for row in rows)
    assert "Eigene" not in {row.name for row in rows}
    assert all(count == 1 for count in _defaults_by_type(db).values())


def test_new_platform_default_replaces_the_old_one(db):
    candidate = _alternative(db)
    before = _defaults_by_type(db)

    result = routes.set_platform_default(candidate.public_id, db=db, admin=_admin())

    assert result.is_platform_default is True
    assert _defaults_by_type(db) == before
    default_ids = {row.id for row in routes.list_system_templates(db=db, admin=_admin()) if row.is_platform_default}
    assert candidate.public_id in default_ids


def test_the_platform_default_cannot_be_archived_and_archived_ones_cannot_become_default(db):
    current_default = db.scalar(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None), DocumentTemplate.is_platform_default.is_(True)))
    with pytest.raises(HTTPException) as blocked:
        routes.archive_system_template(current_default.public_id, routes.StatusBody(archived=True), db=db, admin=_admin())
    assert blocked.value.status_code == 422

    candidate = _alternative(db)
    archived = routes.archive_system_template(candidate.public_id, routes.StatusBody(archived=True), db=db, admin=_admin())
    assert archived.status == "archived"
    with pytest.raises(HTTPException) as refused:
        routes.set_platform_default(candidate.public_id, db=db, admin=_admin())
    assert refused.value.status_code == 422

    assert routes.archive_system_template(candidate.public_id, routes.StatusBody(archived=False), db=db, admin=_admin()).status == "active"


def test_tenant_templates_are_not_reachable_through_the_admin_routes(db):
    tenant = make_tenant(db)
    own = DocumentTemplate(tenant_id=tenant.id, name="Eigene", document_type="protocol")
    db.add(own)
    db.flush()

    with pytest.raises(HTTPException) as hidden:
        routes.set_platform_default(own.public_id, db=db, admin=_admin())
    assert hidden.value.status_code == 404
