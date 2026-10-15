"""Format der Wiederherstellungspunkte im Borg-Repository (siehe architektur.md).

rp-Archiv  hocx-rp-<YYYYMMDDTHHMMSSZ>-<backup-id>:
  hocx-backup.json     Metadaten (Version, Schema, Generation, Zähler, Prüfsummen, Mandanten)
  manifest.jsonl.gz    vollständige Objektliste: eine Kopfzeile, dann je Objekt
                       {"ns","key","size","sha256","version","pool"}
  db/hocx.pgdump       pg_dump -Fc desselben Snapshots
  db/globals.sql       Rollen (ohne Passwörter), sofern lesbar
  recovery/README.txt  Kurzanleitung für den Notfall
pool-Archiv hocx-pool-<backup-id>-<nnnn>: pool/<sha[0:2]>/<sha256>

Alles, was hier gelesen wird, kommt aus dem Repository und wird wie fremde Eingabe geprüft
(Keys, Namespaces, Hashes, Archivnamen) - auch wenn wir es selbst geschrieben haben.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from app.core.objstore_client import NAMESPACES, validate_key

FORMAT = "hocx-backup"
MANIFEST_FORMAT = "hocx-backup-manifest"
FORMAT_VERSION = 1
RP_PREFIX = "hocx-rp-"
POOL_PREFIX = "hocx-pool-"
METADATA_PATH = "hocx-backup.json"
MANIFEST_PATH = "manifest.jsonl.gz"
DUMP_PATH = "db/hocx.pgdump"
GLOBALS_PATH = "db/globals.sql"
README_PATH = "recovery/README.txt"

RP_NAME = re.compile(r"^hocx-rp-(\d{8}T\d{6}Z)-([0-9a-f]{32})(\.invalid)?$")
POOL_NAME = re.compile(r"^hocx-pool-([0-9a-f]{32})-(\d{4})$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_LINE = 8192


class ManifestError(ValueError):
    pass


def rp_archive_name(snapshot_at: datetime, backup_id: uuid.UUID) -> str:
    return f"{RP_PREFIX}{snapshot_at.astimezone(UTC):%Y%m%dT%H%M%SZ}-{backup_id.hex}"


def parse_rp_name(name: str) -> tuple[datetime, uuid.UUID, bool] | None:
    match = RP_NAME.match(name)
    if not match:
        return None
    when = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return when, uuid.UUID(match.group(2)), bool(match.group(3))


def pool_archive_name(backup_id: uuid.UUID, index: int) -> str:
    if not 0 <= index <= 9999:
        raise ManifestError("Zu viele Pool-Archive in einem Lauf")
    return f"{POOL_PREFIX}{backup_id.hex}-{index:04d}"


def pool_path(sha256: str) -> str:
    if not _HEX64.match(sha256 or ""):
        raise ManifestError("Ungültiger SHA-256")
    return f"pool/{sha256[:2]}/{sha256}"


def sha_from_pool_path(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "pool" and _HEX64.match(parts[2]) and parts[1] == parts[2][:2]:
        return parts[2]
    return None


@dataclass(frozen=True)
class ManifestEntry:
    namespace: str
    key: str
    size: int
    sha256: str
    version: int
    pool: str

    def to_json(self) -> str:
        return json.dumps({"ns": self.namespace, "key": self.key, "size": self.size, "sha256": self.sha256,
                           "version": self.version, "pool": self.pool}, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "ManifestEntry":
        namespace, key, size, sha, version, pool = (data.get(k) for k in ("ns", "key", "size", "sha256", "version", "pool"))
        if namespace not in NAMESPACES:
            raise ManifestError("Ungültiger Namespace im Manifest")
        try:
            validate_key(key)
        except ValueError as exc:
            raise ManifestError("Ungültiger Key im Manifest") from exc
        if not isinstance(size, int) or size < 0 or not isinstance(version, int) or version < 0:
            raise ManifestError("Ungültige Grösse/Version im Manifest")
        if not isinstance(sha, str) or not _HEX64.match(sha):
            raise ManifestError("Ungültiger SHA-256 im Manifest")
        if not isinstance(pool, str) or not POOL_NAME.match(pool):
            raise ManifestError("Ungültiges Pool-Archiv im Manifest")
        return cls(namespace, key, size, sha, version, pool)


class _HashingWriter(io.RawIOBase):
    def __init__(self, target: IO[bytes]) -> None:
        self.target = target
        self.digest = hashlib.sha256()
        self.size = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # type: ignore[override]
        data = bytes(data)
        self.digest.update(data)
        self.size += len(data)
        self.target.write(data)
        return len(data)


class ManifestWriter:
    """Schreibt das Manifest gzip-komprimiert in eine Datei und rechnet den SHA-256 der Datei mit."""

    def __init__(self, path: Path, *, backup_id: uuid.UUID, generation: int) -> None:
        self.path = path
        self._file = path.open("wb")
        self._hasher = _HashingWriter(self._file)
        self._gzip = gzip.GzipFile(fileobj=self._hasher, mode="wb", mtime=0)
        self.count = 0
        self.total_bytes = 0
        self._write({"format": MANIFEST_FORMAT, "version": FORMAT_VERSION, "backup_id": str(backup_id), "generation": generation})

    def _write(self, data: dict[str, Any]) -> None:
        self._gzip.write((json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))

    def add(self, entry: ManifestEntry) -> None:
        self._gzip.write((entry.to_json() + "\n").encode("utf-8"))
        self.count += 1
        self.total_bytes += entry.size

    def close(self) -> str:
        self._gzip.close()
        self._file.flush()
        self._file.close()
        return self._hasher.digest.hexdigest()


def read_manifest(stream: IO[bytes]) -> tuple[dict[str, Any], Iterator[ManifestEntry]]:
    """Liest Kopfzeile und liefert die Einträge lazy (Manifeste können Millionen Zeilen haben)."""
    reader = gzip.GzipFile(fileobj=stream, mode="rb")
    first = reader.readline(_MAX_LINE)
    try:
        header = json.loads(first)
    except ValueError as exc:
        raise ManifestError("Manifest-Kopf nicht lesbar") from exc
    if header.get("format") != MANIFEST_FORMAT or header.get("version") != FORMAT_VERSION:
        raise ManifestError("Unbekanntes Manifest-Format")

    def entries() -> Iterator[ManifestEntry]:
        seen: set[tuple[str, str]] = set()
        while True:
            line = reader.readline(_MAX_LINE + 1)
            if not line:
                return
            if len(line) > _MAX_LINE:
                raise ManifestError("Manifest-Zeile zu lang")
            try:
                entry = ManifestEntry.parse(json.loads(line))
            except ValueError as exc:
                raise ManifestError(f"Manifest-Zeile ungültig: {exc}") from exc
            if (entry.namespace, entry.key) in seen:
                raise ManifestError("Doppelter Key im Manifest")
            seen.add((entry.namespace, entry.key))
            yield entry

    return header, entries()


def build_metadata(**values: Any) -> dict[str, Any]:
    return {"format": FORMAT, "format_version": FORMAT_VERSION, **values}


def parse_metadata(raw: bytes) -> dict[str, Any]:
    if len(raw) > 16 * 1024 * 1024:
        raise ManifestError("Metadaten zu gross")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ManifestError("Metadaten nicht lesbar") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ManifestError("Kein hocX-Backup")
    if data.get("format_version") != FORMAT_VERSION:
        raise ManifestError(f"Nicht unterstützte Backup-Version {data.get('format_version')!r}")
    for field in ("backup_id", "snapshot_at", "manifest_sha256", "db_dump_sha256", "object_count"):
        if field not in data:
            raise ManifestError(f"Metadaten unvollständig: {field}")
    return data


RECOVERY_README = """hocX-Wiederherstellungspunkt (BorgBackup)

Dieses Archiv enthält einen vollständigen, konsistenten Stand von hocX:
  hocx-backup.json     Metadaten (hocX-Version, Alembic-Revision, Generation, Prüfsummen)
  manifest.jsonl.gz    alle Objekte (namespace, key, Grösse, SHA-256, Pool-Archiv)
  db/hocx.pgdump       PostgreSQL-Dump (pg_dump -Fc) desselben Snapshots
Die Objektinhalte liegen inhaltsadressiert in den Archiven hocx-pool-*.

Wiederherstellung ohne laufendes hocX (neuer Server):
  docker compose run --rm backup-worker python -m app.backup.cli list
  docker compose run --rm backup-worker python -m app.backup.cli restore-full --archive <NAME> ...
Ausführlich: docs-site/docs/technik/backup/restore.md im hocX-Repository.
"""
