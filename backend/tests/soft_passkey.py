"""Software-Authenticator für Tests: erzeugt echte WebAuthn-Antworten (Registrierung mit
Attestation «none», Assertion mit ECDSA P-256), die app/core/webauthn.py vollständig prüft -
Challenge, Origin, RP-ID-Hash, UP/UV-Flags, Signatur, Zähler."""
from __future__ import annotations

import hashlib
import json
import secrets
import struct
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.base64url import b64url_encode

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


def _head(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 256:
        return bytes([(major << 5) | 24, value])
    if value < 65536:
        return bytes([(major << 5) | 25]) + struct.pack(">H", value)
    return bytes([(major << 5) | 26]) + struct.pack(">I", value)


def cbor(value: Any) -> bytes:
    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _head(3, len(raw)) + raw
    if isinstance(value, dict):
        return _head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(type(value))


class SoftPasskey:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.sign_count = 0
        self.user_verified = True

    @property
    def credential_id_b64(self) -> str:
        return b64url_encode(self.credential_id)

    def _cose_key(self) -> bytes:
        numbers = self.private_key.public_key().public_numbers()
        return cbor({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _flags(self, extra: int = 0) -> int:
        return FLAG_UP | (FLAG_UV if self.user_verified else 0) | extra

    @staticmethod
    def _client_data(kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode("utf-8")

    def create(self, public_key: dict[str, Any], *, origin: str, rp_id: str | None = None) -> dict[str, Any]:
        rp_id = rp_id or public_key["rp"]["id"]
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([self._flags(FLAG_AT)])
            + struct.pack(">I", self.sign_count)
            + bytes(16)
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        attestation = cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", public_key["challenge"], origin)
        return {
            "id": self.credential_id_b64,
            "rawId": self.credential_id_b64,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url_encode(client_data),
                "attestationObject": b64url_encode(attestation),
                "transports": ["internal"],
            },
        }

    def get(self, public_key: dict[str, Any], *, origin: str, rp_id: str | None = None) -> dict[str, Any]:
        rp_id = rp_id or public_key["rpId"]
        self.sign_count += 1
        auth_data = hashlib.sha256(rp_id.encode()).digest() + bytes([self._flags()]) + struct.pack(">I", self.sign_count)
        client_data = self._client_data("webauthn.get", public_key["challenge"], origin)
        signature = self.private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": self.credential_id_b64,
            "rawId": self.credential_id_b64,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url_encode(client_data),
                "authenticatorData": b64url_encode(auth_data),
                "signature": b64url_encode(signature),
                "userHandle": None,
            },
        }
