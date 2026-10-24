"""Tests for Speicher-Zusatzpakete (0087_storage_packages): the catalog CRUD, the tenant
assignment (full-replace incl. quantity) and recompute_effective_storage_quota - the piece that
keeps Tenant.storage_quota_bytes in sync with plan + assigned packages (no manual override since
0136)."""
from __future__ import annotations

import importlib.util
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from app.core.db import engine
from app.schemas.admin import AdminPlanWrite, AdminStoragePackageWrite, AdminTenantStoragePackageItem, AdminTenantSubscriptionUpdate
from app.services.admin_tenant_service import AdminTenantService

from tests.factories import make_tenant
from tests.test_admin_plan_pricing import make_platform_admin

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def test_storage_package_write_rejects_negative_bytes_and_prices():
    """Hardening fix (audit 2026-09-24): AdminStoragePackageWrite had no lower bound on
    bytes/price fields, unlike sibling schemas (AdminTenantSubscriptionUpdate.discount_percent) - a negative package size could drive
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


def _migration_module(filename: str):
    """Migration files start with a digit and can't be `import`ed normally - load by path, the
    same way Alembic resolves version files, to run the exact SQL they execute."""
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _legacy_quota_schema():
    """Isolated schema with the pre-0136 tables (tenant still has storage_quota_manual_override),
    so the historic 0088/0136 statements can run against a head database that no longer has the
    column. Rolled back afterwards."""
    schema = f"test_quota_{uuid.uuid4().hex}"
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))  # sql-ok: Schemaname aus uuid4
            conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))  # sql-ok: Schemaname aus uuid4
            conn.execute(sa.text("""
                CREATE TABLE plan (code text PRIMARY KEY, included_storage_bytes bigint);
                CREATE TABLE storage_package (code text PRIMARY KEY, bytes bigint NOT NULL);
                CREATE TABLE tenant (
                    id bigint PRIMARY KEY, plan_code text REFERENCES plan(code), storage_quota_bytes bigint,
                    storage_quota_manual_override boolean NOT NULL DEFAULT FALSE
                );
                CREATE TABLE tenant_storage_package (
                    tenant_id bigint NOT NULL REFERENCES tenant(id), package_code text NOT NULL REFERENCES storage_package(code),
                    quantity integer NOT NULL
                );
                INSERT INTO plan VALUES ('limited', 1000), ('unlimited', NULL);
                INSERT INTO storage_package VALUES ('pkg', 500);
            """))
            yield conn
        finally:
            transaction.rollback()


def _tenants(conn) -> dict[int, tuple[int | None, bool]]:
    rows = conn.execute(sa.text("SELECT id, storage_quota_bytes, storage_quota_manual_override FROM tenant"))
    return {row.id: (row.storage_quota_bytes, row.storage_quota_manual_override) for row in rows}


def test_migration_0088_resets_only_overrides_that_were_grants():
    """Security fix (audit 2026-09-24): migration 0088's blanket reset used to widen ANY manual
    override back to the auto-computed plan+package total, even one an admin had set BELOW that
    total as a deliberate restriction - silently granting that tenant more storage at deploy
    time. It only resets an override that was a grant (current value >= the computed total),
    and never widens a finite override to unlimited."""
    with _legacy_quota_schema() as conn:
        conn.execute(sa.text("""
            INSERT INTO tenant (id, plan_code, storage_quota_bytes, storage_quota_manual_override) VALUES
                (1, 'limited', 999999, TRUE),   -- Erweiterung
                (2, 'limited', 100, TRUE),      -- Einschränkung
                (3, 'unlimited', 50000, TRUE)   -- Plan unbegrenzt: endlicher Wert war Einschränkung
        """))
        conn.execute(sa.text(_migration_module("0088_remove_manual_storage_quota.py").RESET_GRANTED_OVERRIDES_SQL))
        assert _tenants(conn) == {1: (1000, False), 2: (100, True), 3: (50000, True)}


def test_migration_0136_recomputes_every_remaining_override():
    """FAR-008: 0136 removes the manual quota for good - every tenant still flagged (the
    restrictive overrides 0088 deliberately kept) gets plan + packages, other tenants stay as
    they are, and the statement reports old and new value for the migration log."""
    with _legacy_quota_schema() as conn:
        conn.execute(sa.text("""
            INSERT INTO tenant (id, plan_code, storage_quota_bytes, storage_quota_manual_override) VALUES
                (1, 'limited', 100, TRUE),
                (2, 'unlimited', 50000, TRUE),
                (3, 'limited', 1500, FALSE);
            INSERT INTO tenant_storage_package VALUES (1, 'pkg', 2);
        """))
        reported = conn.execute(sa.text(_migration_module("0136_drop_manual_storage_quota.py").RESET_REMAINING_OVERRIDES_SQL)).all()
        assert [tuple(row) for row in reported] == [(1, 100, 2000), (2, 50000, None)]
        assert {tenant_id: quota for tenant_id, (quota, _flag) in _tenants(conn).items()} == {1: 2000, 2: None, 3: 1500}


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
