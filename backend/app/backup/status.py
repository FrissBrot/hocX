"""Vom Worker ermittelter Zustand für Anzeige (Admin-Portal) und Monitoring (system_health_service).
Das Backend selbst hat keinen Zugang zum Repository - es liest nur, was hier steht."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import BackupSettings


def settings_row(db: Session) -> BackupSettings:
    row = db.get(BackupSettings, 1, populate_existing=True)
    if row is None:  # Migration legt die Zeile an - nur Schutz gegen manuell geleerte Tabelle
        row = BackupSettings(id=1)
        db.add(row)
        db.flush()
    return row


def record_repository_status(db: Session, env: Any, *, ok: bool, info: dict[str, Any] | None = None,
                             error_code: str | None = None, error: str | None = None) -> None:
    row = settings_row(db)
    previous = dict(row.repository_status or {})
    now = datetime.now(UTC)
    status: dict[str, Any] = {
        "ok": ok,
        "checked_at": now.isoformat(),
        "error_code": error_code,
        "error": (error or "")[:500] or None,
        "last_ok_at": now.isoformat() if ok else previous.get("last_ok_at"),
        "borg_version": previous.get("borg_version"),
    }
    try:
        status["borg_version"] = env.borg.version()
    except Exception:  # noqa: BLE001 - reine Anzeige
        pass
    if info:
        cache = (info.get("cache") or {}).get("stats") or {}
        status.update({
            "repository_id": (info.get("repository") or {}).get("id"),
            "encryption": (info.get("encryption") or {}).get("mode"),
            "stored_bytes": cache.get("unique_csize"),
            "original_bytes": cache.get("total_size"),
            "deduplicated_bytes": cache.get("unique_size"),
        })
    else:
        for key in ("repository_id", "encryption", "stored_bytes", "original_bytes", "deduplicated_bytes"):
            status[key] = previous.get(key)
    quota = env.config.quota_bytes
    status["quota_bytes"] = quota
    status["used_percent"] = round(status["stored_bytes"] / quota * 100, 1) if quota and status.get("stored_bytes") else None
    try:
        env.config.staging_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(env.config.staging_dir)
        status["staging_free_bytes"] = usage.free
        status["staging_total_bytes"] = usage.total
    except OSError:
        status["staging_free_bytes"] = None
    row.repository_status = status
    row.repository_checked_at = now
    row.worker_config = env.config.public_summary()
    db.commit()


def update_repository_status(db: Session, **values: Any) -> None:
    row = settings_row(db)
    row.repository_status = {**(row.repository_status or {}), **values}
    db.commit()
