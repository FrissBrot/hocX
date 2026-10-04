"""Zyklusauswahl: Grenzen, Mandantentrennung und gleiche Daten in UI/PDF."""
from datetime import date

import pytest

from app.api.routes.statistics import get_statistics_overview
from app.models.entities import CycleConfig
from app.services.chart_service import _fetch_attendance_data
from app.services.statistics_common import chart_cycle_bounds
from tests.factories import (
    make_current_user, make_tenant, make_template, make_protocol,
    make_protocol_element, make_protocol_element_block,
)


@pytest.mark.parametrize("month,day", [(7, 31), (12, 31), (2, 31)])
def test_cycle_bounds_and_previous_year(db, month, day):
    tenant = make_tenant(db)
    config = CycleConfig(tenant_id=tenant.id, name="Test", reset_month=month, reset_day=day)
    db.add(config)
    db.flush()
    current = chart_cycle_bounds(db, tenant.id, config.public_id)
    previous = chart_cycle_bounds(db, tenant.id, config.public_id, -1)
    assert current[0] <= date.today() <= current[1]
    assert (current[0] - previous[1]).days == 1
    assert chart_cycle_bounds(db, tenant.id, None) is None
    with pytest.raises(ValueError, match="Zyklus nicht gefunden"):
        chart_cycle_bounds(db, make_tenant(db).id, config.public_id)


def test_attendance_cycle_filter_matches_preview_and_pdf(db):
    tenant = make_tenant(db)
    config = CycleConfig(tenant_id=tenant.id, name="Test", reset_month=7, reset_day=31)
    db.add(config)
    db.flush()
    template = make_template(db, tenant.id)
    current = chart_cycle_bounds(db, tenant.id, config.public_id)
    previous = chart_cycle_bounds(db, tenant.id, config.public_id, -1)
    for index, (day, status) in enumerate([(previous[1], "absent"), (current[0], "present"), (current[1], "excused")]):
        protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"cycle-{index}", protocol_date=day, status="durchgeführt")
        element = make_protocol_element(db, protocol.id)
        make_protocol_element_block(db, element.id, element_type_code="attendance", configuration_snapshot_json={
            "attendance_entries": [{"participant_id": 42, "participant_name": "Anna", "status": status}],
        })
    for offset, expected in [(0, 2), (-1, 1)]:
        overview = get_statistics_overview(db=db, user=make_current_user(tenant.id), cycle_config_id=config.public_id, cycle_offset=offset)
        _, pdf_rows = _fetch_attendance_data(db, tenant.id, chart_cycle_bounds(db, tenant.id, config.public_id, offset))
        assert overview.attendance_by_participant[0].total == expected
        assert pdf_rows[0]["total"] == expected
