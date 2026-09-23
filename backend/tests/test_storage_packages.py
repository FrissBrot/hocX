"""Tests for Speicher-Zusatzpakete (0087_storage_packages): the catalog CRUD, the tenant
assignment (full-replace incl. quantity) and recompute_effective_storage_quota - the piece that
keeps Tenant.storage_quota_bytes in sync with plan + assigned packages, unless an admin has set
a manual override (storage_quota_manual_override)."""
from __future__ import annotations

from app.schemas.admin import AdminPlanWrite, AdminStoragePackageWrite, AdminTenantStoragePackageItem, AdminTenantSubscriptionUpdate
from app.services.admin_tenant_service import AdminTenantService
from app.services.storage_service import StorageService

from tests.factories import make_tenant
from tests.test_admin_plan_pricing import make_platform_admin


def test_upsert_storage_package_creates_and_updates(db):
    service = AdminTenantService()
    created = service.upsert_storage_package(
        db,
        "extra_10gb",
        AdminStoragePackageWrite(name="10 GB Zusatzpaket", bytes=10_000_000_000, price_monthly_rp=500, price_yearly_rp=5000, sort_order=1),
    )
    assert created.code == "extra_10gb"
    assert created.bytes == 10_000_000_000

    updated = service.upsert_storage_package(
        db,
        "extra_10gb",
        AdminStoragePackageWrite(name="10 GB Paket (neu)", bytes=10_000_000_000, price_monthly_rp=600, price_yearly_rp=None, sort_order=2),
    )
    assert updated.name == "10 GB Paket (neu)"
    assert updated.price_monthly_rp == 600
    assert updated.price_yearly_rp is None

    packages_by_code = {p.code: p for p in service.list_storage_packages(db)}
    assert packages_by_code["extra_10gb"].name == "10 GB Paket (neu)"


def test_recompute_effective_storage_quota_combines_plan_and_packages(db):
    service = AdminTenantService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    service.upsert_plan(
        db,
        "test_plan_storage_a",
        AdminPlanWrite(name="Plan A", price_monthly_rp=None, price_yearly_rp=None, included_user_limit=None, included_storage_bytes=1000, sort_order=0, feature_codes=[]),
    )
    service.upsert_storage_package(db, "pkg_a", AdminStoragePackageWrite(name="Paket A", bytes=500, price_monthly_rp=None, price_yearly_rp=None, sort_order=0))

    service.update_tenant_subscription(
        db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="test_plan_storage_a", billing_cycle="monthly", user_limit_override=None), admin_id=admin.id
    )
    result = service.update_tenant_storage_packages(
        db, tenant.id, [AdminTenantStoragePackageItem(package_code="pkg_a", quantity=2)], admin_id=admin.id
    )
    assert result is not None
    # 1000 (Plan) + 500 * 2 (Paket) = 2000
    assert result.storage_quota_bytes == 2000
    assert result.effective_storage_quota_bytes == 2000
    assert result.plan_storage_bytes == 1000
    assert result.package_storage_bytes == 1000
    assert [p.package_code for p in result.assigned_storage_packages] == ["pkg_a"]
    assert result.assigned_storage_packages[0].quantity == 2

    # Menge aendern statt neu zuweisen - full-replace muss ein bestehendes Paket updaten,
    # nicht doppelt anlegen (UNIQUE(tenant_id, package_code)).
    result_updated_quantity = service.update_tenant_storage_packages(
        db, tenant.id, [AdminTenantStoragePackageItem(package_code="pkg_a", quantity=3)], admin_id=admin.id
    )
    assert result_updated_quantity is not None
    assert result_updated_quantity.storage_quota_bytes == 1000 + 500 * 3
    assert len(result_updated_quantity.assigned_storage_packages) == 1

    # Paket entfernen (leere Liste) - Kontingent faellt auf den reinen Plan-Anteil zurueck.
    result_removed = service.update_tenant_storage_packages(db, tenant.id, [], admin_id=admin.id)
    assert result_removed is not None
    assert result_removed.storage_quota_bytes == 1000
    assert result_removed.package_storage_bytes == 0
    assert result_removed.assigned_storage_packages == []


def test_recompute_effective_storage_quota_stays_unlimited_without_plan_limit_or_packages(db):
    """A plan with no storage limit (included_storage_bytes=None, e.g. 'legacy') and no
    packages must leave storage_quota_bytes at None (unlimited) - not fall back to 0, which
    upload_pipeline.py's _enforce_tenant_storage_quota would treat as "no uploads allowed"."""
    service = AdminTenantService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    service.upsert_plan(
        db,
        "test_plan_storage_b",
        AdminPlanWrite(name="Plan B", price_monthly_rp=None, price_yearly_rp=None, included_user_limit=None, included_storage_bytes=None, sort_order=0, feature_codes=[]),
    )
    result = service.update_tenant_subscription(
        db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="test_plan_storage_b", billing_cycle="monthly", user_limit_override=None), admin_id=admin.id
    )
    assert result is not None
    assert result.storage_quota_bytes is None
    assert result.effective_storage_quota_bytes is None


def test_manual_quota_override_survives_plan_and_package_changes(db):
    admin_service = AdminTenantService()
    storage_service = StorageService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    service = admin_service
    service.upsert_plan(
        db,
        "test_plan_storage_c",
        AdminPlanWrite(name="Plan C", price_monthly_rp=None, price_yearly_rp=None, included_user_limit=None, included_storage_bytes=1000, sort_order=0, feature_codes=[]),
    )
    service.upsert_storage_package(db, "pkg_c", AdminStoragePackageWrite(name="Paket C", bytes=500, price_monthly_rp=None, price_yearly_rp=None, sort_order=0))

    # Admin setzt manuell eine individuelle Sondergrenze (z.B. Enterprise-Vereinbarung).
    storage_service.set_quota(db, tenant.id, 999_999)

    result = service.update_tenant_subscription(
        db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="test_plan_storage_c", billing_cycle="monthly", user_limit_override=None), admin_id=admin.id
    )
    assert result is not None
    assert result.storage_quota_manual_override is True
    assert result.storage_quota_bytes == 999_999

    result_after_package = service.update_tenant_storage_packages(
        db, tenant.id, [AdminTenantStoragePackageItem(package_code="pkg_c", quantity=5)], admin_id=admin.id
    )
    assert result_after_package is not None
    assert result_after_package.storage_quota_bytes == 999_999
    assert result_after_package.storage_quota_manual_override is True
