"""Quarantäne darf bei Scanner-Ausfall keine registrierten Uploads verlieren."""
import os
import time

from app import storage, scanner
from app.config import settings
from app.db import SessionLocal


def test_quarantine_cleanup_protects_referenced_files_and_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'storage_root', str(tmp_path))
    root = tmp_path / 'quarantine' / 'tenant-1'
    root.mkdir(parents=True)
    pending = root / 'pending.pdf'
    orphan = root / 'orphan.pdf'
    pending.write_bytes(b'pending')
    orphan.write_bytes(b'orphan')
    for path in (pending, orphan):
        os.utime(path, (time.time() - 10000, time.time() - 10000))
    store = storage.get_store()
    registered: list[str] = []
    real_delete = store.delete

    def spy(db, namespace, key):
        real_delete(db, namespace, key)  # registriert den Tombstone (eigene Rolle darf das Register nicht lesen)
        registered.append(f'{namespace}/{key}')

    monkeypatch.setattr(store, 'delete', spy)
    with SessionLocal() as db:
        assert storage.cleanup_stale_quarantine_files(db, 100) == 0
        assert pending.exists() and orphan.exists()
        assert storage.cleanup_stale_quarantine_files(db, 100, is_referenced=lambda path: path.endswith('pending.pdf')) == 1
    # S3-008: die Abgabebox registriert nur die Löschung (committet), physisch entfernt sie der
    # Backend-Job storage_purge danach (das Backend hat den Abgabebox-Speicher eingebunden).
    assert registered == ['abgabebox/quarantine/tenant-1/orphan.pdf']
    assert pending.exists() and orphan.exists()


def test_scanner_errors_are_not_malware(monkeypatch):
    import pyclamd
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, "__init__", lambda *a, **k: None)
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, 'scan_stream', lambda *a: {'stream': ('ERROR', 'limit')})
    assert scanner.scan_bytes(b'file', host='unused') == 'error'
