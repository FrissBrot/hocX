"""S3-008: Löschen erst nach dem Commit (Tombstone + Job storage_purge).

ObjectStore.delete registriert nur; ein Rollback des Aufrufers lässt das Objekt bestehen. Physisch
entfernt purge_deleted die Objekte nach dem Commit - nie neuen Inhalt desselben Keys und nie einen
Key, den gerade ein Schreiber hält."""

from __future__ import annotations

import hashlib
import io
import uuid

from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.storage import MAIN, get_object_store
from app.services import storage_migration_service
from tests.storage_support import committed_storage  # noqa: F401 - Fixture


def _registry(db, key: str):
    return db.execute(
        text("SELECT status, version, purge_pending FROM storage_object WHERE namespace = 'main' AND key = :k"), {"k": key}
    ).one()


def _raw(key: str, namespace: str = MAIN) -> bytes | None:
    """Physischer Inhalt im Bucket (am Register vorbei) - None, wenn das Objekt fehlt."""
    backend = get_object_store().active_backend()
    if backend.head(namespace, key) is None:
        return None
    return b"".join(backend.open_read(namespace, key))


def _present(key: str, namespace: str = MAIN) -> bool:
    return get_object_store().active_backend().head(namespace, key) is not None


def _key() -> str:
    return f"uploads/purge-test/{uuid.uuid4().hex}.txt"


def test_rollback_of_a_delete_keeps_the_object_and_its_registration(db):
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"inhalt")
    db.flush()

    savepoint = db.begin_nested()
    store.delete(db, MAIN, key)
    assert _present(key), "delete darf vor dem Commit nichts physisch entfernen"
    savepoint.rollback()

    assert _raw(key) == b"inhalt"
    assert _registry(db, key).status == "active"
    assert store.purge_deleted(db) == 0
    assert _present(key)


def test_purge_removes_a_deleted_object_and_acknowledges_the_tombstone(db):
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"inhalt")
    store.delete(db, MAIN, key)
    assert _registry(db, key).purge_pending is True
    assert _present(key)

    assert store.purge_deleted(db) >= 1

    assert not _present(key)
    registry = _registry(db, key)
    assert (registry.status, registry.purge_pending) == ("deleted", False)


def test_purge_never_removes_content_written_again_after_the_delete(db):
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"alt")
    store.delete(db, MAIN, key)
    store.put_bytes(db, MAIN, key, b"neu")

    store.purge_deleted(db)

    assert _raw(key) == b"neu"
    registry = _registry(db, key)
    assert (registry.status, registry.purge_pending) == ("active", False)


def test_purge_skips_a_key_that_an_open_writer_is_rewriting(committed_storage):  # noqa: F811
    """Ein Schreiber hat den Key gesperrt und physisch schon neu geschrieben, aber noch nicht
    registriert: der Job darf das neue Objekt nicht löschen und versucht es später erneut."""
    db = committed_storage
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
        # physisch geschrieben, Registrierung steht noch aus
        backend.put_stream(MAIN, key, io.BytesIO(b"neu"), size=3, sha256=hashlib.sha256(b"neu").hexdigest(), content_type=None)

        reaper = SessionLocal()
        try:
            assert store.purge_deleted(reaper) == 0
            reaper.commit()
        finally:
            reaper.close()
        assert _raw(key) == b"neu"
        assert _registry(db, key).purge_pending is True
    finally:
        writer.rollback()
        writer.close()

    get_object_store().active_backend().delete(MAIN, key)
    assert storage_migration_service.purge_deleted_objects(db) == {"purged": 1}
    assert _registry(db, key).purge_pending is False


def test_purge_job_ends_quietly_while_writes_are_fenced(db):
    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"inhalt")
    store.delete(db, MAIN, key)
    db.commit()
    db.execute(text("UPDATE storage_state SET write_fenced = true, fence_reason = 'test' WHERE id = 1"))

    assert storage_migration_service.purge_deleted_objects(db) == {"purged": 0}
    assert _present(key)


def test_purge_also_removes_deleted_abgabebox_objects(db):
    """Die Abgabebox registriert nur (eingeschränkte Rolle); das Backend hat ihren Speicher
    eingebunden und entfernt die Objekte physisch."""
    store = get_object_store()
    key = f"quarantine/tenant-1/{uuid.uuid4().hex}.pdf"
    store.put_bytes(db, "abgabebox", key, b"%PDF")
    store.delete(db, "abgabebox", key)
    assert _present(key, "abgabebox")

    store.purge_deleted(db)

    assert not _present(key, "abgabebox")


def test_deleting_a_document_version_keeps_its_files_until_the_purge(db):
    """DOCMGMT-005: erzeugte Dateien eines Dokuments verschwinden erst nach dem Commit."""
    from app.services import document_service

    store = get_object_store()
    key = _key()
    store.put_bytes(db, MAIN, key, b"%PDF")
    from app.models import StoredFile
    from tests.factories import make_tenant

    tenant = make_tenant(db)
    stored = StoredFile(tenant_id=tenant.id, original_name="x.pdf", mime_type="application/pdf", storage_path=key,
                        file_size_bytes=4, checksum_sha256=None, created_by=None)
    db.add(stored)
    db.flush()

    savepoint = db.begin_nested()
    document_service._delete_generated_files(db, [stored.id])
    savepoint.rollback()
    assert _present(key), "Rollback des Aufrufers: Datei bleibt erhalten"

    document_service._delete_generated_files(db, [stored.id])
    assert _present(key)
    store.purge_deleted(db)
    assert not _present(key)
