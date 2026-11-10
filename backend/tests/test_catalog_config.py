"""Tests for the Preiskatalog JSON export/import (catalog_config_service): merge vs. overwrite,
the "in use -> only deactivate" rule, validation errors and the preview fingerprint. Features
reuse the seeded catalog rows ('finance', 'abgabebox'), plans/packages are test-local."""
from __future__ import annotations

import json

import pytest

from app.models.entities import Feature, Plan, PlanFeature, StoragePackage, TenantStoragePackage
from app.schemas.admin import AdminPlanWrite, AdminStoragePackageWrite, AdminTenantSubscriptionUpdate
from app.services.admin_tenant_service import AdminTenantService
from app.services.catalog_config_service import BYTES_PER_GB, CatalogChangedError, CatalogConfigService

from tests.factories import make_tenant


@pytest.fixture
def service() -> CatalogConfigService:
    return CatalogConfigService()


def _seed(db) -> None:
    admin_service = AdminTenantService()
    admin_service.upsert_plan(
        db,
        "cat_basic",
        AdminPlanWrite(
            name="Cat Basic",
            price_monthly_rp=1990,
            price_yearly_rp=19900,
            included_user_limit=5,
            included_storage_bytes=5 * BYTES_PER_GB,
            feature_codes=["finance"],
        ),
    )
    admin_service.upsert_storage_package(
        db, "cat_pkg_10", AdminStoragePackageWrite(name="Cat 10 GB", bytes=10 * BYTES_PER_GB, price_yearly_rp=6000)
    )


def _changes_by_code(preview) -> dict[str, object]:
    return {change.code: change for change in preview.changes}


def test_export_contains_guide_ids_and_file_units(db, service):
    _seed(db)
    exported = service.export_config(db)

    assert exported["schema_version"] == 1
    assert "_anleitung" in exported
    assert "finance" in exported["_anleitung"]["gueltige_feature_codes"]
    plan = next(p for p in exported["plans"] if p["code"] == "cat_basic")
    assert plan["price_monthly_chf"] == 19.9
    assert plan["price_yearly_chf"] == 199
    assert plan["included_storage_gb"] == 5
    assert plan["feature_codes"] == ["finance"]
    package = next(p for p in exported["storage_packages"] if p["code"] == "cat_pkg_10")
    assert package["storage_gb"] == 10
    assert package["is_bookable"] is True
    # Muss als JSON serialisierbar sein (Decimal o.ä. würde hier scheitern).
    json.dumps(exported)


def test_roundtrip_of_unchanged_export_has_no_changes(db, service):
    _seed(db)
    # Krumme Byte-Zahl, die in GB gerundet exportiert wird, darf keine Scheinänderung erzeugen.
    db.get(StoragePackage, "cat_pkg_10").bytes = 10 * BYTES_PER_GB + 123
    db.commit()
    exported = json.loads(json.dumps(service.export_config(db)))

    for overwrite in (False, True):
        preview = service.preview(db, exported, overwrite=overwrite)
        assert preview.errors == []
        assert preview.changes == []


def test_merge_updates_only_given_fields_and_creates_new_entries(db, service):
    _seed(db)
    config = {
        "schema_version": 1,
        "plans": [{"code": "cat_basic", "price_yearly_chf": 249.5}],
        "storage_packages": [{"code": "cat_pkg_50", "name": "Cat 50 GB", "storage_gb": 50, "price_yearly_chf": 120}],
    }
    preview = service.preview(db, config, overwrite=False)
    assert preview.errors == []
    changes = _changes_by_code(preview)
    assert changes["cat_basic"].action == "update"
    assert [(c.field, c.old, c.new) for c in changes["cat_basic"].changes] == [("price_yearly_chf", 199, 249.5)]
    assert changes["cat_pkg_50"].action == "create"
    # Bestehendes Paket fehlt in der Datei -> im Ergänzen-Modus unverändert.
    assert "cat_pkg_10" not in changes

    service.apply(db, config, overwrite=False, base_fingerprint=preview.base_fingerprint)
    plan = db.get(Plan, "cat_basic")
    assert plan.price_yearly_rp == 24950
    assert plan.price_monthly_rp == 1990
    assert plan.included_user_limit == 5
    assert db.get(StoragePackage, "cat_pkg_50").bytes == 50 * BYTES_PER_GB
    assert db.get(StoragePackage, "cat_pkg_10") is not None


