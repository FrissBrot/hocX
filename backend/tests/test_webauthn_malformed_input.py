"""Kaputte Passkey-Antworten sind Eingabefehler (Bug-Bounty 2026-11-22, mitglieder-rollen/eingaben).

Alle Aufrufer (Passkey einrichten, Passkey-Login, Step-up, Plattform-Admin) fangen nur
`WebauthnError` ab. Ungültiges Base64, ein `response`/Client-Data, das kein Objekt ist,
ungültiges UTF-8 oder tief verschachteltes CBOR warfen aber binascii.Error, AttributeError,
UnicodeDecodeError bzw. RecursionError: 500 samt Eintrag im Fehlerprotokoll statt 400/401."""
from __future__ import annotations

import json

import pytest

from app.core.base64url import b64url_encode
from app.core.cbor import CborDecodeError, decode_cbor
from app.core.webauthn import WebauthnError, register_credential, verify_assertion
from tests.soft_passkey import SoftPasskey

ORIGIN = "https://verein.example.test"
RP_ID = "verein.example.test"
CHALLENGE = "challenge-123"


def _register(credential):
    return register_credential(credential, expected_challenge=CHALLENGE, expected_origin=ORIGIN, expected_rp_id=RP_ID)


def _valid_registration() -> dict:
    return SoftPasskey().create({"challenge": CHALLENGE, "rp": {"id": RP_ID}}, origin=ORIGIN)


def _client_data(kind: str = "webauthn.create") -> str:
    return b64url_encode(json.dumps({"type": kind, "challenge": CHALLENGE, "origin": ORIGIN}).encode())


def test_valid_registration_still_works():
    assert _register(_valid_registration()).credential_id


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: c.__setitem__("response", "kein-objekt"), id="response-ist-text"),
        pytest.param(lambda c: c["response"].__setitem__("clientDataJSON", "A"), id="base64-ungueltig"),
        pytest.param(lambda c: c["response"].__setitem__("clientDataJSON", "äöü"), id="base64-nicht-ascii"),
        pytest.param(lambda c: c["response"].__setitem__("clientDataJSON", b64url_encode(b"[1, 2]")), id="client-data-liste"),
        pytest.param(lambda c: c["response"].__setitem__("attestationObject", b64url_encode(b"\x81" * 5000 + b"\x00")), id="cbor-tief"),
        pytest.param(lambda c: c["response"].__setitem__("attestationObject", b64url_encode(b"\xa1\x63fmt\x62\xff\xfe")), id="cbor-utf8"),
    ],
)
def test_malformed_registration_raises_webauthn_error(mutate):
    credential = _valid_registration()
    mutate(credential)
    with pytest.raises(WebauthnError):
        _register(credential)


def test_non_list_transports_are_ignored_not_a_500():
    credential = _valid_registration()
    credential["response"]["transports"] = 5  # vorher TypeError beim Iterieren
    assert _register(credential).transports == []


@pytest.mark.parametrize(
    "response",
    [
        pytest.param("kein-objekt", id="response-ist-text"),
        pytest.param({"clientDataJSON": _client_data("webauthn.get"), "authenticatorData": "A", "signature": "AAAA"}, id="base64-ungueltig"),
        pytest.param({"clientDataJSON": b64url_encode(b'"text"'), "authenticatorData": "AAAA", "signature": "AAAA"}, id="client-data-text"),
    ],
)
def test_malformed_assertion_raises_webauthn_error(response):
    with pytest.raises(WebauthnError):
        verify_assertion(
            {"id": "abc", "rawId": "abc", "response": response},
            expected_challenge=CHALLENGE, expected_origin=ORIGIN, expected_rp_id=RP_ID,
            public_key_pem="unbenutzt", stored_sign_count=0, expected_credential_id="abc",
        )


@pytest.mark.parametrize("payload", [b"\x81" * 5000 + b"\x00", b"\x63\xff\xfe\xfd"], ids=["tief", "utf8"])
def test_cbor_decoder_raises_only_cbor_errors(payload):
    with pytest.raises(CborDecodeError):
        decode_cbor(payload)
