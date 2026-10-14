"""End-to-End: Dateisystem -> lokales S3 -> externes Test-S3 -> lokales S3 -> zweites Test-S3.

Läuft gegen das isolierte test-s3 (docker-compose.tests.yml) mit reproduzierbaren Testdaten. Nach
jedem Wechsel wird geprüft: Anzahl, SHA-256, Grössen, Mandantenzugehörigkeit, Referenzen,
Downloadbarkeit über die echte Route, Berechtigungen (fremder Mandant) und Konsistenz nach einem
"Neustart" (neue ObjectStore-Instanz, die den aktiven Stand nur aus der Datenbank kennt).
Während der Live-Migrationen werden Dateien neu angelegt, überschrieben und gelöscht.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from app.api.routes import files as files_routes
from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_user
from app.core.storage import ABGABEBOX, MAIN, get_object_store
from app.models import (
    MaintenanceWindow,
    StorageGeneration,
    StorageMigration,
    StorageMigrationObject,
    StorageObject,
    StorageState,
    StoredFile,
)
from app.services import storage_migration_service as sms
from app.services.upload_pipeline import ingest_file
from app.workers import storage_verify, storage_worker
from tests.factories import make_current_user
from tests.storage_support import committed_storage, create_test_profile, make_committed_tenant, requires_s3  # noqa: F401

pytestmark = requires_s3
OWNER = "pytest-worker"


def drive(db, migration_id, *, until: str | None = None, max_steps: int = 400, on_state=None) -> StorageMigration:
    """Treibt den Worker synchron; überspringt Wartezeiten (Backoff, Beobachtungsphase) durch
    Zurücksetzen der Zeitstempel - die Logik selbst bleibt unverändert."""
    seen: set[str] = set()
    for _ in range(max_steps):
        db.expire_all()
        migration = db.get(StorageMigration, migration_id)
        if on_state is not None and migration.state not in seen:
            seen.add(migration.state)
            on_state(migration)
            db.expire_all()
            migration = db.get(StorageMigration, migration_id)
        if until is not None and migration.state == until:
            return migration
        if migration.state in sms.TERMINAL_STATES:
            return migration
        if migration.state == "awaiting_confirmation":
            sms.start(db, migration_id, actor_email="owner@example.com")
            db.commit()
            continue
        if migration.state == "ready_for_cutover" and migration.cutover_confirmed_at is None:
            sms.confirm_cutover(db, migration_id, actor_email="owner@example.com")
            db.commit()
        if migration.state == "observing":
            db.execute(update(StorageMigration).where(StorageMigration.id == migration_id).values(
                phase_started_at=datetime.now(UTC) - timedelta(seconds=int(migration.options.get("observe_seconds", 300)) + 5)))
        db.execute(update(StorageMigration).where(StorageMigration.id == migration_id).values(next_attempt_at=None))
        db.execute(update(StorageMigrationObject).where(StorageMigrationObject.migration_id == migration_id).values(next_attempt_at=None))
        db.commit()
        storage_worker.run_once(OWNER)
    migration = db.get(StorageMigration, migration_id)
    events = db.execute(text("SELECT kind, from_state, to_state, message FROM storage_migration_event WHERE migration_id = :id ORDER BY id DESC LIMIT 8"), {"id": migration_id}).all()
    raise AssertionError(f"Migration hängt in {migration.state}: {migration.last_error} / {events}")


def _png(seed: int, size: int) -> bytes:
    rng = random.Random(seed)
    return b"\x89PNG\r\n\x1a\n" + bytes(rng.getrandbits(8) for _ in range(size))


def seed_files(db, tenant_id: int, count: int, *, seed: int) -> dict[int, bytes]:
    files: dict[int, bytes] = {}
    for index in range(count):
        content = _png(seed * 1000 + index, 2000 + index * 37)
        result = ingest_file(
            db, tenant_id=tenant_id, content=content, original_filename=f"bild-{index}.png", scan_status="clean",
            sniff=lambda _c: "image/png", max_bytes=10**8, storage_subdir_parts=(f"tenant-{tenant_id}", "gallery"),
            enable_perceptual_dedupe=False, enable_thumbnail=False, created_by=None,
        )
        files[result.stored_file.id] = content
    db.commit()
    return files


def client_for(db, tenant_id: int) -> TestClient:
    app = FastAPI()
    app.include_router(files_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: make_current_user(tenant_id, role="writer")
    return TestClient(app)


def verify_everything(db, expected: dict[int, bytes], tenant_id: int, other_tenant_id: int, *, profile_id: int, generation: int, deleted: set[int]) -> None:
    db.expire_all()
    state = db.get(StorageState, 1)
    assert (state.active_profile_id, state.active_generation) == (profile_id, generation)
    assert not state.write_fenced
    # "Neustart": frische Instanz, die den aktiven Stand nur aus der Datenbank kennt.
    get_object_store.cache_clear()
    store = get_object_store()
    assert store.active_state(force=True).config.generation == generation
    client = client_for(db, tenant_id)
    foreign = client_for(db, other_tenant_id)
    for stored_file_id, content in expected.items():
        row = db.get(StoredFile, stored_file_id)
        assert row.tenant_id == tenant_id  # Mandantenzugehörigkeit unverändert
        data = store.get_bytes(MAIN, row.storage_path)
        assert hashlib.sha256(data).hexdigest() == row.checksum_sha256 == hashlib.sha256(content).hexdigest()
        assert len(data) == row.file_size_bytes
        response = client.get(f"/api/stored-files/{row.public_id}/content")
        assert response.status_code == 200 and response.content == content
        ranged = client.get(f"/api/stored-files/{row.public_id}/content", headers={"Range": "bytes=0-7"})
        assert ranged.status_code in (200, 206) and ranged.content[:8] == content[:8]
        assert foreign.get(f"/api/stored-files/{row.public_id}/content").status_code == 403  # Berechtigung
    for key in deleted_keys(db, deleted):
        assert not store.exists(MAIN, key), f"gelöschte Datei {key} ist wieder aufgetaucht"
    report = storage_verify.verify(full=True)
    assert report["counts"]["registry_missing"] == 0 and report["counts"]["registry_mismatch"] == 0, report


_deleted_keys: dict[int, str] = {}


def deleted_keys(db, deleted: set[int]) -> list[str]:
    return [_deleted_keys[i] for i in deleted]


def delete_file(db, stored_file_id: int) -> None:
    row = db.get(StoredFile, stored_file_id)
    _deleted_keys[stored_file_id] = row.storage_path
    from app.services.file_service import FileService

    FileService().delete_stored_file(db, row)
    db.commit()


def overwrite_object(db, stored_file_id: int, content: bytes) -> None:
    """Überschreibt den Inhalt unter demselben Key (wie ein neu hochgeladenes Vorlagen-Bauteil)."""
    row = db.get(StoredFile, stored_file_id)
    get_object_store().put_bytes(db, MAIN, row.storage_path, content)
    row.checksum_sha256 = hashlib.sha256(content).hexdigest()
    row.file_size_bytes = len(content)
    db.commit()


def test_full_migration_chain_keeps_every_confirmed_file(committed_storage, tmp_path, monkeypatch):
    db = committed_storage
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "export_root", str(tmp_path / "storage" / "exports"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    (tmp_path / "abgabebox").mkdir()
    get_object_store.cache_clear()

    tenant = make_committed_tenant(db, "E2E Verein")
    other = make_committed_tenant(db, "Fremder Verein")
    expected = seed_files(db, tenant.id, 6, seed=1)
    deleted: set[int] = set()
    # Nicht referenzierte Datei und Abgabebox-Datei direkt auf der Platte (Altbestand), dazu ein
    # temporärer Staging-Rest, der bewusst NICHT migriert wird.
    (tmp_path / "storage" / "uploads" / "orphans").mkdir(parents=True)
    (tmp_path / "storage" / "uploads" / "orphans" / "alt.bin").write_bytes(b"verwaist")
    (tmp_path / "abgabebox" / f"tenant-{tenant.id}" / "assignment-1").mkdir(parents=True)
    (tmp_path / "abgabebox" / f"tenant-{tenant.id}" / "assignment-1" / "abgabe.pdf").write_bytes(b"%PDF-1.4 abgabe")
    (tmp_path / "storage" / "uploads" / "_staging" / "gallery").mkdir(parents=True)
    (tmp_path / "storage" / "uploads" / "_staging" / "gallery" / "temp.zip").write_bytes(b"temp")

    run = uuid.uuid4().hex[:8]
    local = create_test_profile(db, f"Lokal {run}", f"e2e-{run}/local", provider="garage_local")
    ext_a = create_test_profile(db, f"Extern A {run}", f"e2e-{run}/ext-a")
    ext_b = create_test_profile(db, f"Extern B {run}", f"e2e-{run}/ext-b")
    db.commit()

    # 1) Erstmigration Dateisystem -> lokales S3 (volle Wartung)
    migration = sms.create_migration(db, target_profile_id=local.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    seen_windows: list[str] = []

    def during_initial(m):
        if m.maintenance_window_id is not None:
            seen_windows.append(db.get(MaintenanceWindow, m.maintenance_window_id).state)

    migration = drive(db, migration.id, on_state=during_initial)
    assert migration.state == "completed", migration.last_error
    assert migration.kind == "initial"
    assert "active" in seen_windows  # während der Kopie war die Wartung aktiv
    window = db.get(MaintenanceWindow, migration.maintenance_window_id)
    assert window.state == "completed"  # erst nach bestandener Endprüfung freigegeben
    report = sms.build_report(db, migration)
    assert report["final_integrity_ok"] is True
    inventory = report["inventory"]
    assert inventory["excluded_objects"] >= 1  # Staging-Rest bewusst ausgelassen
    unreferenced = {item["key"] for item in report["references"]["unreferenced"]}
    assert "uploads/orphans/alt.bin" in unreferenced  # nicht still ignoriert, sondern berichtet
    assert get_object_store().get_bytes(ABGABEBOX, f"tenant-{tenant.id}/assignment-1/abgabe.pdf") == b"%PDF-1.4 abgabe"
    assert not get_object_store().exists(MAIN, "uploads/_staging/gallery/temp.zip")
    verify_everything(db, expected, tenant.id, other.id, profile_id=local.id, generation=migration.target_generation, deleted=deleted)
    source_gen = db.scalars(select(StorageGeneration).where(StorageGeneration.generation == 0)).first()
    assert source_gen.status == "retained" and source_gen.retain_until > datetime.now(UTC)  # Rückfallfrist
    assert (tmp_path / "storage" / "uploads" / "orphans" / "alt.bin").exists()  # nichts gelöscht

    # Nach dem Cutover gehen neue Schreibvorgänge in das neue Ziel.
    expected.update(seed_files(db, tenant.id, 2, seed=2))

    # 2) Live-Migration lokal -> extern A, mit Änderungen während der Kopie
    migration = sms.create_migration(db, target_profile_id=ext_a.id, options={"observe_seconds": 30, "parallelism": 3}, actor_email="owner@example.com")
    db.commit()
    victim, changed = sorted(expected)[0], sorted(expected)[1]
    new_content = _png(999, 5000)

    def live_changes(m):
        if m.state == "copying":
            expected.update(seed_files(db, tenant.id, 2, seed=3))  # neue Uploads
            overwrite_object(db, changed, new_content)  # Änderung
            expected[changed] = new_content
            delete_file(db, victim)  # Löschung
            expected.pop(victim)
            deleted.add(victim)

    migration = drive(db, migration.id, on_state=live_changes)
    assert migration.state == "completed", migration.last_error
    assert victim in deleted and expected[changed] == new_content, "Live-Änderungen wurden nicht während der Kopie ausgeführt"
    assert migration.applied_outbox_seq > migration.snapshot_outbox_seq  # Journal wurde nachgezogen
    verify_everything(db, expected, tenant.id, other.id, profile_id=ext_a.id, generation=migration.target_generation, deleted=deleted)
    assert migration.maintenance_window_id is None  # kurzer Schreib-Fence wieder freigegeben

    # 3) Zurück zum lokalen S3 (neue Generation - alte lokale Daten werden nie wieder aktiv)
    previous_local_generation = db.scalars(select(StorageGeneration).where(StorageGeneration.profile_id == local.id).order_by(StorageGeneration.generation)).first().generation
    migration = sms.create_migration(db, target_profile_id=local.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    assert migration.target_generation > previous_local_generation
    migration = drive(db, migration.id)
    assert migration.state == "completed", migration.last_error
    verify_everything(db, expected, tenant.id, other.id, profile_id=local.id, generation=migration.target_generation, deleted=deleted)

    # 4) Zweite externe Migration nach abgeschlossener erster
    expected.update(seed_files(db, tenant.id, 1, seed=4))
    migration = sms.create_migration(db, target_profile_id=ext_b.id, options={"observe_seconds": 30, "verify_mode": "head"}, actor_email="owner@example.com")
    db.commit()
    migration = drive(db, migration.id)
    assert migration.state == "completed", migration.last_error
    verify_everything(db, expected, tenant.id, other.id, profile_id=ext_b.id, generation=migration.target_generation, deleted=deleted)

    # Abgelöste Generationen bleiben bis zur bewussten Bereinigung erhalten.
    retained = db.scalars(select(StorageGeneration).where(StorageGeneration.status == "retained")).all()
    assert len(retained) >= 3
