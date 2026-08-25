from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.core.base64url import b64url_decode, b64url_encode
from app.core.cbor import CborDecodeError, decode_cbor, decode_cbor_prefix


FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04
FLAG_ATTESTED_CREDENTIAL_DATA = 0x40


class WebauthnError(ValueError):
    pass


@dataclass
class RegisteredCredential:
    credential_id: str
    public_key_pem: str
    sign_count: int
    aaguid: str | None
    transports: list[str]


@dataclass
class AssertionResult:
    credential_id: str
    sign_count: int


@dataclass
class ParsedAuthenticatorData:
    rp_id_hash: bytes
    flags: int
    sign_count: int
    credential_id: bytes | None = None
    credential_public_key: bytes | None = None
    aaguid: str | None = None


def generate_challenge() -> str:
    return b64url_encode(secrets.token_bytes(32))


def build_registration_options(
    *,
    rp_id: str,
    rp_name: str,
    user_id: int,
    user_name: str,
    display_name: str,
    challenge: str,
    exclude_credentials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "challenge": challenge,
        "rp": {"name": rp_name, "id": rp_id},
        "user": {
            "id": b64url_encode(str(user_id).encode("utf-8")),
            "name": user_name,
            "displayName": display_name,
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},
            {"type": "public-key", "alg": -257},
        ],
        "timeout": 60_000,
        "attestation": "none",
        "authenticatorSelection": {
            "residentKey": "preferred",
            "userVerification": "required",
        },
        "excludeCredentials": exclude_credentials or [],
    }


def build_assertion_options(
    *,
    challenge: str,
    rp_id: str,
    allow_credentials: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "challenge": challenge,
        "rpId": rp_id,
        "timeout": 60_000,
        "userVerification": "required",
        "allowCredentials": allow_credentials,
    }


def parse_authenticator_data(data: bytes) -> ParsedAuthenticatorData:
    if len(data) < 37:
        raise WebauthnError("Authenticator data is too short")

    rp_id_hash = data[:32]
    flags = data[32]
    sign_count = int.from_bytes(data[33:37], "big")
    parsed = ParsedAuthenticatorData(rp_id_hash=rp_id_hash, flags=flags, sign_count=sign_count)

    if flags & FLAG_ATTESTED_CREDENTIAL_DATA:
        if len(data) < 55:
            raise WebauthnError("Authenticator data is missing attested credential data")
        cursor = 37
        aaguid = data[cursor : cursor + 16]
        cursor += 16
        credential_id_length = int.from_bytes(data[cursor : cursor + 2], "big")
        cursor += 2
        credential_id = data[cursor : cursor + credential_id_length]
        cursor += credential_id_length
        try:
            credential_public_key, consumed = decode_cbor_prefix(data[cursor:])
        except CborDecodeError as exc:
            # A malformed/attacker-crafted CBOR payload here must reach the caller as the
            # same clean 400 every other malformed-input case in this module produces, not
            # as an unclassified 500 (audit finding, 2026-08-25).
            raise WebauthnError("Credential public key is malformed") from exc
        if not isinstance(credential_public_key, dict):
            raise WebauthnError("Credential public key is malformed")
        parsed.credential_id = credential_id
        parsed.credential_public_key = data[cursor : cursor + consumed]
        parsed.aaguid = aaguid.hex()
    return parsed


def register_credential(
    payload: dict[str, Any],
    *,
    expected_challenge: str,
    expected_origin: str,
    expected_rp_id: str,
) -> RegisteredCredential:
    response = payload.get("response") or {}
    client_data_raw = b64url_decode(_require_text(response, "clientDataJSON"))
    attestation_object = b64url_decode(_require_text(response, "attestationObject"))
    client_data = _parse_client_data(client_data_raw, expected_type="webauthn.create")
    _verify_client_data(client_data, expected_challenge=expected_challenge, expected_origin=expected_origin)

    try:
        attestation = decode_cbor(attestation_object)
    except CborDecodeError as exc:
        raise WebauthnError("Attestation object is malformed") from exc
    if not isinstance(attestation, dict):
        raise WebauthnError("Attestation object is malformed")
    auth_data = attestation.get("authData")
    if not isinstance(auth_data, bytes):
        raise WebauthnError("Attestation object is missing authenticator data")

    parsed = parse_authenticator_data(auth_data)
    _verify_rp_id_hash(parsed.rp_id_hash, expected_rp_id)
    if not (parsed.flags & FLAG_USER_PRESENT):
        raise WebauthnError("Authenticator did not confirm user presence")
    if not (parsed.flags & FLAG_USER_VERIFIED):
        raise WebauthnError("Authenticator did not confirm user verification")
    if parsed.credential_id is None or parsed.credential_public_key is None:
        raise WebauthnError("Attestation is missing credential data")

    raw_id = payload.get("rawId") or payload.get("id")
    if raw_id and b64url_encode(parsed.credential_id) != raw_id:
        raise WebauthnError("Credential id does not match authenticator data")

    public_key = _cose_public_key_to_pem(parsed.credential_public_key)
    transports = [str(item) for item in (response.get("transports") or []) if isinstance(item, str)]
    return RegisteredCredential(
        credential_id=b64url_encode(parsed.credential_id),
        public_key_pem=public_key,
        sign_count=parsed.sign_count,
        aaguid=parsed.aaguid,
        transports=transports,
    )


