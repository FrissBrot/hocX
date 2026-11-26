"""Passwörter verschlüsselter Exporte werden so verwendet, wie sie eingegeben wurden.

Nachtlauf 2026-11-26 (dokumente/auth): ``encrypt_xlsx`` (Document Studio «Excel mit Passwort») und
``validate_password`` (AES-ZIP: Document Studio, Vereinsexport, Datenauskunft) kürzten das
Passwort still mit ``strip()``. Wer im Dialog ein Passwort mit Leerzeichen am Anfang oder Ende
setzte (bzw. aus einem Passwortmanager einfügte), bekam eine Datei, die sich mit genau diesem
Passwort nicht öffnen liess - nur ohne die Leerzeichen, was niemand weiss. Die Mindestlänge
zählt weiterhin ohne Rand-Leerzeichen (nur Leerzeichen bleibt ungültig).
"""
from __future__ import annotations

import io
import os

import msoffcrypto
import pytest
import pyzipper

from app.documents import exports as extra_formats
from app.services.data_export.archive import EncryptedZip, encrypt_single, validate_password

# Zufällig statt als Literal (Secret-Scan), mit Leerzeichen am Rand wie aus einem Passwortmanager
PASSWORD = f" {os.urandom(8).hex()} "


def _xlsx() -> bytes:
    return extra_formats.to_xlsx([("Tabelle", [["Name"], ["Muster"]])])


def _decrypt_xlsx(content: bytes, password: str) -> bytes:
    office = msoffcrypto.OfficeFile(io.BytesIO(content))
    office.load_key(password=password)
    out = io.BytesIO()
    office.decrypt(out)
    return out.getvalue()


def test_excel_export_opens_with_password_as_entered():
    plain = _xlsx()
    encrypted = extra_formats.encrypt_xlsx(plain, PASSWORD)
    assert _decrypt_xlsx(encrypted, PASSWORD) == plain


def test_zip_export_opens_with_password_as_entered():
    data = b"Name;Betrag\nMuster;10\n"
    encrypted = encrypt_single("export.csv", data, PASSWORD)
    with pyzipper.AESZipFile(io.BytesIO(encrypted)) as archive:
        archive.setpassword(PASSWORD.encode("utf-8"))
        assert archive.read("export.csv") == data


def test_streamed_zip_archive_opens_with_password_as_entered(tmp_path):
    archive = EncryptedZip(PASSWORD, directory=tmp_path)
    archive.add_bytes("a.txt", b"inhalt")
    archive.close()
    with pyzipper.AESZipFile(archive.path) as opened:
        opened.setpassword(PASSWORD.encode("utf-8"))
        assert opened.read("a.txt") == b"inhalt"


@pytest.mark.parametrize("password", [" " * 20, "\t" + "a" * 11 + " "])
def test_minimum_length_ignores_surrounding_whitespace(password):
    with pytest.raises(ValueError):
        validate_password(password)
    with pytest.raises(ValueError, match="passwordRequired"):
        extra_formats.encrypt_xlsx(_xlsx(), password)
