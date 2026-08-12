"""Regression tests for 4 HIGH findings from the 2026-08-12 full audit (agent A batch:
H1-H4).

H1: platform_oidc_service._verify_id_token() picked the JWT verification algorithm from the
token's own (attacker-controlled) `alg` header instead of a server-fixed allowlist - the
classic RS256->HS256 key-confusion vulnerability. Fix: hard-code `algorithms=["RS256"]`
(backend/app/services/platform_oidc_service.py, _verify_id_token, ~line 247-260).

H2: POST /protocols/{id}/attendance/{participant_id}/excuse (excuse_participant) never
checked whether the protocol is frozen (status "abgeschlossen"), unlike every sibling
mutation route - letting attendance/fines on an already-finalized protocol change after the
fact (marking someone excused silently deletes their pending AttendanceFine). Fix: added the
same get_protocol_or_404_not_frozen() guard used everywhere else (backend/app/api/routes/
protocols.py, excuse_participant, ~line 146-151).

H3: POST /protocols/{id}/quick-todos (create_quick_todo) could create new blocks/todos on a
frozen protocol, unlike todos.py's create_todo/patch_todo/delete_todo which all guard with
get_protocol_or_404_not_frozen(). Fix: same guard added (backend/app/api/routes/protocols.py,
create_quick_todo, ~line 287-291).

H4: ProtocolService.create_from_template()'s auto-derived protocol number was picked via an
exists-check-before-insert race: two concurrent calls for the same template could both see
the same "next" number as free and only one would survive the uq_protocol_tenant_number
unique constraint, with the loser getting a generic 400. Fix: the number pick + insert now
runs inside a retry loop (up to 5 attempts) using a SAVEPOINT scoped to just the insert
attempt (`with db.begin_nested(): ...`, mirroring ParticipantService.import_csv's per-row
retry convention) - on IntegrityError it re-queries fresh counts and retries instead of
surfacing the collision to the caller (backend/app/services/protocol_service.py,
create_from_template, ~line 1012-1080).

Route functions are called directly as plain Python callables (bypassing Depends/ASGI/auth
entirely), matching test_audit_2026_08_12_critical_fixes.py's convention.
"""
from __future__ import annotations

import base64
import time
from datetime import date

import jwt
import pytest
from fastapi import HTTPException
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.routes import protocols as protocols_route
from app.models import AttendanceFine, PlatformOidcConfig, Protocol, ProtocolElement, ProtocolTodo
from app.schemas.protocol import AttendanceExcusePayload, ProtocolCreateFromTemplate, QuickTodoCreate
import app.services.platform_oidc_service as platform_oidc_service_module
from app.services.platform_oidc_service import PlatformOidcService
from app.services.protocol_service import ProtocolService

from tests.factories import (
    make_current_user,
    make_finance_account,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_tenant,
    make_template,
)


# --- H1: JWT alg-header confusion in OIDC verification --------------------------------------


def _b64url_uint(n: int) -> str:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _make_rsa_jwk() -> tuple[object, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": "test-key", "n": _b64url_uint(numbers.n), "e": _b64url_uint(numbers.e)}
    return private_key, jwk


def test_h1_verify_id_token_accepts_legit_rs256_token(monkeypatch):
    private_key, jwk = _make_rsa_jwk()
    monkeypatch.setattr(platform_oidc_service_module, "_fetch_json", lambda url, data=None, headers=None: {"keys": [jwk]})
    discovery = {"jwks_uri": "https://idp.example.com/jwks", "issuer": "https://idp.example.com"}
    cfg = PlatformOidcConfig(issuer_url="https://idp.example.com", client_id="hocx-admin", client_secret="s", enabled=True)

    now = int(time.time())
    claims = {"sub": "admin-1", "aud": "hocx-admin", "iss": "https://idp.example.com", "exp": now + 300, "iat": now}
    good_token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})

    result = PlatformOidcService()._verify_id_token(good_token, discovery, cfg)
    assert result["sub"] == "admin-1"