def verify_assertion(
    payload: dict[str, Any],
    *,
    expected_challenge: str,
    expected_origin: str,
    expected_rp_id: str,
    public_key_pem: str,
    stored_sign_count: int,
    expected_credential_id: str,
) -> AssertionResult:
    response = payload.get("response") or {}
    client_data_raw = b64url_decode(_require_text(response, "clientDataJSON"))
    auth_data = b64url_decode(_require_text(response, "authenticatorData"))
    signature = b64url_decode(_require_text(response, "signature"))

    client_data = _parse_client_data(client_data_raw, expected_type="webauthn.get")
    _verify_client_data(client_data, expected_challenge=expected_challenge, expected_origin=expected_origin)

    parsed = parse_authenticator_data(auth_data)
    _verify_rp_id_hash(parsed.rp_id_hash, expected_rp_id)
    if not (parsed.flags & FLAG_USER_PRESENT):
        raise WebauthnError("Authenticator did not confirm user presence")
    if not (parsed.flags & FLAG_USER_VERIFIED):
        raise WebauthnError("Authenticator did not confirm user verification")

    raw_id = payload.get("rawId") or payload.get("id")
    if raw_id != expected_credential_id:
        raise WebauthnError("Unexpected credential id")

    signed_data = auth_data + hashlib.sha256(client_data_raw).digest()
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, signed_data, ec.ECDSA(hashes.SHA256()))
        elif isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise WebauthnError("Unsupported public key type")
    except InvalidSignature as exc:
        raise WebauthnError("Passkey signature verification failed") from exc

    if stored_sign_count > 0 and parsed.sign_count > 0 and parsed.sign_count <= stored_sign_count:
        raise WebauthnError("Passkey sign counter did not increase")

    return AssertionResult(credential_id=expected_credential_id, sign_count=parsed.sign_count)


def _require_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise WebauthnError(f"Missing WebAuthn field '{key}'")
    return value


def _parse_client_data(raw: bytes, *, expected_type: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebauthnError("Client data is not valid JSON") from exc
    if parsed.get("type") != expected_type:
        raise WebauthnError(f"Unexpected WebAuthn ceremony type '{parsed.get('type')}'")
    return parsed


def _verify_client_data(client_data: dict[str, Any], *, expected_challenge: str, expected_origin: str) -> None:
    if client_data.get("challenge") != expected_challenge:
        raise WebauthnError("WebAuthn challenge does not match")
    if client_data.get("origin") != expected_origin:
        raise WebauthnError("WebAuthn origin does not match")


def _verify_rp_id_hash(rp_id_hash: bytes, expected_rp_id: str) -> None:
    expected = hashlib.sha256(expected_rp_id.encode("utf-8")).digest()
    if rp_id_hash != expected:
        raise WebauthnError("WebAuthn rpId hash does not match")


def _cose_public_key_to_pem(cose_raw: bytes) -> str:
    try:
        cose = decode_cbor(cose_raw)
    except CborDecodeError as exc:
        raise WebauthnError("Credential public key CBOR is malformed") from exc
    if not isinstance(cose, dict):
        raise WebauthnError("Credential public key CBOR is malformed")

    kty = cose.get(1)
    if kty == 2:
        x = cose.get(-2)
        y = cose.get(-3)
        if not isinstance(x, bytes) or not isinstance(y, bytes):
            raise WebauthnError("Elliptic-curve credential key is malformed")
        curve = ec.SECP256R1()
        numbers = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), curve)
        public_key = numbers.public_key()
    elif kty == 3:
        n = cose.get(-1)
        e = cose.get(-2)
        if not isinstance(n, bytes) or not isinstance(e, bytes):
            raise WebauthnError("RSA credential key is malformed")
        numbers = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big"))
        public_key = numbers.public_key()
    else:
        raise WebauthnError(f"Unsupported COSE key type {kty}")

    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
