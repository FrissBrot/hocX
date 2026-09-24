from __future__ import annotations

import hashlib
import time
from pathlib import Path
from uuid import uuid4

from app.config import settings


def tenant_storage_bytes(tenant_id: int) -> int:
    """Sum of everything currently on disk for this tenant, quarantine included (it still
    occupies real space while a scan is pending/stuck)."""
    total = 0
    for root in (
        Path(settings.storage_root) / f"tenant-{tenant_id}",
        Path(settings.storage_root) / "quarantine" / f"tenant-{tenant_id}",
    ):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
    return total


def save_file(content: bytes, *, tenant_id: int, assignment_id: int, suffix: str) -> tuple[str, str]:
    """Save file to regular storage. Returns (relative_path, checksum_sha256)."""
    storage_dir = Path(settings.storage_root) / f"tenant-{tenant_id}" / f"assignment-{assignment_id}"
    storage_dir.mkdir(parents=True, exist_ok=True)
    generated_name = f"{uuid4().hex}{suffix}"
    target_path = storage_dir / generated_name
    target_path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    return str(target_path.relative_to(settings.storage_root)), checksum


def move_from_quarantine(quarantine_rel_path: str) -> str:
    """Move a file from quarantine to regular storage after a clean scan. Returns new relative path.

    Deliberately duplicated (not shared as a package) from backend/app/services/submission_service.py's
    _move_from_quarantine, to keep this public-facing service's dependency surface isolated from the
    main backend. Both are pinned against the same contract in
    backend/tests/fixtures/quarantine_path_parity.json - if you change this transform, update that
    fixture and backend's copy too, and mirror the change here."""
    q_full = Path(settings.storage_root) / quarantine_rel_path
    # quarantine/tenant-1/assignment-2/file.pdf -> tenant-1/assignment-2/file.pdf
    parts = Path(quarantine_rel_path).parts
    new_rel = str(Path(*parts[1:]))
    new_full = Path(settings.storage_root) / new_rel
    new_full.parent.mkdir(parents=True, exist_ok=True)
    q_full.rename(new_full)
    return new_rel


def save_to_quarantine(content: bytes, *, tenant_id: int, assignment_id: int, suffix: str) -> tuple[str, str]:
    """Save file to quarantine subdirectory. Returns (relative_path, checksum_sha256).

    Quarantine paths look like: quarantine/tenant-1/assignment-2/<uuid>.pdf
    They live under the same storage_root so the main backend can reach them via
    its abgabebox-storage mount when rescanning.
    """
    qdir = (
        Path(settings.storage_root)
        / "quarantine"
        / f"tenant-{tenant_id}"
        / f"assignment-{assignment_id}"
    )
    qdir.mkdir(parents=True, exist_ok=True)
    generated_name = f"{uuid4().hex}{suffix}"
    target_path = qdir / generated_name
    target_path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    return str(target_path.relative_to(settings.storage_root)), checksum


def cleanup_stale_quarantine_files(max_age_seconds: int, *, is_referenced=None) -> int:
    """Nur nachweislich verwaiste Dateien löschen; DB-Ausfall darf keine Daten löschen."""
    if is_referenced is None:
        return 0
    quarantine_root = Path(settings.storage_root) / "quarantine"
    if not quarantine_root.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in quarantine_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff and not is_referenced(str(path.relative_to(settings.storage_root))):
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    # Best-effort tidy-up of now-empty tenant-/assignment- subdirectories left behind.
    for path in sorted(quarantine_root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    return removed
