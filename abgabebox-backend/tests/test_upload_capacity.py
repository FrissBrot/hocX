"""Quarantäne darf bei Scanner-Ausfall keine registrierten Uploads verlieren."""
import uuid

from app import storage, scanner
from app.db import SessionLocal


def test_quarantine_cleanup_protects_referenced_files_and_fails_closed(monkeypatch):
    store = storage.get_store()
    run = uuid.uuid4().hex[:8]
    pending = f'quarantine/tenant-1/{run}-pending.pdf'
    orphan = f'quarantine/tenant-1/{run}-orphan.pdf'
    with SessionLocal() as db:
        store.put_bytes(db, storage.NAMESPACE, pending, b'pending')
        store.put_bytes(db, storage.NAMESPACE, orphan, b'orphan')
        db.commit()
    registered: list[str] = []
    real_delete = store.delete

    def spy(db, namespace, key):
        real_delete(db, namespace, key)  # registriert den Tombstone (eigene Rolle darf das Register nicht lesen)
        registered.append(f'{namespace}/{key}')

    monkeypatch.setattr(store, 'delete', spy)
    # max_age -60: die eben geschriebenen Objekte gelten als «alt» (Alter kommt aus LastModified).
    with SessionLocal() as db:
        # Ohne Referenzprüfung (DB-Ausfall) wird nichts gelöscht - fail closed.
        assert storage.cleanup_stale_quarantine_files(db, -60) == 0
        assert store.exists(storage.NAMESPACE, pending) and store.exists(storage.NAMESPACE, orphan)
        removed = storage.cleanup_stale_quarantine_files(db, -60, is_referenced=lambda key: not key.endswith(f'{run}-orphan.pdf'))
    # S3-008: die Abgabebox registriert nur die Löschung (committet), physisch entfernt sie der
    # Backend-Job storage_purge danach.
    assert removed == 1
    assert registered == [f'abgabebox/{orphan}']
    assert store.exists(storage.NAMESPACE, pending) and store.exists(storage.NAMESPACE, orphan)


def test_scanner_errors_are_not_malware(monkeypatch):
    import pyclamd
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, "__init__", lambda *a, **k: None)
    monkeypatch.setattr(pyclamd.ClamdNetworkSocket, 'scan_stream', lambda *a: {'stream': ('ERROR', 'limit')})
    assert scanner.scan_bytes(b'file', host='unused') == 'error'
