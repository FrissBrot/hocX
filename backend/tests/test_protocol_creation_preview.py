"""Echte Namensvorschau und benutzerspezifische Vorlagenauswahl."""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes.protocols import (TemplatePreferencePayload, get_template_preference,
                                     preview_protocol, save_template_preference)
from app.models import CycleConfig, Protocol
from app.models.entities import UserProtocolTemplatePreference
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.services.protocol_service import ProtocolService
from tests.factories import make_current_user, make_protocol, make_template, make_tenant, make_app_user


@pytest.mark.parametrize("status,expected", [("geplant", "P-1"), ("abgeschlossen", "P-2")])
def test_preview_matches_creation_without_changing_siblings(db, status, expected):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-[n]"
    template.title_pattern = "[n]. Hock vom [dd.mm.yyyy]"
    db.flush()
    sibling = make_protocol(db, tenant.id, template.id, protocol_date=date(2026, 10, 20), status=status)
    before = db.scalar(select(func.count()).select_from(Protocol))
    service = ProtocolService()
    names = service.preview_names(db, tenant_id=tenant.id, template=template, protocol_date=date(2026, 10, 12))
    db.refresh(sibling)
    assert sibling.protocol_number == "P-1"
    assert sibling.title is None
    assert db.scalar(select(func.count()).select_from(Protocol)) == before
    assert names == {"protocol_number": expected, "title": "1. Hock vom 12.10.2026"}
    created_id = service.create_from_template(db, ProtocolCreateFromTemplate(
        template_id=template.public_id, protocol_date=date(2026, 10, 12)), tenant_id=tenant.id, created_by=None)
    created = db.get(Protocol, created_id)
    assert (created.protocol_number, created.title) == (names["protocol_number"], names["title"])


def test_preview_resolves_cycle_and_all_date_tokens(db):
    tenant = make_tenant(db)
    cfg = CycleConfig(tenant_id=tenant.id, name="Scharjahr", reset_month=7, reset_day=31)
    db.add(cfg)
    db.flush()
    template = make_template(db, tenant.id)
    template.cycle_config_id = cfg.id
    template.protocol_number_pattern = "[cycle_yyyy_start]/[cycle_yyyy_end].[n_cycle]"
    template.title_pattern = "[n]. Hock vom [dd.mm.yyyy]"
    db.flush()
    names = preview_protocol(template.public_id, date(2026, 10, 12), db=db, user=make_current_user(tenant.id))
    assert names == {"protocol_number": "2026/2027.1", "title": "1. Hock vom 12.10.2026"}


def test_preference_is_scoped_to_user_and_tenant(db):
    tenant = make_tenant(db)
    other_tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    other_template = make_template(db, other_tenant.id)
    user = make_app_user(db, tenant_id=tenant.id, role_code="writer")
    actor = make_current_user(tenant.id, user_id=user.id)
    save_template_preference(TemplatePreferencePayload(template_id=template.public_id), db=db, user=actor)
    assert get_template_preference(db=db, user=actor) == {"template_id": template.public_id}
    assert get_template_preference(db=db, user=make_current_user(tenant.id, user_id=user.id + 1)) == {"template_id": None}
    assert get_template_preference(db=db, user=make_current_user(other_tenant.id, user_id=user.id)) == {"template_id": None}
    with pytest.raises(HTTPException) as error:
        save_template_preference(TemplatePreferencePayload(template_id=other_template.public_id), db=db, user=actor)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        preview_protocol(other_template.public_id, date(2026, 10, 12), db=db, user=actor)
    assert error.value.status_code == 404
    db.delete(template)
    db.flush()
    db.expire_all()
    assert get_template_preference(db=db, user=actor) == {"template_id": None}
    assert db.get(UserProtocolTemplatePreference, (user.id, tenant.id)).template_id is None


def test_reader_cannot_change_preference_or_preview(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    actor = make_current_user(tenant.id, role="reader")
    with pytest.raises(HTTPException) as error:
        save_template_preference(TemplatePreferencePayload(template_id=template.public_id), db=db, user=actor)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        preview_protocol(template.public_id, date(2026, 10, 12), db=db, user=actor)
    assert error.value.status_code == 403
