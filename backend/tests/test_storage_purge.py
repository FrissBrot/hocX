"""S3-008: Löschen erst nach dem Commit (Tombstone + Job storage_purge).

ObjectStore.delete registriert nur; ein Rollback des Aufrufers lässt das Objekt bestehen. Physisch
entfernt purge_deleted die Objekte nach dem Commit - nie neuen Inhalt desselben Keys und nie einen
Key, den gerade ein Schreiber hält."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.storage import MAIN, get_object_store
from app.services import storage_migration_service
from tests.storage_support import committed_storage  # noqa: F401 - Fixture


def _registry(db, key: str):
    return db.execute(
        text("SELECT status, version, purge_pending FROM storage_object WHERE namespace = 'main' AND key = :k"), {"k": key}
    ).one()


def _key() -> str:
    return f"uploads/purge-test/{uuid.uuid4().hex}.txt"


def test_rollback_of_a_delete_keeps_the_object_and_its_registration(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"inhalt")
    db.flush()

    savepoint = db.begin_nested()
    store.delete(db, MAIN, key)
    assert (tmp_path / key).exists(), "delete darf vor dem Commit nichts physisch entfernen"
    savepoint.rollback()

    assert (tmp_path / key).read_bytes() == b"inhalt"
    assert _registry(db, key).status == "active"
    assert store.purge_deleted(db) == 0
    assert (tmp_path / key).exists()


def test_purge_removes_a_deleted_object_and_acknowledges_the_tombstone(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"inhalt")
    store.delete(db, MAIN, key)
    assert _registry(db, key).purge_pending is True
    assert (tmp_path / key).exists()

    assert store.purge_deleted(db) >= 1

    assert not (tmp_path / key).exists()
    registry = _registry(db, key)
    assert (registry.status, registry.purge_pending) == ("deleted", False)


def test_purge_never_removes_content_written_again_after_the_delete(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"alt")
    store.delete(db, MAIN, key)
    store.put_bytes(db, MAIN, key, b"neu")

    store.purge_deleted(db)

    assert (tmp_path / key).read_bytes() == b"neu"
    registry = _registry(db, key)
    assert (registry.status, registry.purge_pending) == ("active", False)


def test_purge_skips_a_key_that_an_open_writer_is_rewriting(committed_storage, tmp_path, monkeypatch):  # noqa: F811
    """Ein Schreiber hat den Key gesperrt und physisch schon neu geschrieben, aber noch nicht
    registriert: der Job darf das neue Objekt nicht löschen und versucht es später erneut."""
    db = committed_storage
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"alt")
    db.commit()
    store.delete(db, MAIN, key)
    db.commit()

    writer = SessionLocal()
    try:
        _ticket, backend = store._begin_write(writer)
        store._lock_key(writer, MAIN, key)
        (tmp_path / key).write_bytes(b"neu")  # physisch geschrieben, Registrierung steht noch aus

        reaper = SessionLocal()
        try:
            assert store.purge_deleted(reaper) == 0
            reaper.commit()
        finally:
            reaper.close()
        assert (tmp_path / key).read_bytes() == b"neu"
        assert _registry(db, key).purge_pending is True
    finally:
        writer.rollback()
        writer.close()

    (tmp_path / key).unlink()
    assert storage_migration_service.purge_deleted_objects(db) == {"purged": 1}
    assert _registry(db, key).purge_pending is False


def test_purge_job_ends_quietly_while_writes_are_fenced(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"inhalt")
    store.delete(db, MAIN, key)
    db.commit()
    db.execute(text("UPDATE storage_state SET write_fenced = true, fence_reason = 'test' WHERE id = 1"))

    assert storage_migration_service.purge_deleted_objects(db) == {"purged": 0}
    assert (tmp_path / key).exists()


def test_purge_also_removes_deleted_abgabebox_objects(db, tmp_path, monkeypatch):
    """Die Abgabebox registriert nur (eingeschränkte Rolle); das Backend hat ihren Speicher
    eingebunden und entfernt die Objekte physisch."""
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    store = get_object_store()
    key = f"quarantine/tenant-1/{uuid.uuid4().hex}.pdf"
    store.put_bytes(db, "abgabebox", key, b"%PDF")
    store.delete(db, "abgabebox", key)
    assert (tmp_path / "abgabebox" / key).exists()

    store.purge_deleted(db)

    assert not (tmp_path / "abgabebox" / key).exists()