def test_h1_verify_id_token_rejects_hs256_key_confusion_forgery(monkeypatch):
    """Classic RS256->HS256 key-confusion attack: the attacker forges a token whose header
    claims alg=HS256 (signed with any secret the attacker controls - the point isn't the
    secret, it's that the header alone must never steer verification). Before the fix,
    `algorithms=[header.get("alg", "RS256")]` would have let this attacker-chosen algorithm
    dictate how jwt.decode verifies the token; with the fix, algorithms is hard-coded to
    ["RS256"] so the forged token is rejected purely because its header alg doesn't match the
    server-side allowlist."""
    private_key, jwk = _make_rsa_jwk()
    monkeypatch.setattr(platform_oidc_service_module, "_fetch_json", lambda url, data=None, headers=None: {"keys": [jwk]})
    discovery = {"jwks_uri": "https://idp.example.com/jwks", "issuer": "https://idp.example.com"}
    cfg = PlatformOidcConfig(issuer_url="https://idp.example.com", client_id="hocx-admin", client_secret="s", enabled=True)

    now = int(time.time())
    claims = {"sub": "admin-1", "aud": "hocx-admin", "iss": "https://idp.example.com", "exp": now + 300, "iat": now}
    forged_token = jwt.encode(claims, "attacker-guessable-secret", algorithm="HS256", headers={"kid": "test-key"})

    with pytest.raises(HTTPException) as exc_info:
        PlatformOidcService()._verify_id_token(forged_token, discovery, cfg)
    assert exc_info.value.status_code == 401


def test_h1_verify_id_token_never_derives_algorithm_from_untrusted_header(monkeypatch):
    """Directly pins the fix at the jwt.decode call site: whatever algorithm the token's own
    header claims (RS256 or the forged HS256), the `algorithms=` kwarg passed to jwt.decode
    must always be the same hard-coded server-side allowlist, never read from `header`."""
    private_key, jwk = _make_rsa_jwk()
    monkeypatch.setattr(platform_oidc_service_module, "_fetch_json", lambda url, data=None, headers=None: {"keys": [jwk]})
    discovery = {"jwks_uri": "https://idp.example.com/jwks", "issuer": "https://idp.example.com"}
    cfg = PlatformOidcConfig(issuer_url="https://idp.example.com", client_id="hocx-admin", client_secret="s", enabled=True)

    now = int(time.time())
    claims = {"sub": "admin-1", "aud": "hocx-admin", "iss": "https://idp.example.com", "exp": now + 300, "iat": now}
    forged_token = jwt.encode(claims, "attacker-guessable-secret", algorithm="HS256", headers={"kid": "test-key"})

    original_decode = jwt.decode
    captured_algorithms = []

    def spy_decode(*args, **kwargs):
        captured_algorithms.append(kwargs.get("algorithms"))
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(platform_oidc_service_module.jwt, "decode", spy_decode)

    with pytest.raises(HTTPException):
        PlatformOidcService()._verify_id_token(forged_token, discovery, cfg)

    assert captured_algorithms == [["RS256"]]


# --- H2: Freeze-bypass at attendance/fines ---------------------------------------------------


