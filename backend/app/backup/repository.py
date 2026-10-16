"""Lesender Zugriff auf das Borg-Repository im hocX-Format - gemeinsam für Worker und
Recovery-CLI, ohne hocX-Datenbank. Die Backup-Historie ist allein hieraus rekonstruierbar."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from app.core.objstore_client import StorageIntegrityError

from app.backup.borg import Borg
from app.backup.manifest import (
    MANIFEST_PATH,
    METADATA_PATH,
    POOL_NAME,
    ManifestEntry,
    ManifestError,
    parse_metadata,
    parse_rp_name,
    pool_path,
    read_manifest,
    sha_from_pool_path,
)

_logger = logging.getLogger("hocx.backup.repository")
_READ = 1024 * 1024


class IntegrityFailure(Exception):
    """Inhalt im Repository passt nicht zu Manifest/Metadaten (SHA-256, Grösse, fehlend)."""


@dataclass(frozen=True)
class RestorePointInfo:
    name: str
    archive_id: str
    snapshot_at: datetime
    backup_id: Any
    invalid: bool


@dataclass
class FetchReport:
    fetched: int = 0
    fetched_bytes: int = 0
    missing: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.corrupt


class _VerifyingReader:
    """Liest einen Tar-Eintrag und rechnet SHA-256 und Grösse mit."""

    def __init__(self, source: IO[bytes]) -> None:
        self.source = source
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(size if size and size > 0 else _READ)
        if data:
            self.digest.update(data)
            self.size += len(data)
        return data

    def chunks(self) -> Iterator[bytes]:
        while data := self.read(_READ):
            yield data

    def drain(self) -> None:
        while self.read(_READ):
            pass


class RepositoryView:
    def __init__(self, borg: Borg) -> None:
        self.borg = borg

    # --- Archive ------------------------------------------------------------------------------

    def restore_points(self, *, include_invalid: bool = False) -> list[RestorePointInfo]:
        points = []
        for archive in self.borg.list_archives(glob="hocx-rp-*"):
            parsed = parse_rp_name(archive["name"])
            if parsed is None:
                continue
            snapshot_at, backup_id, invalid = parsed
            if invalid and not include_invalid:
                continue
            points.append(RestorePointInfo(archive["name"], archive["id"], snapshot_at, backup_id, invalid))
        return sorted(points, key=lambda p: p.snapshot_at, reverse=True)

    def pool_archives(self) -> dict[str, str]:
        return {a["name"]: a["id"] for a in self.borg.list_archives(glob="hocx-pool-*") if POOL_NAME.match(a["name"])}

    def checkpoint_archives(self) -> list[str]:
        """Reste abgebrochener Läufe (Borg-Checkpoints) - nie als gültige Daten verwenden."""
        return [a["name"] for a in self.borg.list_archives(glob="hocx-*.checkpoint*")]

    def pool_contents(self, pool: str) -> dict[str, int]:
        """sha256 -> Grösse aller Inhalte eines Pool-Archivs (Teil-Dateien zählen nicht)."""
        contents: dict[str, int] = {}
        for item in self.borg.iter_items(pool):
            if item.get("type") != "-":
                continue
            sha = sha_from_pool_path(item.get("path") or "")
            if sha is not None:
                contents[sha] = int(item.get("size") or 0)
        return contents

    # --- Dateien eines Wiederherstellungspunkts -----------------------------------------------

    def read_metadata(self, archive: str) -> dict[str, Any]:
        with self.borg.extract_stream(archive, METADATA_PATH) as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        return parse_metadata(raw)

    def download(self, archive: str, path: str, target: Path, *, expected_sha256: str | None = None,
                 max_bytes: int | None = None) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        tmp = target.with_name(f".{target.name}.part")
        try:
            with self.borg.extract_stream(archive, path) as stream, tmp.open("wb") as handle:
                while data := stream.read(_READ):
                    size += len(data)
                    if max_bytes is not None and size > max_bytes:
                        raise IntegrityFailure(f"{path} ist grösser als das Staging-Budget erlaubt")
                    digest.update(data)
                    handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        actual = digest.hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            tmp.unlink(missing_ok=True)
            raise IntegrityFailure(f"SHA-256 von {path} weicht von den Metadaten ab")
        os.replace(tmp, target)
        return actual, size

    @contextmanager
    def open_manifest(self, archive: str, work_dir: Path, *, expected_sha256: str | None) -> Iterator[tuple[dict[str, Any], Iterator[ManifestEntry]]]:
        work_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="manifest-", suffix=".jsonl.gz", dir=str(work_dir))
        os.close(fd)
        path = Path(name)
        try:
            self.download(archive, MANIFEST_PATH, path, expected_sha256=expected_sha256)
            with path.open("rb") as handle:
                header, entries = read_manifest(handle)
                yield header, entries
        finally:
            path.unlink(missing_ok=True)

    # --- Objektinhalte ------------------------------------------------------------------------

    def fetch_contents(
        self,
        entries: Iterable[ManifestEntry],
        sink: Callable[[str, int, Iterator[bytes], list[ManifestEntry]], None],
        *,
        paths_per_call: int = 1000,
        should_stop: Callable[[], None] | None = None,
    ) -> FetchReport:
        """Liest die Inhalte der angegebenen Manifest-Einträge aus ihren Pool-Archiven und reicht
        sie (SHA-256-geprüft) an sink(sha, size, chunks, targets) weiter. Jeder Inhalt wird genau
        einmal gelesen, auch wenn mehrere Keys ihn teilen. sink muss den Stream vollständig lesen.
        Ein Inhalt, dessen SHA-256 nach dem Lesen nicht stimmt, landet in report.corrupt - sink
        muss das Ergebnis darum erst nach erfolgreicher Prüfung endgültig machen (z. B. das
        Objekt unter dem Ziel-Key erst nach dem Schreiben registrieren); siehe verify-Parameter
        der Aufrufer."""
        by_pool: dict[str, dict[str, list[ManifestEntry]]] = defaultdict(lambda: defaultdict(list))
        for entry in entries:
            by_pool[entry.pool][entry.sha256].append(entry)
        report = FetchReport()
        for pool, contents in sorted(by_pool.items()):
            shas = sorted(contents)
            for start in range(0, len(shas), paths_per_call):
                chunk = shas[start:start + paths_per_call]
                expected = {pool_path(sha): sha for sha in chunk}
                seen: set[str] = set()
                with self.borg.export_tar(pool, list(expected)) as stream:
                    for member in stream:
                        if should_stop is not None:
                            should_stop()
                        sha = expected.get(member.name)
                        if sha is None or not member.isfile() or sha in seen:
                            continue
                        handle = stream.extractfile(member)
                        if handle is None:
                            continue
                        targets = contents[sha]
                        reader = _VerifyingReader(handle)
                        try:
                            sink(sha, member.size, reader.chunks(), targets)
                        except StorageIntegrityError:
                            reader.drain()
                            report.corrupt.append(sha)
                            continue
                        reader.drain()
                        if reader.digest.hexdigest() != sha or reader.size != targets[0].size:
                            report.corrupt.append(sha)
                            continue
                        seen.add(sha)
                        report.fetched += 1
                        report.fetched_bytes += reader.size
                report.missing.extend(sha for sha in chunk if sha not in seen and sha not in report.corrupt)
        return report


__all__ = ["FetchReport", "IntegrityFailure", "ManifestError", "RepositoryView", "RestorePointInfo"]
