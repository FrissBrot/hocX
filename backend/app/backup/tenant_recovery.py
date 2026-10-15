"""Mandanten-Restore als KOPIE: ein Mandant aus einem historischen Sicherungspunkt wird als neuer
Mandant in die aktuelle Installation importiert. Der bestehende Mandant bleibt unberührt.

Datenquelle ist ausschliesslich der Sicherungspunkt: der Dump wird in eine isolierte temporäre
Datenbank eingespielt (nie gegen die Live-Datenbank gelesen), die Dateien kommen direkt aus Borg
(nie aus dem aktuellen Objektspeicher). Statt eines ZIP (2-GiB-Grenze des normalen Imports)
werden die Inhalte gestreamt in einen temporären Bereich des aktiven Speichers geschrieben
(_hocx-restore/<auftrag>/<sha256>) und beim Import serverseitig an ihren endgültigen Key kopiert.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.objstore_client import RESTORE_STAGING_PREFIX, Backend, ObjectNotFound
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import ImportFileSource

_logger = logging.getLogger("hocx.backup.tenant_recovery")

# Beziehungen zu ANDEREN Mandanten und global eindeutige Zuordnungen werden bei einer Kopie nie
# übernommen: sonst bekäme die Kopie Freigaben/Vertrauen, die der Partner nur dem Original
# gegeben hat, bzw. würde eine Domain des Originals beanspruchen.
COPY_EXCLUDED_TABLES = ("tenant_trust", "photo_album_tenant_share", "tenant_domain")


def staging_key(job_id: Any, sha256: str) -> str:
    return f"{RESTORE_STAGING_PREFIX}{job_id.hex}/{sha256}"


class HistoricalTenantExport(TenantExportService):
    """Export-Logik gegen die temporäre historische Datenbank; ob eine Datei existiert, sagt das
    Manifest des Sicherungspunkts - nicht der aktuelle Objektspeicher."""

    def __init__(self, available: set[tuple[str, str]]) -> None:
        super().__init__()
        self._available = available

    def object_exists(self, namespace: str, key: str) -> bool:
        return (namespace, key) in self._available


def prepare_copy_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    tables = dict(manifest.get("tables") or {})
    removed = [name for name in COPY_EXCLUDED_TABLES if tables.get(name)]
    for name in COPY_EXCLUDED_TABLES:
        tables[name] = []
    return {**manifest, "tables": tables}, removed


class RecoveryFileSource(ImportFileSource):
    """Dateien des Imports liegen bereits (nach SHA-256 benannt) im Restore-Bereich des aktiven
    Speichers. members: member_name -> (namespace, sha256, size) aus Export + Manifest."""

    def __init__(self, store: Any, backend: Backend, job_id: Any, members: dict[str, tuple[str, str, int]], work_dir: Path) -> None:
        self.object_store = store
        self.backend = backend
        self.job_id = job_id
        self.members = members
        self.work_dir = work_dir
        self.stored = 0

    def exists(self, member: str) -> bool:
        return member in self.members

    def store(self, db: Session, namespace: str, key: str, member: str) -> bool:  # type: ignore[override]
        found = self.members.get(member)
        if found is None:
            return False
        source_namespace, sha, _size = found
        source_key = staging_key(self.job_id, sha)
        if source_namespace == namespace:
            # Registriert den Ziel-Key in der Transaktion des Imports (begin_write/register_write).
            self.object_store.copy(db, namespace, source_key, key)
        else:
            with self.object_store.local_copy(source_namespace, source_key, work_dir=self.work_dir) as path:
                self.object_store.put_file(db, namespace, key, path)
        self.stored += 1
        return True

    @contextlib.contextmanager
    def local_file(self, member: str) -> Iterator[Path]:  # type: ignore[override]
        """Temporäre lokale Kopie einer einzelnen Datei (Virenprüfung) - höchstens eine zugleich."""
        found = self.members.get(member)
        if found is None:
            raise ObjectNotFound(member)
        namespace, sha, _size = found
        with self.object_store.local_copy(namespace, staging_key(self.job_id, sha), work_dir=self.work_dir) as path:
            yield path


def purge_staging(backend: Backend, job_id: Any) -> int:
    prefix = f"{RESTORE_STAGING_PREFIX}{job_id.hex}/"
    removed = 0
    for namespace in ("main", "abgabebox"):
        for info in list(backend.list(namespace, prefix)):
            if info.key.startswith(prefix):
                backend.delete(namespace, info.key)
                removed += 1
    return removed
