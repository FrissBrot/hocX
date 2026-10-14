"""Fehler- und Sicherheitsszenarien der Storage-Migration (Teil 10 des Auftrags).

Fehler werden über FaultyBackend (tests/storage_support.py) in echte Backends injiziert; das Ziel
ist immer das isolierte test-s3. Geprüft wird jeweils, dass keine bestätigte Datei verloren geht,
keine veraltete Version unbemerkt aktiv wird und die Quelle aktiv bleibt, solange kein
vollständig geprüfter Cutover stattgefunden hat.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.objstore_client import FilesystemBackend, S3Backend, StorageUnavailable
from app.core.storage import MAIN, get_object_store
from app.models import StorageGeneration, StorageMigration, StorageMigrationObject, StorageProfile, StorageState, StoredFile
from app.services import storage_migration_service as sms
from app.services import storage_profile_service
from app.workers import storage_verify, storage_worker
from tests.storage_support import FaultyBackend, committed_storage, create_test_profile, make_committed_tenant, requires_s3, throttled, unavailable  # noqa: F401
from tests.test_storage_migration_e2e import drive, seed_files

pytestmark = requires_s3


@pytest.fixture
def setup(committed_storage, tmp_path, monkeypatch):
    db = committed_storage
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "export_root", str(tmp_path / "storage" / "exports"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    (tmp_path / "abgabebox").mkdir()
    get_object_store.cache_clear()
    tenant = make_committed_tenant(db, "Fehler Verein")
    files = seed_files(db, tenant.id, 5, seed=7)
    run = uuid.uuid4().hex[:8]
    local = create_test_profile(db, f"Lokal {run}", f"faults-{run}/local", provider="garage_local")
    external = create_test_profile(db, f"Extern {run}", f"faults-{run}/ext")
    db.commit()
    yield db, tenant, files, local, external
    get_object_store()._backend_factory = None


def inject(failing_profile_id: int, failures: dict[str, list[Exception]]) -> list[FaultyBackend]:
    store = get_object_store()
    created: list[FaultyBackend] = []

    def factory(config):
        real = FilesystemBackend(config, store.filesystem_roots) if config.is_filesystem else S3Backend(config)
        if config.profile_id != failing_profile_id:
            return real
        faulty = FaultyBackend(real, failures)
        created.append(faulty)
        return faulty

    store._backend_factory = factory
    store._backends = {}
    return created


def initial(db, local) -> StorageMigration:
    migration = sms.create_migration(db, target_profile_id=local.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    return drive(db, migration.id)


def assert_files_intact(db, files: dict[int, bytes]) -> None:
    store = get_object_store()
    store.invalidate()
    for stored_file_id, content in files.items():
        row = db.get(StoredFile, stored_file_id)
        assert hashlib.sha256(store.get_bytes(MAIN, row.storage_path)).hexdigest() == hashlib.sha256(content).hexdigest()


# 4-7: Ziel nicht erreichbar, Timeouts, Rate-Limits -------------------------------------------


def test_transient_target_failures_and_rate_limits_are_retried_until_complete(setup):
    db, _tenant, files, local, _external = setup
    inject(local.id, {"put_stream": [unavailable(), throttled(), unavailable(), throttled()]})
    migration = initial(db, local)
    assert migration.state == "completed", migration.last_error
    attempts = db.scalars(select(StorageMigrationObject.attempts).where(StorageMigrationObject.migration_id == migration.id)).all()
    assert sum(attempts) >= 1  # mindestens ein Objekt brauchte einen weiteren Versuch
    assert_files_intact(db, files)


def test_unreachable_source_during_preflight_retries_instead_of_failing(setup):
    db, _tenant, _files, local, external = setup
    assert initial(db, local).state == "completed"
    inject(local.id, {"list": [unavailable(), unavailable()]})
    migration = sms.create_migration(db, target_profile_id=external.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    db.expire_all()
    storage_worker.run_once("w1")
    db.expire_all()
    assert db.get(StorageMigration, migration.id).state == "retrying"
    assert drive(db, migration.id).state == "completed"


# 3: Datenbank kurz weg -----------------------------------------------------------------------


def test_database_errors_in_a_phase_lead_to_retry_not_to_data_loss(setup, monkeypatch):
    db, _tenant, files, local, _external = setup
    original = storage_worker.phase_verifying
    calls = {"n": 0}

    def flaky(db_, ctx, migration):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))
        return original(db_, ctx, migration)

    monkeypatch.setitem(storage_worker.PHASES, "verifying", flaky)
    migration = initial(db, local)
    assert migration.state == "completed"
    kinds = db.execute(text("SELECT to_state FROM storage_migration_event WHERE migration_id = :id"), {"id": migration.id}).scalars().all()
    assert "retrying" in kinds
    assert_files_intact(db, files)


# 1/2/13/14/15: Absturz, zwei Worker, Lease-Verlust, veralteter Worker -------------------------


def test_two_workers_never_hold_the_same_migration(setup):
    db, _tenant, _files, local, _external = setup
    sms.create_migration(db, target_profile_id=local.id, options={}, actor_email="owner@example.com")
    db.commit()
    first = storage_worker.claim("worker-a")
    second = storage_worker.claim("worker-b")
    assert first is not None and second is None
    storage_worker.release_lease(first)


def test_a_worker_that_lost_its_lease_cannot_write_anymore(setup):
    db, _tenant, _files, local, _external = setup
    migration = sms.create_migration(db, target_profile_id=local.id, options={}, actor_email="owner@example.com")
    db.commit()
    stale = storage_worker.claim("stale-worker")
    # Lease abgelaufen, ein anderer Worker übernimmt (neues Fencing-Token).
    db.execute(update(StorageMigration).where(StorageMigration.id == migration.id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    fresh = storage_worker.claim("fresh-worker")
    assert fresh is not None and fresh.token > stale.token
    with storage_worker.SessionLocal() as session:
        with pytest.raises(storage_worker.LeaseLost):
            storage_worker.guarded(session, stale, state="preflight")
    assert not storage_worker.renew(stale)
    storage_worker.release_lease(fresh)


def test_a_crashed_worker_is_resumed_by_another_without_recopying_everything(setup):
    db, _tenant, files, local, _external = setup
    migration = sms.create_migration(db, target_profile_id=local.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    drive(db, migration.id, until="copying")
    ctx = storage_worker.claim("crashing-worker")
    with storage_worker.SessionLocal() as session:
        m = storage_worker.load(session, ctx)
        storage_worker.copy_pending(session, ctx, m)  # ein Stapel, dann "Absturz" ohne Lease-Freigabe
    db.execute(update(StorageMigration).where(StorageMigration.id == migration.id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    completed = drive(db, migration.id)
    assert completed.state == "completed"
    assert completed.copied_objects == completed.total_objects  # kein doppeltes Zählen nach Wiederaufnahme
    assert_files_intact(db, files)


# 16/17: Cutover scheitert, Neustart direkt nach dem Cutover ----------------------------------


def test_failed_cutover_keeps_the_source_active_and_retries(setup):
    db, _tenant, files, local, external = setup
    assert initial(db, local).state == "completed"
    migration = sms.create_migration(db, target_profile_id=external.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    drive(db, migration.id, until="cutting_over")
    inject(external.id, {"list": [unavailable()]})  # finaler Abgleich listet das Ziel
    storage_worker.run_once("w1")
    db.expire_all()
    state = db.get(StorageState, 1)
    assert state.active_profile_id == local.id and not state.write_fenced  # Quelle aktiv, kein Fence
    assert db.get(StorageMigration, migration.id).state == "retrying"
    assert db.get(StorageMigration, migration.id).cutover_committed_at is None
    done = drive(db, migration.id)
    assert done.state == "completed"
    get_object_store.cache_clear()  # "Neustart" direkt nach dem Cutover
    assert get_object_store().active_state(force=True).config.profile_id == external.id
    assert_files_intact(db, files)


# 9/10/11: Änderungen während der Migration werden nachgeführt ---------------------------------


def test_changes_after_snapshot_never_resurrect_deleted_or_stale_versions(setup):
    db, tenant, files, local, external = setup
    assert initial(db, local).state == "completed"
    migration = sms.create_migration(db, target_profile_id=external.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    drive(db, migration.id, until="catching_up")
    store = get_object_store()
    keys = [db.get(StoredFile, i).storage_path for i in sorted(files)]
    store.delete(db, MAIN, keys[0])
    store.put_bytes(db, MAIN, keys[1], b"\x89PNG neue Version")
    store.put_bytes(db, MAIN, keys[1], b"\x89PNG noch neuere Version")
    db.commit()
    done = drive(db, migration.id)
    assert done.state == "completed"
    store.invalidate()
    assert not store.exists(MAIN, keys[0])
    assert store.get_bytes(MAIN, keys[1]) == b"\x89PNG noch neuere Version"


# 12: zwei Administratoren starten gleichzeitig -----------------------------------------------


def test_two_admins_starting_a_migration_concurrently_create_only_one(setup):
    db, _tenant, _files, local, _external = setup
    local_id = local.id  # vor den Threads lesen (abgelaufene ORM-Instanz der Fixture-Session)
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        with storage_worker.SessionLocal() as session:
            barrier.wait()
            try:
                sms.create_migration(session, target_profile_id=local_id, options={}, actor_email="admin@example.com")
                session.commit()
                results.append("ok")
            except sms.MigrationError:
                session.rollback()
                results.append("rejected")
            except Exception as exc:  # sichtbar machen statt den Thread still sterben zu lassen
                session.rollback()
                results.append(f"error:{type(exc).__name__}:{exc}"[:300])

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results) == ["ok", "rejected"]


# 27: Profil wird während einer Migration geändert --------------------------------------------


def test_profile_changes_during_a_migration_are_rejected_and_detected(setup):
    db, _tenant, _files, local, _external = setup
    migration = sms.create_migration(db, target_profile_id=local.id, options={}, actor_email="owner@example.com")
    db.commit()
    with pytest.raises(storage_profile_service.StorageProfileError):
        storage_profile_service.update_profile(db, db.get(StorageProfile, local.id), {"name": "Neu"}, actor_email="x")
    db.rollback()
    # Selbst wenn die Konfiguration am API vorbei geändert würde, bricht der Worker sicher ab.
    db.execute(update(StorageProfile).where(StorageProfile.id == local.id).values(config_version=StorageProfile.config_version + 1))
    db.commit()
    result = drive(db, migration.id)
    assert result.state == "failed" and "geändert" in (result.last_error or "")
    assert db.get(StorageState, 1).active_generation == 0  # Quelle bleibt aktiv


# Abbruch, Pause, dauerhaft fehlgeschlagene Objekte -------------------------------------------


def test_cancel_and_pause_resume_keep_the_source_active(setup):
    db, _tenant, files, local, external = setup
    assert initial(db, local).state == "completed"
    migration = sms.create_migration(db, target_profile_id=external.id, options={"observe_seconds": 30}, actor_email="owner@example.com")
    db.commit()
    drive(db, migration.id, until="copying")
    sms.pause(db, migration.id, actor_email="owner@example.com")
    db.commit()
    assert storage_worker.claim("w") is None  # pausiert: kein Worker nimmt sie auf
    sms.resume(db, migration.id, actor_email="owner@example.com")
    db.commit()
    sms.cancel(db, migration.id, actor_email="owner@example.com")
    db.commit()
    cancelled = drive(db, migration.id)
    assert cancelled.state == "cancelled"
    assert db.get(StorageState, 1).active_profile_id == local.id
    generation = db.scalars(select(StorageGeneration).where(StorageGeneration.generation == cancelled.target_generation)).first()
    assert generation.status == "abandoned"  # Zieldaten bleiben, Bereinigung ist ein eigener Schritt
    assert_files_intact(db, files)


def test_objects_missing_in_the_source_block_cutover_until_acknowledged(setup):
    db, _tenant, files, local, external = setup
    assert initial(db, local).state == "completed"
    victim = db.get(StoredFile, sorted(files)[0])
    # Vorbestehende Inkonsistenz: Objekt hinter dem Rücken des Systems entfernt.
    get_object_store().active_backend(force=True).delete(MAIN, victim.storage_path)
    migration = sms.create_migration(db, target_profile_id=external.id, options={"observe_seconds": 30, "max_object_attempts": 1}, actor_email="owner@example.com")
    db.commit()
    for _ in range(40):
        storage_worker.run_once("w")
        db.expire_all()
        dead = db.scalar(select(StorageMigrationObject.id).where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status == "dead"))
        if dead is not None and db.get(StorageMigration, migration.id).state in ("copying", "catching_up", "verifying"):
            break
        if db.get(StorageMigration, migration.id).state == "awaiting_confirmation":
            sms.start(db, migration.id, actor_email="owner@example.com")
            db.commit()
        db.execute(update(StorageMigration).where(StorageMigration.id == migration.id).values(next_attempt_at=None))
        db.commit()
    assert db.get(StorageMigration, migration.id).state != "cutting_over"
    assert db.get(StorageState, 1).active_profile_id == local.id
    assert sms.accept_missing(db, migration.id, actor_email="owner@example.com") == 1
    db.commit()
    done = drive(db, migration.id)
    assert done.state == "completed"
    assert f"main/{victim.storage_path}" in done.checkpoint["accepted_missing"]


# Bereinigung alter Generationen --------------------------------------------------------------


def test_purging_an_old_generation_requires_confirmation_and_expired_retention(setup):
    db, _tenant, files, local, external = setup
    assert initial(db, local).state == "completed"
    old = db.scalars(select(StorageGeneration).where(StorageGeneration.generation == 0)).first()
    with pytest.raises(sms.MigrationError, match="Bestätigung"):
        sms.request_generation_purge(db, old.id, confirmation="ja", actor_email="owner@example.com")
    with pytest.raises(sms.MigrationError, match="Rückfallfrist"):
        sms.request_generation_purge(db, old.id, confirmation="g0", actor_email="owner@example.com")
    db.rollback()
    db.execute(update(StorageGeneration).where(StorageGeneration.id == old.id).values(retain_until=datetime.now(UTC) - timedelta(days=1)))
    db.commit()
    sms.request_generation_purge(db, old.id, confirmation="g0", actor_email="owner@example.com")
    db.commit()
    storage_worker.purge_generations()
    db.expire_all()
    assert db.get(StorageGeneration, old.id).status == "purged"
    for stored_file_id in files:
        assert not (settings.storage_root and __import__("pathlib").Path(settings.storage_root, db.get(StoredFile, stored_file_id).storage_path).exists())
    assert_files_intact(db, files)  # aktive Generation unberührt


# 28: Datenbank und S3 aus zeitlich inkonsistenten Backups ------------------------------------


def test_storage_verify_detects_objects_missing_after_an_inconsistent_restore(setup):
    db, _tenant, files, local, _external = setup
    assert initial(db, local).state == "completed"
    assert storage_verify.verify(full=True)["consistent"] is True
    victim = db.get(StoredFile, sorted(files)[1])
    get_object_store().active_backend(force=True).delete(MAIN, victim.storage_path)  # "älteres S3-Backup"
    report = storage_verify.verify(full=True)
    assert report["consistent"] is False
    assert {"namespace": "main", "key": victim.storage_path} in report["registry_missing"]
    assert any(item["key"] == victim.storage_path for item in report["missing_references"])


# 18: lokaler S3-Container unerwartet gestoppt ------------------------------------------------


def test_unreachable_storage_yields_503_not_500():
    import asyncio

    from app.main import storage_unavailable_handler

    class _Req:
        method = "GET"
        url = type("U", (), {"path": "/api/stored-files/x/content"})()
        headers: dict = {}
        cookies: dict = {}
        state = type("S", (), {})()
        client = None

    try:
        response = asyncio.run(storage_unavailable_handler(_Req(), StorageUnavailable("EndpointConnectionError")))
    except Exception as exc:  # pragma: no cover - Logging darf die Antwort nie verhindern
        pytest.fail(f"Handler warf {exc!r}")
    assert response.status_code == 503 and response.headers["retry-after"] == "30"
