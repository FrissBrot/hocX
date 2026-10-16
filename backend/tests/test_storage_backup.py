"""Objekt-Backup (app.workers.storage_backup) bei gleichzeitigen Änderungen (S3-014): ein
während des Laufs geändertes Objekt darf das Backup nicht abbrechen; nur eine echte Abweichung
zwischen Register und Speicher wird gemeldet - und das Manifest wird trotzdem geschrieben."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.core.config import settings
from app.core.storage import MAIN, get_object_store
from app.workers import storage_backup
from tests.storage_support import committed_storage  # noqa: F401


@pytest.fixture
def fs_store(committed_storage, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "export_root", str(tmp_path / "storage" / "exports"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    (tmp_path / "abgabebox").mkdir()
    get_object_store.cache_clear()
    store = get_object_store()
    assert store.active_state(force=True).config.is_filesystem
    yield committed_storage, store
    get_object_store.cache_clear()


def test_object_changed_during_the_backup_is_taken_in_its_new_state(fs_store, tmp_path, monkeypatch):
    db, store = fs_store
    key = "document_templates/bauteil-v1/logo.bin"
    store.put_bytes(db, MAIN, key, b"alter Inhalt")
    db.commit()
    real_download = store.download_to

    def download_after_change(namespace, object_key, path):
        if object_key == key:
            with storage_backup.SessionLocal() as other:
                store.put_bytes(other, MAIN, key, b"neuer Inhalt gleicher Version")
                other.commit()
        return real_download(namespace, object_key, path)

    monkeypatch.setattr(store, "download_to", download_after_change)
    result = storage_backup.backup(tmp_path / "backup")
    assert result["changed"] == 1 and result["mismatched"] == 0
    manifest = json.loads((tmp_path / "backup" / storage_backup.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["objects"][f"main/{key}"]["sha256"] == hashlib.sha256(b"neuer Inhalt gleicher Version").hexdigest()
    assert (tmp_path / "backup" / "objects" / "main" / key).read_bytes() == b"neuer Inhalt gleicher Version"
    assert storage_backup.verify_backup(tmp_path / "backup")["ok"]


def test_real_mismatch_is_reported_without_aborting_the_backup(fs_store, tmp_path):
    db, store = fs_store
    good, bad = "uploads/tenant-1/gut.bin", "uploads/tenant-1/kaputt.bin"
    store.put_bytes(db, MAIN, good, b"gut")
    store.put_bytes(db, MAIN, bad, b"original")
    db.commit()
    store.local_path(MAIN, bad).write_bytes(b"am System vorbei veraendert")
    result = storage_backup.backup(tmp_path / "backup")
    assert result["mismatched"] == 1
    manifest = json.loads((tmp_path / "backup" / storage_backup.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["mismatched"] == [f"main/{bad}"]
    assert f"main/{good}" in manifest["objects"] and f"main/{bad}" not in manifest["objects"]
