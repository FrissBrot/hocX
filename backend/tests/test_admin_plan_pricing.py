"""Tests for the Preiskatalog (0085_plan_pricing): plan/feature CRUD via AdminTenantService
and the tenant-subscription baseline/cost logic. 'finance'/'abgabebox' already exist as
seeded catalog rows (migrations 0084/0085), so these tests reuse them instead of creating
throwaway features - only the plan itself is test-local."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.security import CurrentUser
from app.models.entities import Feature, PlatformAdmin, TenantFeature
from app.schemas.admin import AdminFeatureUpdate, AdminPlanWrite, AdminTenantCreate, AdminTenantSubscriptionUpdate
from app.services.admin_tenant_service import AdminTenantService
from app.services.tenant_service import TenantService

from tests.factories import make_tenant


def make_platform_admin(db, email="pricing-admin@example.com") -> PlatformAdmin:
    admin = PlatformAdmin(email=email, password_hash="x", display_name="Pricing Admin")
    db.add(admin)
    db.flush()
    return admin


def test_plan_write_rejects_negative_price_and_limit_fields():
    """Hardening fix (audit 2026-09-24): AdminPlanWrite had no lower bound on its price/limit
    fields, unlike sibling schemas (AdminTenantStorageQuotaUpdate.quota_mb,
    AdminTenantSubscriptionUpdate.discount_percent). Only reachable by a platform-admin-owner,
    but should fail validation the same way as everywhere else instead of persisting a negative
    price/limit that then flows into cost/quota calculations."""
    with pytest.raises(ValidationError):
        AdminPlanWrite(name="Bad Plan", price_monthly_rp=-100, price_yearly_rp=None, included_user_limit=None, included_storage_bytes=None, sort_order=0, feature_codes=[])
    with pytest.raises(ValidationError):
        AdminPlanWrite(name="Bad Plan", price_monthly_rp=None, price_yearly_rp=None, included_user_limit=None, included_storage_bytes=-1, sort_order=0, feature_codes=[])


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


def _plan_write(**overrides) -> AdminPlanWrite:
    values = dict(
        name="Katalog Plan",
        price_monthly_rp=1000,
        price_yearly_rp=10000,
        included_user_limit=5,
        included_storage_bytes=1_000_000,
        sort_order=0,
        feature_codes=["finance"],
    )
    values.update(overrides)
    return AdminPlanWrite(**values)


def test_plan_description_bookable_and_tenant_count(db):
    """0089_plan_catalog_details: Beschreibung/Status werden gespeichert, tenant_count zählt die
    Mandanten des Plans, und der Plan-Filter der Mandantenliste greift vor der Paginierung."""
    service = AdminTenantService()
    admin = make_platform_admin(db)
    service.upsert_plan(db, "test_plan_cat", _plan_write(description="  Für Tests  ", is_bookable=False))
    tenant = make_tenant(db, name="Plan Count Tenant")
    make_tenant(db, name="Other Tenant")
    service.update_tenant_subscription(
        db, tenant.id, AdminTenantSubscriptionUpdate(plan_code="test_plan_cat"), admin_id=admin.id
    )

    plan = {p.code: p for p in service.list_plans(db)}["test_plan_cat"]
    assert plan.description == "Für Tests"
    assert plan.is_bookable is False
    assert plan.tenant_count == 1

    page = service.list_tenants(db, plan_code="test_plan_cat")
    assert [t.name for t in page.items] == ["Plan Count Tenant"]
    assert page.total == 1


def test_create_plan_with_explicit_code_rejects_duplicates(db):
    service = AdminTenantService()
    created = service.create_plan(db, _plan_write(name="Irgendwas", code="test_code_explicit"))
    assert created.code == "test_code_explicit"
    try:
        service.create_plan(db, _plan_write(name="Nochmal", code="test_code_explicit"))
    except ValueError:
        pass
    else:
        raise AssertionError("Doppelter Plan-Code muss abgelehnt werden")


def test_create_tenant_with_plan_slug_and_billing(db):
    service = AdminTenantService()
    admin = make_platform_admin(db)
    service.upsert_plan(db, "test_plan_new_tenant", _plan_write(feature_codes=["finance"]))

    created = service.create_tenant(
        db,
        AdminTenantCreate(name="Neuer Verein", public_slug="neuer-verein-test", plan_code="test_plan_new_tenant", billing_cycle="yearly"),
        admin_id=admin.id,
    )
    assert created.public_slug == "neuer-verein-test"
    assert created.plan_code == "test_plan_new_tenant"
    assert created.billing_cycle == "yearly"
    assert "finance" in created.enabled_features
    assert created.storage_quota_bytes == 1_000_000

    try:
        service.create_tenant(db, AdminTenantCreate(name="Kollision", public_slug="neuer-verein-test"))
    except ValueError:
        pass
    else:
        raise AssertionError("Vergebener Slug muss abgelehnt werden")


def test_discount_and_note_are_stored_and_reduce_estimated_cost(db):
    admin_service = AdminTenantService()
    tenant_service = TenantService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)
    admin_service.upsert_plan(db, "test_plan_discount", _plan_write(price_monthly_rp=2000, price_yearly_rp=20000, feature_codes=[]))

    updated = admin_service.update_tenant_subscription(
        db,
        tenant.id,
        AdminTenantSubscriptionUpdate(plan_code="test_plan_discount", discount_percent=25, billing_note=" Vereinsrabatt bis 2027 "),
        admin_id=admin.id,
    )
    assert updated is not None
    assert updated.discount_percent == 25
    assert updated.billing_note == "Vereinsrabatt bis 2027"

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
        current_tenant_features=frozenset(),
    )
    subscription = tenant_service.get_subscription(db, tenant.id, actor)
    assert subscription is not None
    assert subscription.estimated_monthly_cost_rp == 1500
    assert subscription.estimated_yearly_cost_rp == 15000


def test_update_tenant_subscription_rejects_unknown_plan_code(db):
    """Hardening fix (audit 2026-09-24): update_tenant_subscription used to assign
    payload.plan_code straight onto the tenant with no existence check (unlike create_tenant,
    which already validates this) - an unknown/typo'd code relied entirely on the plan_code FK
    constraint to fail the commit, surfacing as an unhandled IntegrityError instead of a clean
    validation error. Only reachable by an already-authenticated platform-admin-owner (not a
    tenant-facing bypass), but should fail predictably like every other admin-input path."""
    admin_service = AdminTenantService()
    admin = make_platform_admin(db)
    tenant = make_tenant(db)

    with pytest.raises(ValueError, match="existiert nicht"):
        admin_service.update_tenant_subscription(
            db,
            tenant.id,
            AdminTenantSubscriptionUpdate(plan_code="does_not_exist", billing_cycle="monthly", user_limit_override=None),
            admin_id=admin.id,
        )


def _named_plan_write(name: str, **overrides) -> AdminPlanWrite:
    values = dict(
        name=name,
        price_monthly_rp=1000,
        price_yearly_rp=10000,
        included_user_limit=5,
        included_storage_bytes=1_000_000,
        sort_order=0,
        feature_codes=[],
    )
    values.update(overrides)
    return AdminPlanWrite(**values)


def test_featured_plan_is_exclusive(db):
    """Die Website hebt genau einen Plan als "Beliebteste Wahl" hervor - einen neuen Plan zu
    markieren, setzt den bisher markierten zurueck."""
    service = AdminTenantService()
    service.upsert_plan(db, "test_feat_a", _named_plan_write("Feat A", is_featured=True))
    service.upsert_plan(db, "test_feat_b", _named_plan_write("Feat B", is_featured=True))

    featured = [p.code for p in service.list_plans(db) if p.is_featured]
    assert featured == ["test_feat_b"]


def test_public_plans_lists_only_bookable_plans_with_feature_names(db):
    """Die oeffentliche Website zeigt nur buchbare Plaene, inklusive der Feature-Namen aus dem
    Katalog - Aenderungen im Adminportal schlagen damit ohne Deployment durch."""
    service = AdminTenantService()
    service.upsert_plan(db, "test_pub_visible", _named_plan_write("Pub Visible", feature_codes=["finance"], is_featured=True))
    service.upsert_plan(db, "test_pub_hidden", _named_plan_write("Pub Hidden", is_bookable=False))

    plans = {p.code: p for p in service.list_public_plans(db)}
    assert "test_pub_hidden" not in plans
    assert "legacy" not in plans
    visible = plans["test_pub_visible"]
    assert visible.is_featured is True
    assert visible.price_monthly_rp == 1000
    assert [f.code for f in visible.features] == ["finance"]
    assert visible.features[0].name == db.get(Feature, "finance").name


def test_public_customers_lists_only_tenants_marked_for_website(db):
    """Nur ausdruecklich freigegebene Mandanten erscheinen auf der Website unter "Im Einsatz bei"."""
    service = AdminTenantService()
    listed = make_tenant(db, name="Website Verein Gelistet")
    hidden = make_tenant(db, name="Website Verein Versteckt")

    result = service.set_tenant_website_listing(db, listed.id, True)
    assert result is not None and result.show_on_website is True

    names = [c.name for c in service.list_public_customers(db)]
    assert listed.name in names
    assert hidden.name not in names

    service.set_tenant_website_listing(db, listed.id, False)
    assert listed.name not in [c.name for c in service.list_public_customers(db)]


def test_set_tenant_website_listing_unknown_tenant_returns_none(db):
    assert AdminTenantService().set_tenant_website_listing(db, -1, True) is None
