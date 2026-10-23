"""Priorität bei Überlast je Abo (Migration 0151, app/core/db_admission.py): Stufe am Plan im
Adminportal und Preiskatalog, Laden der Stufen je Nutzer, Protokoll der Abweisungen und ihre
Anzeige in /admin/system."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.db_admission import PRIORITY_HIGH, PRIORITY_LOW, PRIORITY_NORMAL, PriorityDirectory, RejectionLog
from app.core.security import create_session_token
from app.main import _session_user_id
from app.models.entities import Plan
from app.schemas.admin import AdminPlanWrite, AdminTenantSubscriptionUpdate
from app.services import system_alert_service, system_health_service
from app.services.admin_tenant_service import AdminTenantService
from app.services.catalog_config_service import CatalogConfigService

from tests.factories import make_app_user, make_tenant


def _tenant_with_plan(db, plan_code: str, priority: int, name: str):
    service = AdminTenantService()
    service.upsert_plan(db, plan_code, AdminPlanWrite(name=f"Plan {plan_code}", load_priority=priority))
    tenant = make_tenant(db, name)
    service.update_tenant_subscription(db, tenant.id, AdminTenantSubscriptionUpdate(plan_code=plan_code), admin_id=None)
    return tenant


def test_plan_priority_is_stored_listed_and_defaults_to_normal(db):
    service = AdminTenantService()
    service.upsert_plan(db, "ovl_free", AdminPlanWrite(name="Ovl Free", load_priority=PRIORITY_LOW))
    service.upsert_plan(db, "ovl_default", AdminPlanWrite(name="Ovl Default"))

    plans = {plan.code: plan for plan in service.list_plans(db)}
    assert plans["ovl_free"].load_priority == PRIORITY_LOW
    assert plans["ovl_default"].load_priority == PRIORITY_NORMAL
    # Bestehende Pläne starten nach der Migration auf "normal".
    assert db.get(Plan, "legacy").load_priority == PRIORITY_NORMAL


def test_plan_priority_rejects_unknown_levels():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdminPlanWrite(name="Bad", load_priority=3)


def test_catalog_file_exports_and_imports_the_priority(db):
    service = CatalogConfigService()
    AdminTenantService().upsert_plan(db, "ovl_cat", AdminPlanWrite(name="Ovl Cat"))
    exported = service.export_config(db)
    assert next(p for p in exported["plans"] if p["code"] == "ovl_cat")["load_priority"] == PRIORITY_NORMAL
    assert "load_priority" in exported["_anleitung"]["felder"]["plans"]

    config = {"schema_version": 1, "plans": [{"code": "ovl_cat", "load_priority": PRIORITY_HIGH}]}
    preview = service.preview(db, config, overwrite=False)
    assert preview.errors == []
    service.apply(db, config, overwrite=False, base_fingerprint=preview.base_fingerprint)
    assert db.get(Plan, "ovl_cat").load_priority == PRIORITY_HIGH


def test_directory_maps_each_user_to_tenant_and_plan_priority(db):
    free = _tenant_with_plan(db, "ovl_dir_free", PRIORITY_LOW, "Ovl Gratis")
    paid = _tenant_with_plan(db, "ovl_dir_paid", PRIORITY_HIGH, "Ovl Bezahlt")
    without_plan = make_tenant(db, "Ovl Ohne Plan")
    users = [make_app_user(db, f"ovl-dir-{i}@example.com", tenant_id=t.id) for i, t in enumerate((free, paid, without_plan))]

    directory = PriorityDirectory()
    directory.load(db.connection())

    assert directory.lookup(users[0].id) == (free.id, PRIORITY_LOW)
    assert directory.lookup(users[1].id) == (paid.id, PRIORITY_HIGH)
    assert directory.lookup(users[2].id) == (without_plan.id, PRIORITY_NORMAL)


def test_session_cookie_identifies_the_user_without_database():
    token = create_session_token(42)
    scope = {"headers": [(b"cookie", f"other=1; hocx_session={token}".encode())]}
    assert _session_user_id(scope) == 42
    assert _session_user_id({"headers": [(b"cookie", b"hocx_session=forged.token")]}) is None
    assert _session_user_id({"headers": []}) is None


def test_rejections_are_logged_checked_and_listed_per_tenant(db):
    db.execute(text("DELETE FROM overload_rejection"))
    free = _tenant_with_plan(db, "ovl_log_free", PRIORITY_LOW, "Ovl Verein Gratis")
    log = RejectionLog()
    for user_id in (1, 2, 2):
        log.record(user_id=user_id, tenant_id=free.id, priority=PRIORITY_LOW, pressure=0.82)
    # Ein inzwischen gelöschter Mandant darf das Schreiben der übrigen nicht verhindern.
    log.record(user_id=9, tenant_id=-1, priority=PRIORITY_NORMAL, pressure=1.1)
    RejectionLog.write(db.connection(), "backend:test:1", log.take())

    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    check = system_health_service._check_overload(db, now)
    assert check.status == "warning"
    assert check.params == {"minutes": 5, "rejected": 3, "users": 2, "tenants": 1, "pressurePercent": 82}
    assert "3 Anfragen von 2 neuen Nutzern" in system_alert_service._check_message(check)

    [entry] = system_health_service.overload_by_tenant(db, now)
    assert entry.tenant_id == str(free.public_id)
    assert entry.tenant_name == "Ovl Verein Gratis"
    assert entry.plan_name == "Plan ovl_log_free"
    assert (entry.load_priority, entry.rejected, entry.users) == (PRIORITY_LOW, 3, 2)

    # Nach dem Fenster gilt die Überlast als behoben, die Liste bleibt sieben Tage.
    later = now + timedelta(minutes=6)
    assert system_health_service._check_overload(db, later).status == "ok"
    assert len(system_health_service.overload_by_tenant(db, later)) == 1
    assert system_health_service.overload_by_tenant(db, now + timedelta(days=8)) == []


def test_overload_check_is_part_of_the_snapshot(db):
    db.execute(text("DELETE FROM overload_rejection"))
    keys = [check.key for check in system_health_service.collect_checks(db, datetime.now(timezone.utc))]
    assert "overload" in keys