def test_overwrite_deletes_unused_and_deactivates_assigned_entries(db, service):
    _seed(db)
    admin_service = AdminTenantService()
    admin_service.upsert_storage_package(db, "cat_pkg_unused", AdminStoragePackageWrite(name="Unused", bytes=BYTES_PER_GB))
    admin_service.upsert_plan(db, "cat_unused_plan", AdminPlanWrite(name="Unused Plan"))
    tenant = make_tenant(db)
    admin_service.update_tenant_subscription(db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="cat_basic"), admin_id=None)
    db.add(TenantStoragePackage(tenant_id=tenant.id, package_code="cat_pkg_10", quantity=1))
    db.commit()

    exported = service.export_config(db)
    config = {
        "schema_version": 1,
        "plans": [p for p in exported["plans"] if p["code"] not in ("cat_basic", "cat_unused_plan")],
        "storage_packages": [p for p in exported["storage_packages"] if p["code"] not in ("cat_pkg_10", "cat_pkg_unused")],
    }
    preview = service.preview(db, config, overwrite=True)
    assert preview.errors == []
    changes = _changes_by_code(preview)
    assert changes["cat_basic"].action == "deactivate"
    assert changes["cat_basic"].tenant_count == 1
    assert changes["cat_pkg_10"].action == "deactivate"
    assert changes["cat_unused_plan"].action == "delete"
    assert changes["cat_pkg_unused"].action == "delete"

    service.apply(db, config, overwrite=True)
    db.expire_all()
    assert db.get(Plan, "cat_basic").is_bookable is False
    assert db.get(StoragePackage, "cat_pkg_10").is_bookable is False
    assert db.get(Plan, "cat_unused_plan") is None
    assert db.get(StoragePackage, "cat_pkg_unused") is None
    # Zuweisung bleibt bestehen.
    assert db.query(TenantStoragePackage).filter_by(tenant_id=tenant.id, package_code="cat_pkg_10").count() == 1

    rebooking = admin_service.list_tenants(db, needs_rebooking=True)
    assert tenant.public_id in {item.id for item in rebooking.items}


def test_overwrite_replaces_entry_completely(db, service):
    _seed(db)
    config = {"schema_version": 1, "plans": [{"code": "cat_basic", "name": "Cat Basic"}]}
    service.apply(db, config, overwrite=True)
    db.expire_all()
    plan = db.get(Plan, "cat_basic")
    assert plan.price_monthly_rp is None
    assert plan.included_user_limit is None
    assert db.query(PlanFeature).filter_by(plan_code="cat_basic").count() == 0
    # Abschnitt storage_packages fehlt -> unverändert, auch im Überschreiben-Modus.
    assert db.get(StoragePackage, "cat_pkg_10") is not None


def test_storage_change_recomputes_tenant_quota(db, service):
    _seed(db)
    admin_service = AdminTenantService()
    tenant = make_tenant(db)
    admin_service.update_tenant_subscription(db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="cat_basic"), admin_id=None)
    db.add(TenantStoragePackage(tenant_id=tenant.id, package_code="cat_pkg_10", quantity=2))
    db.commit()

    service.apply(
        db,
        {
            "schema_version": 1,
            "plans": [{"code": "cat_basic", "included_storage_gb": 8}],
            "storage_packages": [{"code": "cat_pkg_10", "storage_gb": 20}],
        },
        overwrite=False,
    )
    db.refresh(tenant)
    assert tenant.storage_quota_bytes == 8 * BYTES_PER_GB + 2 * 20 * BYTES_PER_GB


def test_featured_plan_in_file_resets_others(db, service):
    _seed(db)
    AdminTenantService().upsert_plan(db, "cat_other", AdminPlanWrite(name="Other", is_featured=True))
    preview = service.preview(db, {"schema_version": 1, "plans": [{"code": "cat_basic", "is_featured": True}]}, overwrite=False)
    assert preview.errors == []
    other = _changes_by_code(preview)["cat_other"]
    assert [(c.field, c.new) for c in other.changes] == [("is_featured", False)]


def test_validation_errors_are_collected_and_block_apply(db, service):
    _seed(db)
    config = {
        "schema_version": 1,
        "features": [{"code": "does_not_exist", "name": "X"}],
        "plans": [
            {"code": "cat_basic", "price_montly_chf": 10},
            {"code": "cat_new"},
            {"code": "cat_bad", "name": "Bad", "price_yearly_chf": 10.005, "feature_codes": ["nope"]},
            {"code": "Has Space", "name": "Y"},
        ],
        "storage_packages": [{"code": "cat_pkg_10", "storage_gb": 0}],
        "unknown_section": [],
    }
    preview = service.preview(db, config, overwrite=False)
    text = "\n".join(preview.errors)
    assert "unbekanntes Modul" in text
    assert "price_montly_chf" in text
    assert "Plan 'cat_new': name fehlt" in text
    assert "zwei Nachkommastellen" in text
    assert "unbekannte feature_codes nope" in text
    assert "Has Space" in text
    assert "storage_gb" in text
    assert "unknown_section" in text

    with pytest.raises(ValueError):
        service.apply(db, config, overwrite=False)
    assert db.get(Plan, "cat_new") is None


def test_features_can_be_updated_but_not_deleted(db, service):
    original = db.get(Feature, "finance").name
    preview = service.preview(db, {"schema_version": 1, "features": [{"code": "finance", "name": "Finanzen Neu"}]}, overwrite=True)
    assert preview.errors == []
    assert {c.code for c in preview.changes} == {"finance"}
    service.apply(db, {"schema_version": 1, "features": [{"code": "finance", "name": "Finanzen Neu"}]}, overwrite=False)
    assert db.get(Feature, "finance").name == "Finanzen Neu"
    assert original != "Finanzen Neu"


def test_apply_rejects_stale_fingerprint(db, service):
    _seed(db)
    config = {"schema_version": 1, "plans": [{"code": "cat_basic", "price_yearly_chf": 300}]}
    preview = service.preview(db, config, overwrite=False)
    AdminTenantService().upsert_storage_package(db, "cat_pkg_10", AdminStoragePackageWrite(name="Changed", bytes=BYTES_PER_GB))
    with pytest.raises(CatalogChangedError):
        service.apply(db, config, overwrite=False, base_fingerprint=preview.base_fingerprint)
