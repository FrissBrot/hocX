"""Tests for Speicher-Zusatzpakete (0087_storage_packages): the catalog CRUD, the tenant
assignment (full-replace incl. quantity) and recompute_effective_storage_quota - the piece that
keeps Tenant.storage_quota_bytes in sync with plan + assigned packages, unless an admin has set
a manual override (storage_quota_manual_override)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from app.schemas.admin import AdminPlanWrite, AdminStoragePackageWrite, AdminTenantStoragePackageItem, AdminTenantSubscriptionUpdate
from app.services.admin_tenant_service import AdminTenantService
from app.services.storage_service import StorageService

from tests.factories import make_tenant
from tests.test_admin_plan_pricing import make_platform_admin

_MIGRATION_0088_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/0088_remove_manual_storage_quota.py"
)


def _load_migration_0088_reset_sql() -> str:
    """The migration file's module name starts with a digit, so it can't be `import`ed normally -
    load it by path instead, the same way Alembic itself resolves version files, to get the exact
    SQL text 0088's upgrade() runs (RESET_GRANTED_OVERRIDES_SQL) without duplicating it here."""
    spec = importlib.util.spec_from_file_location("migration_0088", _MIGRATION_0088_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RESET_GRANTED_OVERRIDES_SQL


def test_storage_package_write_rejects_negative_bytes_and_prices():
    """Hardening fix (audit 2026-09-24): AdminStoragePackageWrite had no lower bound on
    bytes/price fields, unlike sibling schemas (AdminTenantStorageQuotaUpdate.quota_mb,
    AdminTenantSubscriptionUpdate.discount_percent) - a negative package size could drive
    recompute_effective_storage_quota's sum negative. Only reachable by a platform-admin-owner,
    but should fail validation the same way as everywhere else."""
    with pytest.raises(ValidationError):
        AdminStoragePackageWrite(name="Bad Package", bytes=-1, price_monthly_rp=None, price_yearly_rp=None)
    with pytest.raises(ValidationError):
        AdminStoragePackageWrite(name="Bad Package", bytes=1000, price_monthly_rp=-500, price_yearly_rp=None)


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


def test_clearing_manual_quota_falls_back_to_plan_and_package_total(db):
    """Emptying the admin panel's manual-quota field (quota_mb=None) must remove the override
    and restore the automatically computed plan+package total, matching its "leer =
    automatische Berechnung" label - not leave the tenant stuck on an explicit unlimited
    override, which is what set_quota used to do unconditionally."""
    admin_service = AdminTenantService()
    storage_service = StorageService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    admin_service.upsert_plan(
        db,
        "test_plan_storage_d",
        AdminPlanWrite(name="Plan D", price_monthly_rp=None, price_yearly_rp=None, included_user_limit=None, included_storage_bytes=2000, sort_order=0, feature_codes=[]),
    )
    admin_service.update_tenant_subscription(
        db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="test_plan_storage_d", billing_cycle="monthly", user_limit_override=None), admin_id=admin.id
    )

    overridden = storage_service.set_quota(db, tenant.id, 999_999)
    assert overridden.storage_quota_manual_override is True

    cleared = storage_service.set_quota(db, tenant.id, None)
    assert cleared.storage_quota_manual_override is False

    admin_service.recompute_effective_storage_quota(db, tenant.id)
    result = admin_service.get_tenant(db, tenant.id)
    assert result is not None
    assert result.storage_quota_bytes == 2000
    assert result.storage_quota_manual_override is False


def test_migration_0088_resets_only_overrides_that_were_grants(db):
    """Security fix (audit 2026-09-24): migration 0088's blanket reset used to widen ANY manual
    override back to the auto-computed plan+package total, even one an admin had set BELOW that
    total as a deliberate restriction (e.g. a billing/abuse measure) - silently granting that
    tenant more storage at deploy time. It must now only reset an override that was a grant
    (current value >= the computed total)."""
    admin_service = AdminTenantService()
    storage_service = StorageService()
    admin = make_platform_admin(db)
    granted_tenant = make_tenant(db, name="Granted Override Tenant")
    restricted_tenant = make_tenant(db, name="Restricted Override Tenant")

    admin_service.upsert_plan(
        db,
        "test_plan_storage_migration_0088",
        AdminPlanWrite(
            name="Plan 0088", price_monthly_rp=None, price_yearly_rp=None,
            included_user_limit=None, included_storage_bytes=1000, sort_order=0, feature_codes=[],
        ),
    )
    for tenant in (granted_tenant, restricted_tenant):
        admin_service.update_tenant_subscription(
            db, tenant.id,
            AdminTenantSubscriptionUpdate(plan_code="test_plan_storage_migration_0088", billing_cycle="monthly", user_limit_override=None),
            admin_id=admin.id,
        )

    # Granted: admin raised this tenant's quota above the plan's 1000 bytes (e.g. an enterprise
    # deal) - the migration should reset this to the auto-computed total.
    storage_service.set_quota(db, granted_tenant.id, 999_999)
    # Restricted: admin capped this tenant BELOW the plan's 1000 bytes (e.g. a billing dispute) -
    # the migration must leave this alone.
    storage_service.set_quota(db, restricted_tenant.id, 100)
    db.flush()

    db.execute(sa.text(_load_migration_0088_reset_sql()))

    reset_result = admin_service.get_tenant(db, granted_tenant.id)
    assert reset_result is not None
    assert reset_result.storage_quota_manual_override is False
    assert reset_result.storage_quota_bytes == 1000

    preserved_result = admin_service.get_tenant(db, restricted_tenant.id)
    assert preserved_result is not None
    assert preserved_result.storage_quota_manual_override is True
    assert preserved_result.storage_quota_bytes == 100


def test_migration_0088_preserves_restrictive_override_when_plan_would_be_unlimited(db):
    """A plan+packages total of "unbegrenzt" (None) means any existing finite manual override was
    necessarily a deliberate restriction, never a grant - the migration must not widen it to
    unlimited."""
    admin_service = AdminTenantService()
    storage_service = StorageService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    admin_service.upsert_plan(
        db,
        "test_plan_storage_migration_0088_unlimited",
        AdminPlanWrite(
            name="Plan 0088 Unlimited", price_monthly_rp=None, price_yearly_rp=None,
            included_user_limit=None, included_storage_bytes=None, sort_order=0, feature_codes=[],
        ),
    )
    admin_service.update_tenant_subscription(
        db, tenant.id,
        AdminTenantSubscriptionUpdate(plan_code="test_plan_storage_migration_0088_unlimited", billing_cycle="monthly", user_limit_override=None),
        admin_id=admin.id,
    )
    storage_service.set_quota(db, tenant.id, 50_000)
    db.flush()

    db.execute(sa.text(_load_migration_0088_reset_sql()))

    result = admin_service.get_tenant(db, tenant.id)
    assert result is not None
    assert result.storage_quota_manual_override is True
    assert result.storage_quota_bytes == 50_000


def test_create_storage_package_generates_unique_code_from_name(db):
    """The admin portal no longer asks for a code - create_storage_package derives it from the
    name and appends a suffix instead of overwriting an existing package with the same name."""
    service = AdminTenantService()
    payload = AdminStoragePackageWrite(name="Zusatz 50 GB (Ü)", bytes=50, price_monthly_rp=None, price_yearly_rp=None)
    first = service.create_storage_package(db, payload)
    second = service.create_storage_package(db, payload)

    assert first.code == "zusatz_50_gb_u"
    assert second.code == "zusatz_50_gb_u_2"
    codes = [p.code for p in service.list_storage_packages(db)]
    assert first.code in codes and second.code in codes
