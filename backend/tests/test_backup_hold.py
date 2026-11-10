"""Backup-Hold (Migration 0115): Copy-on-Write vor Löschen/Überschreiben registrierter Objekte,
damit ein laufendes Backup jeden Inhalt seines Snapshots findet."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text

from app.core.objstore_client import StorageUnavailable, backup_hold_key, is_internal_key
from app.core.storage import get_object_store

MAIN = "main"


def _set_hold(db, generation: int | None = None) -> uuid.UUID:
    hold = uuid.uuid4()
    db.execute(
        text("UPDATE storage_state SET backup_hold_id = :h, backup_hold_generation = COALESCE(:g, active_generation), backup_hold_since = NOW() WHERE id = 1"),
        {"h": hold, "g": generation},
    )
    return hold


def _physical(store, key: str) -> bytes | None:
    """Inhalt direkt aus dem Bucket (am Register vorbei) - None, wenn physisch nicht vorhanden."""
    backend = store.active_backend()
    if backend.head(MAIN, key) is None:
        return None
    return b"".join(backend.open_read(MAIN, key))


def _hold_keys(store, prefix: str = "_hocx-backup-hold/") -> set[str]:
    return {info.key for info in store.active_backend().list(MAIN, prefix)}


def test_delete_under_hold_preserves_the_registered_content(db, monkeypatch):
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"original")
    hold = _set_hold(db)
    store.delete(db, MAIN, key)
    sha = hashlib.sha256(b"original").hexdigest()
    preserved = backup_hold_key(hold, sha)
    # S3-008: delete ist nur ein Tombstone, das Objekt bleibt bis zum Purge-Job liegen.
    assert _physical(store, key) == b"original"
    # Release 1.2.0 (Migration 0123): der Purge-Job sichert den Tombstone vor dem physischen
    # Löschen in den Hold - vorher fand storage_backup_hold() nur aktive Objekte.
    assert store.purge_deleted(db) >= 1
    assert _physical(store, preserved) == b"original"
    assert _physical(store, key) is None


def test_overwrite_under_hold_preserves_the_previous_version_once(db, monkeypatch):
    store = get_object_store()
    key = f"document_assets/test/{uuid.uuid4().hex}.png"
    store.put_bytes(db, MAIN, key, b"v1")
    hold = _set_hold(db)
    store.put_bytes(db, MAIN, key, b"v2")
    store.put_bytes(db, MAIN, key, b"v3")
    assert _physical(store, backup_hold_key(hold, hashlib.sha256(b"v1").hexdigest())) == b"v1"
    # v2 war nie Teil eines Snapshots vor dem Hold, wird aber beim Überschreiben ebenfalls nach
    # Inhalt gesichert - das Backup findet jeden Zwischenstand über seinen SHA-256.
    assert _physical(store, backup_hold_key(hold, hashlib.sha256(b"v2").hexdigest())) == b"v2"
    assert _physical(store, key) == b"v3"


def test_without_hold_nothing_is_copied(db, monkeypatch):
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"x")
    before = _hold_keys(store)
    store.delete(db, MAIN, key)
    store.purge_deleted(db)
    assert _physical(store, key) is None
    # Der Bucket ist über Testläufe geteilt: es darf nur nichts Neues im Hold-Bereich entstehen.
    assert _hold_keys(store) == before


def test_hold_on_another_generation_does_not_copy(db, monkeypatch):
    """Nach einem Cutover liegt der Hold auf der alten Generation - Schreiber der neuen müssen
    nichts sichern, die alte Generation ist eingefroren."""
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"x")
    hold = _set_hold(db, generation=987654)
    store.delete(db, MAIN, key)
    store.purge_deleted(db)
    assert _hold_keys(store, f"_hocx-backup-hold/{hold.hex}/") == set()


def test_failed_preservation_aborts_the_destructive_write(db, monkeypatch):
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"keep me")
    _set_hold(db)
    backend = store.active_backend()

    def broken_copy(*_args, **_kwargs):
        raise StorageUnavailable("simulated")

    monkeypatch.setattr(backend, "copy", broken_copy)
    # S3-008: delete ist nur ein Tombstone; zerstörerisch ist erst der Purge-Job - scheitert die
    # Sicherung in den Hold, bricht er ab und das Objekt bleibt erhalten.
    store.delete(db, MAIN, key)
    with pytest.raises(StorageUnavailable):
        store.purge_deleted(db)
    assert _physical(store, key) == b"keep me"


def test_internal_prefixes_are_recognised():
    assert is_internal_key("_hocx-backup-hold/abc/def")
    assert is_internal_key("_hocx-restore/job/x")
    assert not is_internal_key("uploads/tenant-1/a.jpg")
    with pytest.raises(ValueError):
        backup_hold_key(uuid.uuid4(), "../../etc/passwd")
