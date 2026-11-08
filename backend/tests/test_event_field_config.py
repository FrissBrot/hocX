"""Spezialfelder der Termine: Alias/Ausblenden je Mandant."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import event_field_config as routes
from app.schemas.event_field_config import EventFieldConfig, EventFieldSetting
from tests.factories import make_current_user, make_tenant


def test_defaults_then_save_and_read_per_tenant(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    admin = make_current_user(tenant.id, role="admin")

    assert routes.get_event_field_config(db=db, user=admin).spezial1_ids == EventFieldSetting()

    saved = routes.put_event_field_config(
        EventFieldConfig(spezial1_ids=EventFieldSetting(label="  Leiter  "), spezial_text3=EventFieldSetting(hidden=True)),
        db=db, user=admin,
    )

    assert saved.spezial1_ids.label == "Leiter"
    assert saved.spezial_text3.hidden is True
    assert routes.get_event_field_config(db=db, user=make_current_user(tenant.id, role="reader")).spezial1_ids.label == "Leiter"
    assert routes.get_event_field_config(db=db, user=make_current_user(other.id, role="reader")).spezial1_ids.label == ""


def test_only_settings_managers_may_change(db):
    tenant = make_tenant(db)
    with pytest.raises(HTTPException) as excinfo:
        routes.put_event_field_config(EventFieldConfig(), db=db, user=make_current_user(tenant.id, role="writer"))
    assert excinfo.value.status_code == 403


def test_invalid_stored_values_fall_back_to_defaults():
    config = EventFieldConfig.from_stored({"spezial1_ids": {"label": 5, "hidden": "x"}, "unknown": {}, "spezial2_ids": {"label": "Koch"}})
    assert config.spezial1_ids == EventFieldSetting()
    assert config.spezial2_ids.label == "Koch"
