"""Tests for the Preiskatalog (0085_plan_pricing): plan/feature CRUD via AdminTenantService
and the tenant-subscription baseline/cost logic. 'finance'/'abgabebox' already exist as
seeded catalog rows (migrations 0084/0085), so these tests reuse them instead of creating
throwaway features - only the plan itself is test-local."""
from __future__ import annotations

from app.core.security import CurrentUser
from app.models.entities import Feature, PlatformAdmin, TenantFeature
from app.schemas.admin import AdminFeatureUpdate, AdminPlanWrite, AdminTenantSubscriptionUpdate
from app.services.admin_tenant_service import AdminTenantService
from app.services.tenant_service import TenantService

from tests.factories import make_tenant


def make_platform_admin(db, email="pricing-admin@example.com") -> PlatformAdmin:
    admin = PlatformAdmin(email=email, password_hash="x", display_name="Pricing Admin")
    db.add(admin)
    db.flush()
    return admin


def test_upsert_plan_creates_and_updates_with_feature_bundle(db):
    service = AdminTenantService()
    created = service.upsert_plan(
        db,
        "test_plan_x",
        AdminPlanWrite(
            name="Test Plan X",
            price_monthly_rp=1000,
            price_yearly_rp=10000,
            included_user_limit=5,
            included_storage_bytes=1_000_000,
            sort_order=99,
            feature_codes=["finance"],
        ),
    )
    assert created.code == "test_plan_x"
    assert created.feature_codes == ["finance"]

    updated = service.upsert_plan(
        db,
        "test_plan_x",
        AdminPlanWrite(
            name="Test Plan X Renamed",
            price_monthly_rp=2000,
            price_yearly_rp=None,
            included_user_limit=None,
            included_storage_bytes=None,
            sort_order=1,
            feature_codes=["finance", "abgabebox"],
        ),
    )
    assert updated.name == "Test Plan X Renamed"
    assert updated.price_yearly_rp is None
    assert updated.included_user_limit is None
    assert sorted(updated.feature_codes) == ["abgabebox", "finance"]

    plans_by_code = {p.code: p for p in service.list_plans(db)}
    assert plans_by_code["test_plan_x"].name == "Test Plan X Renamed"


def test_update_feature_sets_standalone_price(db):
    service = AdminTenantService()
    original = db.get(Feature, "finance")
    try:
        updated = service.update_feature(
            db, "finance", AdminFeatureUpdate(name=original.name, description=original.description, standalone_price_monthly_rp=500)
        )
        assert updated is not None
        assert updated.standalone_price_monthly_rp == 500
    finally:
        # 'finance' ist ein geteiltes Katalog-Feature (seed data, nicht test-lokal) - Preis
        # wieder zuruecksetzen, damit dieser Test andere Tests/Runs nicht beeinflusst, obwohl
        # die db-Fixture ohnehin am Ende zurueckrollt (Verteidigung falls das mal nicht gilt).
        service.update_feature(
            db, "finance", AdminFeatureUpdate(name=original.name, description=original.description, standalone_price_monthly_rp=None)
        )


def test_update_tenant_subscription_baselines_plan_features_without_removing_extras(db):
    admin_service = AdminTenantService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    admin_service.upsert_plan(
        db,
        "test_plan_y",
        AdminPlanWrite(
            name="Test Plan Y",
            price_monthly_rp=None,
            price_yearly_rp=None,
            included_user_limit=3,
            included_storage_bytes=None,
            sort_order=0,
            feature_codes=["finance"],
        ),
    )
    # Ein Zusatzmodul, das nicht Teil des Plans ist - darf durch den Plan-Wechsel nicht
    # verschwinden (siehe Kommentar an Tenant.plan_code in entities.py).
    db.add(TenantFeature(tenant_id=tenant.id, feature_code="abgabebox"))
    db.flush()

    result = admin_service.update_tenant_subscription(
        db,
        tenant.id,
        AdminTenantSubscriptionUpdate(plan_code="test_plan_y", billing_cycle="yearly", user_limit_override=None),
        admin_id=admin.id,
    )
    assert result is not None
    assert result.plan_code == "test_plan_y"
    assert result.billing_cycle == "yearly"
    assert result.effective_user_limit == 3
    assert sorted(result.enabled_features) == ["abgabebox", "finance"]

    # Override gewinnt gegen das Plan-Limit.
    result_override = admin_service.update_tenant_subscription(
        db,
        tenant.id,
        AdminTenantSubscriptionUpdate(plan_code="test_plan_y", billing_cycle="monthly", user_limit_override=10),
        admin_id=admin.id,
    )
    assert result_override is not None
    assert result_override.effective_user_limit == 10


def test_tenant_subscription_view_computes_estimated_cost_including_extra_feature(db):
    admin_service = AdminTenantService()
    tenant_service = TenantService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    admin_service.upsert_plan(
        db,
        "test_plan_z",
        AdminPlanWrite(
            name="Test Plan Z",
            price_monthly_rp=1000,
            price_yearly_rp=12000,
            included_user_limit=None,
            included_storage_bytes=None,
            sort_order=0,
            feature_codes=["finance"],
        ),
    )
    admin_service.update_feature(
        db, "abgabebox", AdminFeatureUpdate(name="Abgabebox", description=None, standalone_price_monthly_rp=200)
    )
    try:
        admin_service.update_tenant_subscription(
            db,
            tenant.id,
            AdminTenantSubscriptionUpdate(plan_code="test_plan_z", billing_cycle="monthly", user_limit_override=None),
            admin_id=admin.id,
        )
        db.add(TenantFeature(tenant_id=tenant.id, feature_code="abgabebox"))
        db.flush()

        actor = CurrentUser(
            user_id=1,
            user_public_id=tenant.public_id,
            first_name="Test",
            last_name="Admin",
            display_name="Test Admin",
            email="test@example.com",
            preferred_language="de",
            is_participant_account=False,
            current_tenant_id=tenant.id,
            current_tenant_public_id=tenant.public_id,
            current_tenant_name=tenant.name,
            current_tenant_profile_image_path=None,
            current_role="admin",
            current_tenant_features=frozenset({"finance", "abgabebox"}),
        )
        subscription = tenant_service.get_subscription(db, tenant.id, actor)
        assert subscription is not None
        assert subscription.plan_price_monthly_rp == 1000
        # 1000 (Plan) + 200 (Abgabebox, nicht im Plan enthalten) = 1200
        assert subscription.estimated_monthly_cost_rp == 1200
        feature_by_code = {f.code: f for f in subscription.features}
        assert feature_by_code["finance"].included_in_plan is True
        assert feature_by_code["abgabebox"].included_in_plan is False
        assert feature_by_code["abgabebox"].standalone_price_monthly_rp == 200
    finally:
        admin_service.update_feature(db, "abgabebox", AdminFeatureUpdate(name="Abgabebox", description=None, standalone_price_monthly_rp=None))