def _make_frozen_protocol_with_attendance_and_fine(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    participant = make_participant(db, tenant.id, "Anna Muster")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(
        db,
        element.id,
        configuration_snapshot_json={
            "attendance_entries": [
                {"participant_id": participant.id, "participant_name": "Anna Muster", "status": "absent"},
            ]
        },
        element_type_code="attendance",
    )
    account = make_finance_account(db, tenant.id)
    fine = AttendanceFine(
        protocol_id=protocol.id,
        participant_id=participant.id,
        participant_name_snapshot="Anna Muster",
        fine_type="absent",
        amount=10,
        account_id=account.id,
        status="pending",
    )
    db.add(fine)
    db.flush()
    return tenant, protocol, participant, block, fine


def test_h2_excuse_participant_blocked_when_frozen(db):
    tenant, protocol, participant, block, fine = _make_frozen_protocol_with_attendance_and_fine(db)
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        protocols_route.excuse_participant(
            protocol.id, participant.id, payload=AttendanceExcusePayload(excused=True), db=db, user=user,
        )
    assert exc_info.value.status_code == 409

    # Attendance status must be untouched.
    db.refresh(block)
    entries = block.configuration_snapshot_json["attendance_entries"]
    assert entries[0]["status"] == "absent"

    # The pending fine must still exist - excusing a frozen protocol's attendance must not
    # silently delete financial data on an already-finalized protocol.
    still_pending = db.scalar(
        select(AttendanceFine).where(AttendanceFine.id == fine.id, AttendanceFine.status == "pending")
    )
    assert still_pending is not None


def test_h2_excuse_participant_still_works_when_not_frozen(db):
    tenant, protocol, participant, block, fine = _make_frozen_protocol_with_attendance_and_fine(db)
    protocol.status = "geplant"
    db.flush()
    user = make_current_user(tenant.id)

    result = protocols_route.excuse_participant(
        protocol.id, participant.id, payload=AttendanceExcusePayload(excused=True), db=db, user=user,
    )
    assert result["message"] == "Participant excused"
    db.refresh(block)
    entries = block.configuration_snapshot_json["attendance_entries"]
    assert entries[0]["status"] == "excused"
    # Excusing clears the pending fine (existing behavior, unrelated to this fix) - the fine
    # row is fully deleted, not merely a status flip.
    assert db.get(AttendanceFine, fine.id) is None


# --- H3: Freeze-bypass at quick todo creation -------------------------------------------------


def test_h3_create_quick_todo_blocked_when_frozen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        protocols_route.create_quick_todo(protocol.id, QuickTodoCreate(task="Sollte nicht entstehen"), db=db, user=user)
    assert exc_info.value.status_code == 409

    assert db.scalars(select(ProtocolElement).where(ProtocolElement.protocol_id == protocol.id)).all() == []
    assert db.scalar(select(ProtocolTodo).where(ProtocolTodo.task == "Sollte nicht entstehen")) is None


def test_h3_create_quick_todo_still_works_when_not_frozen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    user = make_current_user(tenant.id)

    result = protocols_route.create_quick_todo(protocol.id, QuickTodoCreate(task="Darf entstehen"), db=db, user=user)
    assert result["todo_id"] is not None
    todo = db.get(ProtocolTodo, result["todo_id"])
    assert todo is not None
    assert todo.task == "Darf entstehen"


# --- H4: Race condition in protocol number assignment -----------------------------------------


def test_h4_create_from_template_retries_after_simulated_unique_constraint_collision(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    original_flush = db.flush
    call_count = {"n": 0}

    def flaky_flush(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Simulates a concurrent transaction that committed the same tenant_id +
            # protocol_number first (uq_protocol_tenant_number) between our exists-check and
            # our own insert - the classic read-then-write race this fix closes.
            raise IntegrityError(
                "INSERT INTO protocol (...) VALUES (...)",
                {},
                Exception('duplicate key value violates unique constraint "uq_protocol_tenant_number"'),
            )
        return original_flush(*args, **kwargs)

    db.flush = flaky_flush
    try:
        protocol_id = ProtocolService().create_from_template(
            db,
            ProtocolCreateFromTemplate(template_id=template.id, protocol_date=date(2026, 1, 1)),
            tenant_id=tenant.id,
            created_by=None,
        )
    finally:
        db.flush = original_flush

    # The retry must have actually happened (first attempt failed, second succeeded) rather
    # than the collision surfacing as an error to the caller.
    assert call_count["n"] >= 2
    protocol = db.get(Protocol, protocol_id)
    assert protocol is not None
    assert protocol.protocol_number == "P-1"
    # Exactly one protocol was actually persisted for this number - no duplicate/half-built
    # leftover from the failed first attempt.
    all_with_number = db.scalars(
        select(Protocol).where(Protocol.tenant_id == tenant.id, Protocol.protocol_number == "P-1")
    ).all()
    assert len(all_with_number) == 1


def test_h4_create_from_template_gives_up_after_exhausting_retry_attempts(db):
    """If every retry attempt keeps colliding (e.g. a pathological/stuck race), the retry loop
    must not hang forever - it should eventually let the IntegrityError propagate, same as the
    old behavior did on the very first collision, just after a bounded number of attempts."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    original_flush = db.flush
    call_count = {"n": 0}

    def always_flaky_flush(*args, **kwargs):
        call_count["n"] += 1
        raise IntegrityError(
            "INSERT INTO protocol (...) VALUES (...)",
            {},
            Exception('duplicate key value violates unique constraint "uq_protocol_tenant_number"'),
        )

    db.flush = always_flaky_flush
    try:
        with pytest.raises(IntegrityError):
            ProtocolService().create_from_template(
                db,
                ProtocolCreateFromTemplate(template_id=template.id, protocol_date=date(2026, 1, 1)),
                tenant_id=tenant.id,
                created_by=None,
            )
    finally:
        db.flush = original_flush

    # Bounded retries (up to 5 attempts per the fix), not an infinite/unbounded loop.
    assert 1 <= call_count["n"] <= 5
    assert db.scalars(select(Protocol).where(Protocol.tenant_id == tenant.id)).all() == []


def test_h4_create_from_template_does_not_retry_an_explicit_protocol_number_collision(db):
    """An explicit payload.protocol_number is a deliberate user choice, not an auto-pick - a
    collision there is a genuine conflict (e.g. two people typing the same number at once by
    coincidence, not the auto-increment race) and must fail immediately, not retry."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    db.flush()
    make_protocol(db, tenant.id, template.id, protocol_number="MANUAL-1")

    with pytest.raises(IntegrityError):
        ProtocolService().create_from_template(
            db,
            ProtocolCreateFromTemplate(template_id=template.id, protocol_date=date(2026, 1, 2), protocol_number="MANUAL-1"),
            tenant_id=tenant.id,
            created_by=None,
        )
