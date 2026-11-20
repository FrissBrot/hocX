"""Zyklus ändern mit ausdrücklichem null (Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

PUT /cycle-configs/{id} mit {"name": null} oder {"reset_month": null} setzte die NOT-NULL-Spalte
auf NULL: IntegrityError beim Commit, Antwort 400 «Could not update cycle config» und ein
Eintrag in system_error_log, als wäre es ein unerwarteter Serverfehler."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes import cycle_configs as cycle_routes
from app.schemas.cycle_config import CycleConfigUpdate
from tests.factories import make_current_user, make_cycle_config, make_tenant


@pytest.mark.parametrize("field", ["name", "reset_month", "reset_day"])
def test_explicit_null_is_rejected_by_the_schema(field):
    with pytest.raises(ValidationError):
        CycleConfigUpdate.model_validate({field: None})


def test_omitted_fields_and_null_pattern_still_work(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    cfg = make_cycle_config(db, tenant.id, name="Vereinsjahr", reset_month=7, reset_day=31)
    cfg.name_pattern = "[cy]/[cy_end]"
    db.flush()

    updated = cycle_routes.update_cycle_config(
        cfg.public_id, CycleConfigUpdate.model_validate({"name_pattern": None}), db=db, user=user
    )

    assert updated.name == "Vereinsjahr"
    assert (updated.reset_month, updated.reset_day) == (7, 31)
    assert updated.name_pattern is None
