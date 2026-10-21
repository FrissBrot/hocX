"""Passwortgeschützte ZIP-Datei (AES-256, WinZip AE-2) - lesbar mit 7-Zip, Keka, WinRAR.

SECURITY-RULES §4.4: Exporte mit Personendaten verlassen den Server nur verschlüsselt. Für die
Weiterarbeit im Verein ohne hocX ist das hocX-eigene Format (export_crypto) ungeeignet; ein
AES-ZIP mit einem Passwort, das nur der Admin kennt, erfüllt beides.
"""
from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

import pyzipper

MIN_PASSWORD_LENGTH = 12


def validate_password(password: str | None) -> str:
    value = (password or "").strip()
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen")
    return value


class EncryptedZip:
    """Schreibt Einträge nacheinander in eine temporäre, AES-verschlüsselte ZIP-Datei."""

    def __init__(self, password: str, *, directory: Path | None = None) -> None:
        secret = validate_password(password).encode("utf-8")  # vor dem Anlegen: sonst bliebe die Datei liegen
        handle = tempfile.NamedTemporaryFile(prefix="hocx-datenexport-", suffix=".zip", delete=False, dir=str(directory) if directory else None)
        handle.close()
        self.path = Path(handle.name)
        try:
            self._zip = pyzipper.AESZipFile(self.path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES)
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        self._zip.setpassword(secret)
        self._zip.setencryption(pyzipper.WZ_AES, nbits=256)
        self._names: set[str] = set()

    def _unique(self, name: str) -> str:
        candidate, counter = name, 2
        while candidate in self._names:
            stem, dot, suffix = name.rpartition(".")
            candidate = f"{stem} ({counter}).{suffix}" if dot else f"{name} ({counter})"
            counter += 1
        self._names.add(candidate)
        return candidate

    def add_bytes(self, name: str, data: bytes) -> str:
        name = self._unique(name)
        self._zip.writestr(name, data)
        return name

    def add_file(self, name: str, source: Path) -> str:
        name = self._unique(name)
        self._zip.write(source, name)
        return name

    def close(self) -> Path:
        self._zip.close()
        return self.path

    def discard(self) -> None:
        try:
            self._zip.close()
        finally:
            self.path.unlink(missing_ok=True)


def safe_name(value: str | None, fallback: str = "Datei", max_length: int = 80) -> str:
    """Dateiname für ein ZIP-Mitglied: keine Pfadteile, keine Steuerzeichen."""
    text = "".join(ch for ch in str(value or "") if ch.isprintable() and ch not in '\\/:*?"<>|').strip(" .")
    return (text or fallback)[:max_length]


def add_all(archive: EncryptedZip, items: Iterable[tuple[str, bytes]]) -> None:
    for name, data in items:
        archive.add_bytes(name, data)
