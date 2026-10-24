"""FAR-002 (Feature-Recovery-Audit v1.2): Bussentarif je Protokollvorlage (0137). Standard ist der
Mandantentarif; eine Vorlage kann ihn übersteuern. Der Tarif gilt live für alle Protokolle der
Vorlage, das Konto muss zum eigenen Mandanten gehören."""
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.routes import templates as template_routes
from app.models.entities import Template
from app.schemas.fines import FineTariffUpdate, TemplateFineTariffUpdate
from app.services import fine_tariff_service
from app.services.protocol_element_service import ProtocolElementService
from app.services.template_service import TemplateService
from app.services.tenant_clone_service import TenantCloneService
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)
from tests.test_tenant_export_import import _export_import

FINANCE = frozenset({"finance"})


def _setup(db):
    tenant = make_tenant(db)
    tenant_account = make_finance_account(db, tenant.id, name="Vereinskasse")
    template_account = make_finance_account(db, tenant.id, name="Jugendkasse")
    fine_tariff_service.update_tariff(
        db, tenant.id, FineTariffUpdate(account_id=tenant_account.public_id, amount_late=Decimal("2"), amount_absent=Decimal("4"))
    )
    template = make_template(db, tenant.id)
    return tenant, tenant_account, template_account, template


def _attendance_values(db, tenant_id: int, template_id: int) -> dict:
    protocol = make_protocol(db, tenant_id, template_id, protocol_number=f"P-{template_id}")
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, {"fines_enabled": True, "attendance_entries": []}, element_type_code="attendance")
    config = ProtocolElementService().list_protocol_elements(db, protocol.id)[0].blocks[0].configuration_snapshot_json
    return {key: config[key] for key in ("fine_account_id", "fine_amount_late", "fine_amount_absent")}


def _own(account, late="1.5", absent="7") -> TemplateFineTariffUpdate:
    return TemplateFineTariffUpdate(override=True, account_id=account.public_id, amount_late=Decimal(late), amount_absent=Decimal(absent))


def test_template_without_own_tariff_uses_the_tenant_tariff(db):
    tenant, tenant_account, _template_account, template = _setup(db)

    read = fine_tariff_service.read_template_tariff(db, template)

    assert read.override is False
    assert read.tenant_tariff.account_id == tenant_account.public_id
    assert _attendance_values(db, tenant.id, template.id) == {
        "fine_account_id": str(tenant_account.public_id), "fine_amount_late": 2.0, "fine_amount_absent": 4.0,
    }


def test_own_template_tariff_applies_live_to_its_protocols_only(db):
    tenant, tenant_account, template_account, template = _setup(db)
    other_template = make_template(db, tenant.id, name="Andere")
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-live")
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, {"fines_enabled": True, "attendance_entries": []}, element_type_code="attendance")

    fine_tariff_service.update_template_tariff(db, template, _own(template_account))

    # Bereits bestehendes Protokoll übernimmt den neuen Tarif sofort.
    config = ProtocolElementService().list_protocol_elements(db, protocol.id)[0].blocks[0].configuration_snapshot_json
    assert (config["fine_account_id"], config["fine_amount_late"], config["fine_amount_absent"]) == (str(template_account.public_id), 1.5, 7.0)
    assert _attendance_values(db, tenant.id, other_template.id)["fine_account_id"] == str(tenant_account.public_id)


def test_switching_back_to_the_tenant_tariff_clears_the_own_values(db):
    tenant, tenant_account, template_account, template = _setup(db)
    fine_tariff_service.update_template_tariff(db, template, _own(template_account))

    read = fine_tariff_service.update_template_tariff(db, template, TemplateFineTariffUpdate(override=False))

    assert (read.override, read.account_id, read.amount_late, read.amount_absent) == (False, None, Decimal("0"), Decimal("0"))
    assert _attendance_values(db, tenant.id, template.id)["fine_amount_late"] == 2.0


def test_account_of_another_tenant_is_rejected(db):
    _tenant, _tenant_account, _template_account, template = _setup(db)
    foreign_account = make_finance_account(db, make_tenant(db).id)

    with pytest.raises(ValueError):
        fine_tariff_service.update_template_tariff(db, template, _own(foreign_account))


def test_trigger_blocks_a_foreign_account_written_directly(db):
    _tenant, _tenant_account, _template_account, template = _setup(db)
    foreign_account = make_finance_account(db, make_tenant(db).id)

    # Eigener SQL-Savepoint statt db.begin_nested(): _setup committet (Tarif), danach kollidiert
    # ein verschachtelter ORM-Savepoint mit dem Neustart-Hook aus conftest.
    connection = db.connection()
    connection.exec_driver_sql("SAVEPOINT foreign_account")
    with pytest.raises(IntegrityError, match="gehört nicht zum Mandanten"):
        connection.execute(text("UPDATE template SET fine_account_id = :account WHERE id = :id"), {"account": foreign_account.id, "id": template.id})
    connection.exec_driver_sql("ROLLBACK TO SAVEPOINT foreign_account")


def test_routes_need_admin_and_finance_and_hide_foreign_templates(db):
    tenant, _tenant_account, template_account, template = _setup(db)
    admin = make_current_user(tenant.id, role="admin", features=FINANCE)
    payload = _own(template_account)

    saved = template_routes.update_template_fine_tariff(template.public_id, payload, db=db, user=admin)
    assert saved.override is True
    assert template_routes.get_template_fine_tariff(template.public_id, db=db, user=admin).amount_absent == Decimal("7.00")

    for user in (
        make_current_user(tenant.id, role="writer", features=FINANCE),
        make_current_user(tenant.id, role="admin", features=frozenset()),
    ):
        with pytest.raises(HTTPException) as denied:
            template_routes.update_template_fine_tariff(template.public_id, payload, db=db, user=user)
        assert denied.value.status_code == 403

    other_admin = make_current_user(make_tenant(db).id, role="admin", features=FINANCE)
    with pytest.raises(HTTPException) as hidden:
        template_routes.get_template_fine_tariff(template.public_id, db=db, user=other_admin)
    assert hidden.value.status_code == 404


def test_duplicate_clone_and_export_keep_the_own_tariff(db):
    tenant, _tenant_account, template_account, template = _setup(db)
    fine_tariff_service.update_template_tariff(db, template, _own(template_account))

    duplicate = TemplateService().duplicate_template(db, template.id, new_name="Kopie", created_by=None)
    assert (duplicate.fine_tariff_override, duplicate.fine_account_id) == (True, template_account.id)

    for new_tenant in (TenantCloneService().clone_full(db, tenant.id, "Klon"), _export_import(db, tenant.id)[0]):
        copied = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id, Template.name == template.name))
        assert copied.fine_tariff_override is True
        assert copied.fine_account_id is not None and copied.fine_account_id != template_account.id
        assert (copied.fine_amount_late, copied.fine_amount_absent) == (Decimal("1.50"), Decimal("7.00"))
