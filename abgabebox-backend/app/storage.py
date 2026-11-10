"""Dateiablage der Abgabebox über den gemeinsamen Objektspeicher-Client (objstore_client.py,
generiert aus backend/app/core/objstore_client.py).

Die Abgabebox schreibt ausschliesslich in den Namespace "abgabebox" - bei S3 in einen eigenen
Bucket mit eigenen, eingeschränkten Zugangsdaten (storage_active_config('abgabebox')), beim
bisherigen Dateisystem unter ABGABEBOX_STORAGE_ROOT. Jeder Schreibvorgang läuft über das
Fence-/Journal-Protokoll in der Transaktion der übergebenen Session.
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.objstore_client import ObjectNotFound, ObjectStore, safe_suffix, validate_key

NAMESPACE = "abgabebox"


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    return ObjectStore(
        service="abgabebox",
        connect=engine.connect,
        filesystem_roots=lambda: {NAMESPACE: Path(settings.storage_root)},
        credentials_key=lambda: settings.storage_credentials_key,
    )


def tenant_storage_bytes(db: Session, tenant_id: int) -> int:
    """Belegter Platz dieses Mandanten in der Abgabebox, Quarantäne eingeschlossen (sie belegt
    echten Platz, solange ein Scan aussteht)."""
    store = get_store()
    return store.usage_bytes(db, NAMESPACE, f"tenant-{tenant_id}/") + store.usage_bytes(db, NAMESPACE, f"quarantine/tenant-{tenant_id}/")


def _key(*parts: str, suffix: str) -> str:
    return validate_key("/".join([*parts, f"{uuid4().hex}{safe_suffix('x' + suffix, '.bin')}"]))


def save_file(db: Session, content: bytes, *, tenant_id: int, assignment_id: int, suffix: str) -> tuple[str, str]:
    """Save file to regular storage. Returns (key, checksum_sha256)."""
    key = _key(f"tenant-{tenant_id}", f"assignment-{assignment_id}", suffix=suffix)
    info = get_store().put_bytes(db, NAMESPACE, key, content)
    return key, info.sha256 or ""


def quarantine_target_key(quarantine_rel_path: str) -> str:
    """Pfad-Vertrag Quarantäne -> regulärer Speicher.

    Deliberately duplicated (not shared as a package) from backend/app/services/submission_service.py's
    quarantine_target_key, to keep this public-facing service's dependency surface isolated from the
    main backend. Both are pinned against the same contract in
    backend/tests/fixtures/quarantine_path_parity.json - if you change this transform, update that
    fixture and backend's copy too, and mirror the change here."""
    validate_key(quarantine_rel_path)
    parts = Path(quarantine_rel_path).parts
    if not parts or parts[0] != "quarantine" or len(parts) < 2:
        raise ValueError(f"Expected a quarantine-prefixed path, got {quarantine_rel_path!r}")
    # quarantine/tenant-1/assignment-2/file.pdf -> tenant-1/assignment-2/file.pdf
    return validate_key(Path(*parts[1:]).as_posix())


def move_from_quarantine(db: Session, quarantine_rel_path: str) -> str:
    """Move a file from quarantine to regular storage after a clean scan. Returns new key."""
    target = quarantine_target_key(quarantine_rel_path)
    get_store().move(db, NAMESPACE, quarantine_rel_path, target)
    return target


def save_to_quarantine(db: Session, content: bytes, *, tenant_id: int, assignment_id: int, suffix: str) -> tuple[str, str]:
    """Save file to quarantine. Returns (key, checksum_sha256).

    Quarantine keys look like: quarantine/tenant-1/assignment-2/<uuid>.pdf - the main backend
    reaches them through the same namespace when rescanning."""
    key = _key("quarantine", f"tenant-{tenant_id}", f"assignment-{assignment_id}", suffix=suffix)
    info = get_store().put_bytes(db, NAMESPACE, key, content)
    return key, info.sha256 or ""


def delete_object(db: Session, key: str) -> None:
    get_store().delete(db, NAMESPACE, key)


def cleanup_stale_quarantine_files(db: Session, max_age_seconds: int, *, is_referenced=None) -> int:
    """Nur nachweislich verwaiste Dateien löschen; DB-Ausfall darf keine Daten löschen."""
    if is_referenced is None:
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    store = get_store()
    for info in list(store.list(NAMESPACE, "quarantine/")):
        if info.size < 0 or info.last_modified is None or info.last_modified.timestamp() >= cutoff:
            continue
        if is_referenced(info.key):
            continue
        try:
            store.delete(db, NAMESPACE, info.key)
            db.commit()
            removed += 1
        except ObjectNotFound:
            db.rollback()
    return removed
