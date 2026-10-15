"""Backup-Hold (Migration 0115): Copy-on-Write vor Löschen/Überschreiben registrierter Objekte,
damit ein laufendes Backup jeden Inhalt seines Snapshots findet."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
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


def test_delete_under_hold_preserves_the_registered_content(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"original")
    hold = _set_hold(db)
    store.delete(db, MAIN, key)
    sha = hashlib.sha256(b"original").hexdigest()
    preserved = tmp_path / backup_hold_key(hold, sha)
    assert preserved.read_bytes() == b"original"
    assert not (tmp_path / key).exists()


def test_overwrite_under_hold_preserves_the_previous_version_once(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = f"document_template_parts/{uuid.uuid4().hex}.tex"
    store.put_bytes(db, MAIN, key, b"v1")
    hold = _set_hold(db)
    store.put_bytes(db, MAIN, key, b"v2")
    store.put_bytes(db, MAIN, key, b"v3")
    assert (tmp_path / backup_hold_key(hold, hashlib.sha256(b"v1").hexdigest())).read_bytes() == b"v1"
    # v2 war nie Teil eines Snapshots vor dem Hold, wird aber beim Überschreiben ebenfalls nach
    # Inhalt gesichert - das Backup findet jeden Zwischenstand über seinen SHA-256.
    assert (tmp_path / backup_hold_key(hold, hashlib.sha256(b"v2").hexdigest())).read_bytes() == b"v2"
    assert (tmp_path / key).read_bytes() == b"v3"


def test_without_hold_nothing_is_copied(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"x")
    store.delete(db, MAIN, key)
    assert not (tmp_path / "_hocx-backup-hold").exists()


def test_hold_on_another_generation_does_not_copy(db, tmp_path, monkeypatch):
    """Nach einem Cutover liegt der Hold auf der alten Generation - Schreiber der neuen müssen
    nichts sichern, die alte Generation ist eingefroren."""
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"x")
    _set_hold(db, generation=987654)
    store.delete(db, MAIN, key)
    assert not (tmp_path / "_hocx-backup-hold").exists()


def test_failed_preservation_aborts_the_destructive_write(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"keep me")
    _set_hold(db)
    backend = store.active_backend()

    def broken_copy(*_args, **_kwargs):
        raise StorageUnavailable("simulated")

    monkeypatch.setattr(backend, "copy", broken_copy)
    with pytest.raises(StorageUnavailable):
        store.delete(db, MAIN, key)
    assert (tmp_path / key).read_bytes() == b"keep me"


def test_internal_prefixes_are_recognised():
    assert is_internal_key("_hocx-backup-hold/abc/def")
    assert is_internal_key("_hocx-restore/job/x")
    assert not is_internal_key("uploads/tenant-1/a.jpg")
    with pytest.raises(ValueError):
        backup_hold_key(uuid.uuid4(), "../../etc/passwd")
