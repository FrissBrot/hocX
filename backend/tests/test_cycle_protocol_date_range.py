"""Protokolldatum ausserhalb des Kalenderbereichs legt die Zyklenliste lahm
(Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

PATCH /protocols/{id} nahm jedes ISO-Datum an, z. B. 0001-01-02. Liegt das Protokoll in einer
Vorlage mit Zyklus, berechnete GET /cycle-configs/{id}/cycles den Vorjahres-Stichtag im Jahr 0:
ValueError «year 0 is out of range» -> 500 bei jedem Abruf, bis das Protokoll korrigiert war.
Termine sind seit #65 auf 1900-2999 begrenzt, Protokolle nicht."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.routes import cycle_configs as cycle_routes
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolUpdate
from tests.factories import make_current_user, make_cycle_config, make_protocol, make_template, make_tenant


@pytest.mark.parametrize("value", [date(1, 1, 2), date(9999, 12, 31)])
def test_protocol_date_outside_range_is_rejected(value):
    with pytest.raises(ValidationError):
        ProtocolUpdate(protocol_date=value)
    with pytest.raises(ValidationError):
        ProtocolCreateFromTemplate(template_id="00000000-0000-0000-0000-000000000001", protocol_date=value)


def test_protocol_date_within_range_still_accepted():
    assert ProtocolUpdate(protocol_date=date(1900, 1, 1)).protocol_date == date(1900, 1, 1)
    assert ProtocolUpdate().protocol_date is None


def test_cycle_list_survives_legacy_protocol_with_year_one(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    cfg = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    template = make_template(db, tenant.id)
    template.cycle_config_id = cfg.id
    make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2025, 9, 1))
    make_protocol(db, tenant.id, template.id, protocol_number="P-2", protocol_date=date(1, 1, 2))
    db.flush()

    cycles = cycle_routes.list_cycles(cfg.public_id, db=db, user=user)

    assert 2025 in {cycle.cycle_year for cycle in cycles}
