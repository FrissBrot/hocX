from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from app.config import settings


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
    """Move a file from quarantine to regular storage after a clean scan. Returns new relative path."""
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
