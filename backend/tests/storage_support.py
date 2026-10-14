"""Gemeinsame Hilfen für Objektspeicher-, Migrations- und Wartungstests.

Die Migrationstests müssen echt committen (der Worker arbeitet mit eigenen Verbindungen) - das
Fixture committed_storage hält darum den Ausgangszustand fest und stellt ihn danach wieder her:
aktiver Speicher zurück auf das Dateisystem, angelegte Profile, Migrationen, Generationen,
Wartungsfenster, Registry-/Journal-Einträge und Test-Mandanten werden entfernt. Alles S3-seitige
liegt im isolierten test-s3 (docker-compose.tests.yml), nie in produktiven Buckets.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, text, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.objstore_client import Backend, ObjectInfo, StorageThrottled, StorageUnavailable
from app.core.storage import get_object_store
from app.models import (
    MaintenanceWindow,
    StorageGeneration,
    StorageMigration,
    StorageProfile,
    StorageState,
)
from app.services import maintenance_service, storage_profile_service

S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT")
requires_s3 = pytest.mark.skipif(not S3_ENDPOINT, reason="TEST_S3_ENDPOINT nicht gesetzt (docker-compose.tests.yml: test-s3)")


def s3_profile_values(name: str, prefix: str, *, restricted: bool = True) -> dict:
    values = {
        "name": name,
        "provider": "s3_compatible",
        "endpoint_url": S3_ENDPOINT,
        "region": "garage",
        "bucket": "hocx-main",
        "abgabebox_bucket": "hocx-abgabebox",
        "prefix": prefix,
        "addressing_style": "path",
        "access_key": os.environ["TEST_S3_ACCESS_KEY"],
        "secret_key": os.environ["TEST_S3_SECRET_KEY"],
        "tls_verify": False,
    }
    if restricted:
        values["restricted_access_key"] = os.environ["TEST_S3_ABGABEBOX_ACCESS_KEY"]
        values["restricted_secret_key"] = os.environ["TEST_S3_ABGABEBOX_SECRET_KEY"]
    return values


def create_test_profile(db, name: str, prefix: str, *, provider: str = "s3_compatible") -> StorageProfile:
    """Legt ein Profil auf dem Test-S3 an. provider="garage_local" erlaubt http (wie lokal)."""
    values = s3_profile_values(name, prefix)
    values["provider"] = "garage_local" if provider == "garage_local" else "s3_compatible"
    if values["provider"] == "s3_compatible":
        # Externe Profile müssen HTTPS nutzen; das Test-S3 spricht nur http. Die Validierung wird
        # hier bewusst umgangen (und separat in test_storage_profiles getestet).
        profile = storage_profile_service.create_profile(db, {**values, "provider": "garage_local"}, actor_email="test@example.com")
        profile.provider = "s3_compatible"
    else:
        profile = storage_profile_service.create_profile(db, values, actor_email="test@example.com")
    profile.last_test_ok = True
    db.flush()
    return profile


@pytest.fixture
def committed_storage(monkeypatch):
    """Session, deren Änderungen wirklich committet werden - mit vollständigem Aufräumen."""
    monkeypatch.setattr(settings, "maintenance_cache_seconds", 0.05)
    started = datetime.now(UTC)
    db = SessionLocal()
    state = db.get(StorageState, 1)
    original = (state.active_profile_id, state.active_generation)
    existing_profiles = set(db.scalars(select(StorageProfile.id)))
    # Register-/Journal-Reste anderer Tests (die mit echten Commits geschrieben haben) würden
    # sonst als "registriert, aber in der Quelle fehlend" in die Migration eingehen - die
    # Migrationstests arbeiten auf eigenen, frischen Speicherwurzeln.
    db.execute(text("DELETE FROM storage_object"))
    db.execute(text("DELETE FROM storage_change_outbox"))
    db.commit()
    max_outbox = db.scalar(text("SELECT COALESCE(MAX(seq), 0) FROM storage_change_outbox"))
    tenant_ids: list[int] = []
    db.info["test_tenant_ids"] = tenant_ids
    db.commit()
    try:
        yield db
    finally:
        db.rollback()
        db.execute(update(StorageState).where(StorageState.id == 1).values(
            active_profile_id=original[0], active_generation=original[1], write_fenced=False, fence_reason=None,
            fenced_at=None, local_s3_requested_until=None))
        db.execute(delete(StorageMigration).where(StorageMigration.created_at >= started))
        db.execute(delete(StorageGeneration).where(StorageGeneration.created_at >= started, StorageGeneration.generation != original[1]))
        db.execute(update(StorageGeneration).where(StorageGeneration.generation == original[1]).values(status="active", retain_until=None, deactivated_at=None))
        db.execute(delete(MaintenanceWindow).where(MaintenanceWindow.created_at >= started))
        db.execute(text("DELETE FROM storage_change_outbox WHERE seq > :seq"), {"seq": max_outbox})
        db.execute(text("DELETE FROM storage_object WHERE updated_at >= :started"), {"started": started})
        for tenant_id in tenant_ids:
            db.execute(text("DELETE FROM gallery_image WHERE tenant_id = :t"), {"t": tenant_id})
            db.execute(text("DELETE FROM stored_file WHERE tenant_id = :t"), {"t": tenant_id})
            db.execute(text("DELETE FROM tenant WHERE id = :t"), {"t": tenant_id})
        new_profiles = set(db.scalars(select(StorageProfile.id))) - existing_profiles
        if new_profiles:
            db.execute(delete(StorageProfile).where(StorageProfile.id.in_(new_profiles)))
        db.commit()
        db.close()
        get_object_store().invalidate()
        maintenance_service.invalidate_cache()


class FaultyBackend:
    """Fehlerinjektion um ein echtes Backend: schlägt die nächsten n Aufrufe einer Operation mit
    der angegebenen Ausnahme fehl (Timeouts, Rate-Limits, Ausfälle)."""

    def __init__(self, inner: Backend, failures: dict[str, list[Exception]]) -> None:
        self.inner = inner
        self.config = inner.config
        self.failures = failures
        self.calls: dict[str, int] = {}

    def _maybe_fail(self, operation: str) -> None:
        self.calls[operation] = self.calls.get(operation, 0) + 1
        queue = self.failures.get(operation)
        if queue:
            raise queue.pop(0)

    def put_stream(self, *args, **kwargs) -> ObjectInfo:
        self._maybe_fail("put_stream")
        return self.inner.put_stream(*args, **kwargs)

    def open_read(self, *args, **kwargs):
        self._maybe_fail("open_read")
        return self.inner.open_read(*args, **kwargs)

    def head(self, *args, **kwargs):
        self._maybe_fail("head")
        return self.inner.head(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._maybe_fail("delete")
        return self.inner.delete(*args, **kwargs)

    def list(self, *args, **kwargs):
        self._maybe_fail("list")
        return self.inner.list(*args, **kwargs)

    def copy(self, *args, **kwargs):
        return self.inner.copy(*args, **kwargs)

    def local_path(self, *args, **kwargs):
        return self.inner.local_path(*args, **kwargs)

    def abort_stale_multipart_uploads(self, *args, **kwargs):
        return self.inner.abort_stale_multipart_uploads(*args, **kwargs)


def throttled() -> StorageThrottled:
    return StorageThrottled("SlowDown")


def unavailable() -> StorageUnavailable:
    return StorageUnavailable("ConnectTimeoutError")


def make_committed_tenant(db, name: str):
    from tests.factories import make_tenant

    tenant = make_tenant(db, f"{name} {uuid.uuid4().hex[:6]}")
    db.commit()
    db.info["test_tenant_ids"].append(tenant.id)
    return tenant
