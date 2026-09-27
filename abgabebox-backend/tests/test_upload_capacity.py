"""Quarantäne darf bei Scanner-Ausfall keine registrierten Uploads verlieren."""
import os
import time

from app import storage, scanner
from app.config import settings


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
    assert storage.cleanup_stale_quarantine_files(100) == 0
    assert pending.exists() and orphan.exists()
    assert storage.cleanup_stale_quarantine_files(100, is_referenced=lambda path: path.endswith('pending.pdf')) == 1
    assert pending.exists() and not orphan.exists()


def test_scanner_errors_are_not_malware(monkeypatch):
    import pyclamd
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, "__init__", lambda *a, **k: None)
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, 'scan_stream', lambda *a: {'stream': ('ERROR', 'limit')})
    assert scanner.scan_bytes(b'file', host='unused') == 'error'
