"""Tar-Stream-Erzeugung für `borg import-tar` ohne Zwischendateien.

Der Header eines Eintrags steht vor dem Inhalt - darum muss die Grösse vorher bekannt sein
(Register) und der SHA-256 wird beim Durchreichen geprüft. Passt etwas nicht, ist der Stream
bereits teilweise geschrieben: ContentMismatch signalisiert dem Aufrufer, dass er borg
abbrechen muss (dann entsteht kein Archiv)."""

from __future__ import annotations

import hashlib
import tarfile
from collections.abc import Iterable
from pathlib import Path
from typing import IO

BLOCK = 512
_READ = 1024 * 1024


class ContentMismatch(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StreamBroken(Exception):
    """Der Empfänger (borg) hat die Pipe geschlossen."""


class TarStreamWriter:
    def __init__(self, out: IO[bytes]) -> None:
        self.out = out
        self.bytes_written = 0

    def _write(self, data: bytes) -> None:
        try:
            self.out.write(data)
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise StreamBroken(str(exc)) from exc
        self.bytes_written += len(data)

    def _header(self, name: str, size: int) -> bytes:
        info = tarfile.TarInfo(name)
        info.size = size
        info.mode = 0o600
        info.mtime = 0
        info.type = tarfile.REGTYPE
        return info.tobuf(format=tarfile.PAX_FORMAT)

    def add_chunks(self, name: str, size: int, chunks: Iterable[bytes], *, expected_sha256: str | None = None) -> str:
        self._write(self._header(name, size))
        digest = hashlib.sha256()
        written = 0
        for chunk in chunks:
            if not chunk:
                continue
            if written + len(chunk) > size:
                raise ContentMismatch("size_larger")
            digest.update(chunk)
            self._write(chunk)
            written += len(chunk)
        if written != size:
            raise ContentMismatch("size_smaller")
        remainder = size % BLOCK
        if remainder:
            self._write(b"\0" * (BLOCK - remainder))
        actual = digest.hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            raise ContentMismatch("sha256")
        return actual

    def add_file(self, name: str, path: Path) -> str:
        size = path.stat().st_size

        def chunks() -> Iterable[bytes]:
            with path.open("rb") as handle:
                while data := handle.read(_READ):
                    yield data

        return self.add_chunks(name, size, chunks())

    def add_bytes(self, name: str, data: bytes) -> str:
        return self.add_chunks(name, len(data), [data])

    def close(self) -> None:
        self._write(b"\0" * (BLOCK * 2))
        try:
            self.out.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise StreamBroken(str(exc)) from exc
