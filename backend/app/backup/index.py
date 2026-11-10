"""Inhaltsindex (backup_content/backup_pool_archive): welcher Inhalt (SHA-256) liegt bereits in
welchem Pool-Archiv. Er ist nur ein Cache des Repository-Zustands - reconcile() gleicht ihn vor
jeder Nutzung gegen das Repository ab, damit ein veralteter Index (DB-Restore, abgebrochener
Lauf, Garbage Collection) nie dazu führt, dass ein Manifest auf fehlenden Inhalt verweist."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.backup.manifest import POOL_NAME
from app.backup.repository import RepositoryView
from app.models import BackupContent, BackupPoolArchive

_logger = logging.getLogger("hocx.backup.index")
_CHUNK = 1000


class ContentIndex:
    def __init__(self, db: Session) -> None:
        self.db = db

    def lookup(self, shas: Iterable[str]) -> dict[str, str]:
        """sha256 -> Pool-Archiv für alle aktiven (nicht zur Bereinigung markierten) Inhalte."""
        result: dict[str, str] = {}
        unique = sorted({sha for sha in shas if sha})
        for start in range(0, len(unique), _CHUNK):
            chunk = unique[start:start + _CHUNK]
            rows = self.db.execute(
                select(BackupContent.sha256, BackupContent.pool_archive)
                .join(BackupPoolArchive, BackupPoolArchive.name == BackupContent.pool_archive)
                .where(BackupContent.sha256.in_(chunk), BackupContent.state == "active", BackupPoolArchive.state == "active")
            ).all()
            result.update({row.sha256: row.pool_archive for row in rows})
        return result

    def add_pool(self, name: str, archive_id: str | None, contents: dict[str, int], *, backup_set_id: uuid.UUID | None) -> None:
        if not POOL_NAME.match(name):
            raise ValueError("Ungültiger Pool-Name")
        self.db.execute(text("""
            INSERT INTO backup_pool_archive (name, archive_id, backup_set_id, state, object_count, total_bytes)
            VALUES (:name, :aid, :bsid, 'active', :count, :bytes)
            ON CONFLICT (name) DO UPDATE SET archive_id = EXCLUDED.archive_id, state = 'active',
              object_count = EXCLUDED.object_count, total_bytes = EXCLUDED.total_bytes, updated_at = NOW()
        """), {"name": name, "aid": archive_id, "bsid": backup_set_id, "count": len(contents), "bytes": sum(contents.values())})
        rows = [{"sha256": sha, "size": size} for sha, size in contents.items()]
        for start in range(0, len(rows), _CHUNK):
            # Liegt ein Inhalt schon in einem anderen Pool (Doppelung nach Abbruch), bleibt der
            # erste Eintrag - beide Pools enthalten ihn tatsächlich.
            self.db.execute(text("""
                INSERT INTO backup_content (sha256, size_bytes, pool_archive, state)
                SELECT x.sha256, x.size, :pool, 'active' FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(sha256 text, size bigint)
                ON CONFLICT (sha256) DO UPDATE SET pool_archive = EXCLUDED.pool_archive, state = 'active'
                WHERE backup_content.state <> 'active'
            """), {"pool": name, "rows": json.dumps(rows[start:start + _CHUNK])})

    def reconcile(self, view: RepositoryView) -> dict[str, Any]:
        """Abgleich mit dem Repository:
        - Pools, die es im Repository nicht (mehr) gibt -> Einträge entfernen (Inhalt wird beim
          nächsten Backup neu übertragen).
        - Pools mit abweichender Archiv-ID (recreate) oder offenen gc_pending-Einträgen -> Inhalt
          neu einlesen.
        - Pools im Repository ohne Index-Eintrag (Index älter als Repository) -> übernehmen; ihre
          Inhalte sind vollständig (borg legt ein Archiv nur nach erfolgreichem Ende an) und
          tragen den SHA-256 im Pfad, der beim Schreiben geprüft wurde.
        - Borg-Checkpoints abgebrochener Läufe werden gemeldet (Bereinigung durch die Retention)."""
        repo = view.pool_archives()
        known = {row.name: row for row in self.db.scalars(select(BackupPoolArchive))}
        report = {"removed": 0, "relisted": 0, "adopted": 0, "checkpoints": view.checkpoint_archives()}
        pending = set(self.db.scalars(select(BackupContent.pool_archive).where(BackupContent.state == "gc_pending").distinct()))
        for name, row in known.items():
            if name not in repo:
                self.db.execute(delete(BackupContent).where(BackupContent.pool_archive == name))
                self.db.execute(delete(BackupPoolArchive).where(BackupPoolArchive.name == name))
                report["removed"] += 1
            elif row.archive_id != repo[name] or name in pending or row.state != "active":
                contents = view.pool_contents(name)
                self.db.execute(delete(BackupContent).where(BackupContent.pool_archive == name))
                self.add_pool(name, repo[name], contents, backup_set_id=row.backup_set_id)
                report["relisted"] += 1
        for name, archive_id in repo.items():
            if name not in known:
                self.add_pool(name, archive_id, view.pool_contents(name), backup_set_id=None)
                report["adopted"] += 1
        self.db.commit()
        return report

    def mark_gc_pending(self, shas: Iterable[str]) -> None:
        unique = sorted(set(shas))
        for start in range(0, len(unique), _CHUNK):
            self.db.execute(update(BackupContent).where(BackupContent.sha256.in_(unique[start:start + _CHUNK])).values(state="gc_pending"))

    def remove(self, shas: Iterable[str]) -> None:
        unique = sorted(set(shas))
        for start in range(0, len(unique), _CHUNK):
            self.db.execute(delete(BackupContent).where(BackupContent.sha256.in_(unique[start:start + _CHUNK])))
