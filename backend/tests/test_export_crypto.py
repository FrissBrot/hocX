"""Verschlüsselte Mandanten-Exporte (app/services/export_crypto.py): Server-Schlüssel oder Passwort,
gestreamt in Blöcken, Manipulation und Abschneiden werden erkannt."""

import asyncio
import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes import admin as admin_routes
from app.core.config import settings
from app.schemas.admin import TenantExportRequest
from app.services import export_crypto
from tests.factories import make_tenant

SERVER_KEY = "11" * 32
OTHER_SERVER_KEY = "22" * 32
# Zufällig statt als Literal: Testpasswörter sollen weder im Code noch im Secret-Scan auftauchen.
PASSWORD = os.urandom(12).hex()
WRONG_PASSWORD = os.urandom(12).hex()


@pytest.fixture(autouse=True)
def _small_chunks_and_fixed_key(monkeypatch):
    # Kleine Blöcke: mehrere Blöcke und der Schlussblock werden auch mit kleinen Dateien geprüft.
    monkeypatch.setattr(export_crypto, "CHUNK_SIZE", 64)
    monkeypatch.setattr(settings, "export_encryption_key", SERVER_KEY)


def _roundtrip(tmp_path: Path, content: bytes, *, password: str | None = None, decrypt_password: str | None = None) -> bytes:
    plain, encrypted, restored = tmp_path / "plain", tmp_path / "enc", tmp_path / "restored"
    plain.write_bytes(content)
    export_crypto.encrypt_file(plain, encrypted, password=password)
    export_crypto.decrypt_file(encrypted, restored, password=decrypt_password)
    return restored.read_bytes()


@pytest.mark.parametrize("size", [0, 1, 64, 65, 64 * 5 + 7])
def test_server_key_roundtrip(tmp_path, size):
    content = os.urandom(size)
    assert _roundtrip(tmp_path, content) == content


def test_password_roundtrip_and_wrong_or_missing_password(tmp_path):
    content = os.urandom(300)
    assert _roundtrip(tmp_path, content, password=PASSWORD, decrypt_password=PASSWORD) == content

    encrypted = tmp_path / "enc"
    assert export_crypto.requires_password(encrypted)
    with pytest.raises(export_crypto.ExportPasswordRequired):
        export_crypto.decrypt_file(encrypted, tmp_path / "out")
    with pytest.raises(export_crypto.ExportDecryptionError, match="falsch"):
        export_crypto.decrypt_file(encrypted, tmp_path / "out", password=WRONG_PASSWORD)
    assert not (tmp_path / "out").exists()


def test_password_export_is_importable_on_another_server(tmp_path, monkeypatch):
    plain, encrypted, restored = tmp_path / "plain", tmp_path / "enc", tmp_path / "restored"
    plain.write_bytes(b"umzug")
    export_crypto.encrypt_file(plain, encrypted, password=PASSWORD)
    monkeypatch.setattr(settings, "export_encryption_key", OTHER_SERVER_KEY)

    export_crypto.decrypt_file(encrypted, restored, password=PASSWORD)
    assert restored.read_bytes() == b"umzug"


def test_server_export_is_useless_on_another_server(tmp_path, monkeypatch):
    plain, encrypted = tmp_path / "plain", tmp_path / "enc"
    plain.write_bytes(b"nur hier")
    export_crypto.encrypt_file(plain, encrypted)
    monkeypatch.setattr(settings, "export_encryption_key", OTHER_SERVER_KEY)

    with pytest.raises(export_crypto.ExportDecryptionError, match="anderen Server"):
        export_crypto.decrypt_file(encrypted, tmp_path / "out")


def test_ciphertext_does_not_contain_the_plaintext(tmp_path):
    marker = b"$pbkdf2-sha256$geheimer-hash" * 10
    plain, encrypted = tmp_path / "plain", tmp_path / "enc"
    plain.write_bytes(marker)
    export_crypto.encrypt_file(plain, encrypted)
    data = encrypted.read_bytes()
    assert data.startswith(export_crypto.MAGIC)
    assert b"geheimer-hash" not in data


@pytest.mark.parametrize("damage", ["flip_byte", "truncate_last_block", "drop_middle_block", "append_block"])
def test_tampering_is_detected(tmp_path, damage):
    plain, encrypted = tmp_path / "plain", tmp_path / "enc"
    plain.write_bytes(os.urandom(64 * 4 + 10))
    export_crypto.encrypt_file(plain, encrypted)
    data = bytearray(encrypted.read_bytes())
    block = 64 + 16
    body_start = len(data) - (4 * block + (10 + 16))
    if damage == "flip_byte":
        data[-5] ^= 0x01
    elif damage == "truncate_last_block":
        data = data[: len(data) - (10 + 16)]
    elif damage == "drop_middle_block":
        data = data[: body_start + block] + data[body_start + 2 * block :]
    else:
        data = data + data[body_start : body_start + block]
    encrypted.write_bytes(bytes(data))

    with pytest.raises(export_crypto.ExportDecryptionError):
        export_crypto.decrypt_file(encrypted, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_short_passwords_are_rejected():
    assert export_crypto.validate_password(None) is None
    assert export_crypto.validate_password("") is None
    with pytest.raises(ValueError):
        export_crypto.validate_password("zu-kurz")


def test_production_refuses_to_export_without_a_server_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "export_encryption_key", "")
    monkeypatch.setattr(settings, "environment", "production")
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="EXPORT_ENCRYPTION_KEY"):
        export_crypto.encrypt_file(plain, tmp_path / "enc")


def _admin():
    from types import SimpleNamespace

    return SimpleNamespace(email="admin@example.org")


def _import(db, path: Path, name: str, password: str | None = None):
    upload = UploadFile(file=io.BytesIO(path.read_bytes()), filename=path.name, headers=Headers({"content-type": "application/octet-stream"}))
    return asyncio.run(admin_routes.import_tenant(new_name=name, file=upload, password=password, db=db, current_admin=_admin()))


@pytest.mark.parametrize("password", [None, PASSWORD])
def test_export_route_returns_only_encrypted_files_that_import_again(db, tmp_path, password):
    tenant = make_tenant(db, "Verschluesselt")

    response = admin_routes.export_tenant(tenant.public_id, TenantExportRequest(scope="structure", password=password), db=db, current_admin=_admin())
    exported = tmp_path / "export.hocxenc"
    exported.write_bytes(Path(response.path).read_bytes())
    Path(response.path).unlink(missing_ok=True)

    assert response.filename.endswith(export_crypto.ENCRYPTED_SUFFIX)
    assert export_crypto.is_encrypted(exported)
    assert not zipfile.is_zipfile(exported)
    if password:
        with pytest.raises(HTTPException) as exc:
            _import(db, exported, "Ohne Passwort")
        assert exc.value.status_code == 400
    result = _import(db, exported, "Wieder da", password=password)
    assert result.tenant.name == "Wieder da"


def test_export_route_rejects_a_short_password(db):
    tenant = make_tenant(db)
    with pytest.raises(HTTPException) as exc:
        admin_routes.export_tenant(tenant.public_id, TenantExportRequest(scope="structure", password="kurz"), db=db, current_admin=_admin())
    assert exc.value.status_code == 400
