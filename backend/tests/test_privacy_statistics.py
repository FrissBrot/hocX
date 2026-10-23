"""Datenschutz-Audit PRIV-001: Bussen und Anwesenheit je Person sehen in der Statistik nur Writer,
Kassier und Admins. Leser sehen ihre eigene Zeile, ausser der Mandant gibt die Ranglisten frei
(tenant.statistics_per_person_public). Dieselbe Regel gilt für Diagramme und Tabellen der
Dokument-Engine, weil PDFs mit dem anfragenden Benutzer gerendert werden."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes.privacy_settings import PrivacySettingsWrite, get_privacy_settings, update_privacy_settings
from app.api.routes.statistics import get_statistics_overview
from app.documents.catalog import BlockSpec, ChartParams, StatTableParams
from app.documents.context import BuildContext
from app.documents.providers.statistics import provide_chart, provide_table
from tests.factories import (
    make_app_user,
    make_current_user,
    make_finance_account,
    make_fine,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _setup(db):
    tenant = make_tenant(db, "Statistik Datenschutz")
    reader = make_app_user(db, email="leser@example.com", first_name="Lea", last_name="Leser", tenant_id=tenant.id)
    other = make_app_user(db, email="andere@example.com", first_name="Otto", last_name="Andere", tenant_id=tenant.id)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 3, 1), status="durchgeführt")
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(
        db,
        element.id,
        configuration_snapshot_json={
            "attendance_entries": [
                {"participant_id": reader.id, "participant_name": "Lea Leser", "status": "present"},
                {"participant_id": other.id, "participant_name": "Otto Andere", "status": "absent"},
            ]
        },
        element_type_code="attendance",
    )
    account = make_finance_account(db, tenant.id)
    for person, name in ((reader, "Lea Leser"), (other, "Otto Andere")):
        fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=Decimal("5.00"), participant_name_snapshot=name, fine_type="absent")
        fine.participant_id = person.id
    db.flush()
    return tenant, reader, other


def _overview(db, tenant_id: int, role: str, user_id: int, features=None):
    return get_statistics_overview(db=db, user=make_current_user(tenant_id, role=role, user_id=user_id, features=features))


def test_reader_sees_only_own_rows(db):
    tenant, reader, _ = _setup(db)

    overview = _overview(db, tenant.id, "reader", reader.id)

    assert overview.per_person_scope == "own"
    assert [row.name for row in overview.attendance_by_participant] == ["Lea Leser"]
    assert [row.name for row in overview.fines_by_participant] == ["Lea Leser"]
    # Aggregierte Werte bleiben vollständig.
    assert sum(month.total for month in overview.attendance_over_time) == 2
    assert sum(row.count for row in overview.fines_by_type) == 2


@pytest.mark.parametrize("role", ["writer", "kassier", "admin"])
def test_privileged_roles_see_everyone(db, role):
    tenant, reader, _ = _setup(db)

    overview = _overview(db, tenant.id, role, reader.id)

    assert overview.per_person_scope == "all"
    assert sorted(row.name for row in overview.attendance_by_participant) == ["Lea Leser", "Otto Andere"]
    assert sorted(row.name for row in overview.fines_by_participant) == ["Lea Leser", "Otto Andere"]


def test_tenant_switch_shares_rankings_with_readers(db):
    tenant, reader, _ = _setup(db)
    tenant.statistics_per_person_public = True
    db.flush()

    overview = _overview(db, tenant.id, "reader", reader.id)

    assert overview.per_person_scope == "all"
    assert len(overview.fines_by_participant) == 2


def test_finance_figures_require_finance_feature(db):
    tenant, reader, _ = _setup(db)

    overview = _overview(db, tenant.id, "admin", reader.id, features=frozenset({"abgabebox"}))

    assert overview.finance_by_month == []


def test_document_charts_and_tables_follow_the_same_rule(db):
    tenant, reader, _ = _setup(db)
    reader_ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", user=make_current_user(tenant.id, role="reader", user_id=reader.id))
    writer_ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", user=make_current_user(tenant.id, role="writer", user_id=reader.id))

    chart = provide_chart(reader_ctx, BlockSpec(type="chart"), ChartParams(chart_type="attendance_by_participant"))[0]
    assert chart.categories == ["Lea Leser"]
    fines_chart = provide_chart(reader_ctx, BlockSpec(type="chart"), ChartParams(chart_type="fines_by_participant"))[0]
    assert fines_chart.categories == ["Lea Leser"]
    table = provide_table(reader_ctx, BlockSpec(type="stat_table"), StatTableParams(table="fines_by_participant"))[0]
    assert len(table.table.groups[0].rows) == 1

    full = provide_chart(writer_ctx, BlockSpec(type="chart"), ChartParams(chart_type="attendance_by_participant"))[0]
    assert sorted(full.categories) == ["Lea Leser", "Otto Andere"]


def test_only_admins_change_the_switch(db):
    tenant, reader, _ = _setup(db)
    admin = make_app_user(db, email="admin@example.com", tenant_id=tenant.id, role_code="admin")

    with pytest.raises(HTTPException) as denied:
        update_privacy_settings(PrivacySettingsWrite(statistics_per_person_public=True), db=db, user=make_current_user(tenant.id, role="writer", user_id=reader.id))
    assert denied.value.status_code == 403

    admin_user = make_current_user(tenant.id, role="admin", user_id=admin.id)
    assert get_privacy_settings(db=db, user=admin_user).statistics_per_person_public is False
    result = update_privacy_settings(PrivacySettingsWrite(statistics_per_person_public=True), db=db, user=admin_user)
    assert result.statistics_per_person_public is True
