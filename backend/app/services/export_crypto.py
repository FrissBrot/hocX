"""Verschlüsselung der Mandanten-Exporte (Security-Audit release/1.2.0, Datenschutz).

Ein Export enthält Personendaten und - im Umfang "full" - die Passwort-Hashes aller Konten. Er
verlässt den Server deshalb nie unverschlüsselt:

- **Server-Schlüssel (Standard):** Beim Einrichten erzeugt `deploy.sh` einmalig einen
  X25519-Schlüssel (`EXPORT_ENCRYPTION_KEY`, scripts/lib/env_migrate.sh). Exporte werden mit dem
  öffentlichen Teil verschlüsselt (ephemeres X25519 + HKDF), ein Import auf demselben Server
  entschlüsselt automatisch. Auf einem anderen Server ist die Datei wertlos.
- **Passwort (optional):** Setzt der Admin beim Export ein Passwort, wird der Datenschlüssel
  stattdessen per scrypt aus dem Passwort abgeleitet. So lässt sich ein Mandant auf einen
  anderen Server umziehen; beim Import muss das Passwort angegeben werden.

Format: `MAGIC`, 4 Byte Headerlänge, Header (JSON), danach der Inhalt in Blöcken zu `CHUNK_SIZE`
Byte, jeder einzeln mit AES-256-GCM verschlüsselt. Die Nonce eines Blocks besteht aus einem
zufälligen Präfix, dem Blockzähler und einem Schlussmarker; der Header ist Teil der
authentifizierten Daten jedes Blocks. Vertauschte, veränderte oder abgeschnittene Dateien werden
so beim Entschlüsseln erkannt. Gestreamt, weil Exporte mit Dateien gross sein können.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.core.config import settings

MAGIC = b"HOCXENC1\n"
CHUNK_SIZE = 1024 * 1024
ENCRYPTED_SUFFIX = ".hocxenc"
MIN_PASSWORD_LENGTH = 12
# scrypt-Kosten (2^15, 8, 1): ~32 MiB Speicher, im Bereich einer Sekunde - einmal je Export/Import.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1
_MAX_HEADER_BYTES = 16 * 1024
_HKDF_INFO = b"hocx tenant export v1"
_NONCE_PREFIX_BYTES = 7


class ExportDecryptionError(ValueError):
    """Kuratierte Meldung für den Admin (ValueError: wird nicht als unerwarteter Fehler geloggt)."""


class ExportPasswordRequired(ExportDecryptionError):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _server_private_key() -> X25519PrivateKey:
    raw = settings.export_encryption_key.strip()
    if raw:
        try:
            key_bytes = bytes.fromhex(raw)
        except ValueError as exc:
            raise RuntimeError("EXPORT_ENCRYPTION_KEY muss 64 Hex-Zeichen enthalten") from exc
        if len(key_bytes) != 32:
            raise RuntimeError("EXPORT_ENCRYPTION_KEY muss 64 Hex-Zeichen enthalten")
    elif settings.is_production:
        raise RuntimeError("EXPORT_ENCRYPTION_KEY fehlt - deploy.sh erzeugt ihn (scripts/lib/env_migrate.sh)")
    else:
        # Nur ausserhalb der Produktion: stabil aus
        # AUTH_SECRET abgeleitet, damit Entwicklungs- und Teststacks ohne eigenes Secret laufen.
        key_bytes = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"hocx export key (dev)").derive(
            settings.auth_secret.encode("utf-8")
        )
    return X25519PrivateKey.from_private_bytes(key_bytes)


def _public_bytes(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def server_key_id() -> str:
    """Kurzer Fingerabdruck des Server-Schlüssels: erkennt beim Import, ob die Datei für diesen
    Server verschlüsselt wurde."""
    return hashlib.sha256(_public_bytes(_server_private_key().public_key())).hexdigest()[:16]


def _wrap_key_for_server(data_key: bytes) -> dict:
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = _public_bytes(ephemeral.public_key())
    shared = ephemeral.exchange(_server_private_key().public_key())
    kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral_public, info=_HKDF_INFO).derive(shared)
    nonce = os.urandom(12)
    return {
        "mode": "server",
        "key_id": server_key_id(),
        "ephemeral_public_key": _b64(ephemeral_public),
        "wrapped_key": _b64(nonce + AESGCM(kek).encrypt(nonce, data_key, b"server")),
    }


def _password_kek(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def _wrap_key_with_password(data_key: bytes, password: str) -> dict:
    salt = os.urandom(16)
    kek = _password_kek(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    nonce = os.urandom(12)
    return {
        "mode": "password",
        "kdf": {"name": "scrypt", "salt": _b64(salt), "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P},
        "wrapped_key": _b64(nonce + AESGCM(kek).encrypt(nonce, data_key, b"password")),
    }


def _nonce(prefix: bytes, counter: int, final: bool) -> bytes:
    return prefix + struct.pack(">I", counter) + (b"\x01" if final else b"\x00")


def validate_password(password: str | None) -> str | None:
    if password is None or password == "":
        return None
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Das Export-Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein")
    return password


def encrypt_file(source: Path, target: Path, *, password: str | None = None) -> None:
    """Verschlüsselt `source` nach `target` - mit Passwort, sonst mit dem Server-Schlüssel."""
    data_key = AESGCM.generate_key(bit_length=256)
    prefix = os.urandom(_NONCE_PREFIX_BYTES)
    header = {
        "version": 1,
        "cipher": "AES-256-GCM",
        "chunk_size": CHUNK_SIZE,
        "nonce_prefix": _b64(prefix),
        **(_wrap_key_with_password(data_key, password) if password else _wrap_key_for_server(data_key)),
    }
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    aead = AESGCM(data_key)
    with source.open("rb") as src, target.open("wb") as dst:
        dst.write(MAGIC)
        dst.write(struct.pack(">I", len(header_bytes)))
        dst.write(header_bytes)
        counter = 0
        chunk = src.read(CHUNK_SIZE)
        while True:
            following = src.read(CHUNK_SIZE)
            final = not following
            dst.write(aead.encrypt(_nonce(prefix, counter, final), chunk, header_bytes))
            if final:
                break
            chunk = following
            counter += 1


def is_encrypted(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(MAGIC)) == MAGIC


def _read_header(handle: BinaryIO) -> tuple[dict, bytes]:
    if handle.read(len(MAGIC)) != MAGIC:
        raise ExportDecryptionError("Die Datei ist kein verschlüsselter hocX-Export")
    raw_length = handle.read(4)
    if len(raw_length) != 4:
        raise ExportDecryptionError("Der verschlüsselte Export ist beschädigt")
    (length,) = struct.unpack(">I", raw_length)
    if length > _MAX_HEADER_BYTES:
        raise ExportDecryptionError("Der verschlüsselte Export ist beschädigt")
    header_bytes = handle.read(length)
    try:
        header = json.loads(header_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExportDecryptionError("Der verschlüsselte Export ist beschädigt") from exc
    if header.get("version") != 1 or header.get("cipher") != "AES-256-GCM":
        raise ExportDecryptionError("Unbekanntes Format des verschlüsselten Exports")
    return header, header_bytes


def requires_password(path: Path) -> bool:
    with path.open("rb") as handle:
        header, _ = _read_header(handle)
    return header.get("mode") == "password"


def _unwrap_data_key(header: dict, password: str | None) -> bytes:
    try:
        wrapped = _unb64(header["wrapped_key"])
        nonce, ciphertext = wrapped[:12], wrapped[12:]
        if header.get("mode") == "server":
            if header.get("key_id") != server_key_id():
                raise ExportDecryptionError(
                    "Dieser Export wurde für einen anderen Server verschlüsselt. Für einen Umzug beim Export ein Passwort setzen."
                )
            ephemeral_public = _unb64(header["ephemeral_public_key"])
            shared = _server_private_key().exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
            kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral_public, info=_HKDF_INFO).derive(shared)
            return AESGCM(kek).decrypt(nonce, ciphertext, b"server")
        if header.get("mode") == "password":
            if not password:
                raise ExportPasswordRequired("Dieser Export ist mit einem Passwort geschützt")
            kdf = header["kdf"]
            if kdf.get("name") != "scrypt" or int(kdf["n"]) > 2**20:
                raise ExportDecryptionError("Unbekanntes Format des verschlüsselten Exports")
            kek = _password_kek(password, _unb64(kdf["salt"]), int(kdf["n"]), int(kdf["r"]), int(kdf["p"]))
            try:
                return AESGCM(kek).decrypt(nonce, ciphertext, b"password")
            except InvalidTag as exc:
                raise ExportDecryptionError("Das Passwort für diesen Export ist falsch") from exc
    except ExportDecryptionError:
        raise
    except (KeyError, ValueError, TypeError, InvalidTag) as exc:
        raise ExportDecryptionError("Der verschlüsselte Export ist beschädigt") from exc
    raise ExportDecryptionError("Unbekanntes Format des verschlüsselten Exports")


def decrypt_file(source: Path, target: Path, *, password: str | None = None) -> None:
    """Entschlüsselt `source` nach `target`. Bei jedem Fehler bleibt kein Teilergebnis liegen."""
    try:
        with source.open("rb") as src:
            header, header_bytes = _read_header(src)
            data_key = _unwrap_data_key(header, password)
            prefix = _unb64(header["nonce_prefix"])
            chunk_size = int(header["chunk_size"])
            aead = AESGCM(data_key)
            with target.open("wb") as dst:
                counter = 0
                block = src.read(chunk_size + 16)
                while True:
                    following = src.read(chunk_size + 16)
                    final = not following
                    try:
                        dst.write(aead.decrypt(_nonce(prefix, counter, final), block, header_bytes))
                    except InvalidTag as exc:
                        raise ExportDecryptionError("Der verschlüsselte Export ist beschädigt oder unvollständig") from exc
                    if final:
                        break
                    block = following
                    counter += 1
    except BaseException:
        target.unlink(missing_ok=True)
        raise
