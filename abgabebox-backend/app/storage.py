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


def cleanup_stale_quarantine_files(max_age_seconds: int) -> int:
    """Deletes files sitting in quarantine/ longer than max_age_seconds and returns how many
    were removed.

    DECISION (see abgabebox_quarantine_cleanup_loop in app/main.py for the full rationale):
    this is purely filesystem-age-based, with NO database lookup to confirm orphan status.
    The restricted 'hocx_abgabebox' DB role this service runs as has only INSERT on
    submission_upload/submission_upload_file/stored_file - no SELECT at all (see
    backend/alembic/versions/0020_abgabebox.py, "bewusst OHNE jeglichen Zugriff auf
    stored_file/submission_upload_file"), so there is no query this service could run to check
    whether a quarantine file already made it into a DB row. Age-based deletion is therefore the
    only mechanism available here, not a chosen shortcut. This is safe because every quarantine
    file is normally alive for seconds (upload -> ClamAV scan -> move-or-reject, all inside one
    request): a real in-flight upload never gets close to max_age_seconds, so anything still
    there that old can only be debris from a crashed/interrupted request (see public.upload's
    quarantine-then-DB-insert flow) - a real, but never-recovered, file scanned clean and still
    stuck in quarantine (rather than moved to regular storage) is the one case this can't
    distinguish from an orphan; that combination is not expected to occur in practice given the
    request is a single synchronous flow, and the pending-scan/DB-insert-success case is instead
    cleaned up by the main backend's abgabebox_rescan_loop, which does have full DB access.
    """
    quarantine_root = Path(settings.storage_root) / "quarantine"
    if not quarantine_root.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in quarantine_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
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
