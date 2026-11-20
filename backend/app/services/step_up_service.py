"""Step-up-Prüfung (SEC-AUTH-010): Faktor bzw. Passwort bestätigen, Frische der Session setzen.

Siehe app/auth_security/step_up.py für die Regel und die geschützten Aktionen."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth_security import context as request_context
from app.auth_security import events
from app.auth_security import sessions as session_register
from app.auth_security.guard import consume_factor_attempt, refund_factor_attempt
from app.core.rate_limit import consume_attempt, release_attempt
from app.core.secret_crypto import decrypt_secret
from app.core.security import CurrentUser, issue_session_cookie, verify_password
from app.core.totp import verify_totp_code
from app.core.webauthn import WebauthnError, build_assertion_options, generate_challenge, verify_assertion
from app.models import AppUser, AuthSession, UserMfaFactor
from app.schemas.step_up import StepUpOptionsRead, StepUpRead, StepUpRequest
from app.schemas.mfa import PasskeyAssertionStartRead
from app.services.mfa_service import MfaService, claim_totp_counter

_PASSWORD_LIMIT = 10
_WINDOW = 15 * 60


class StepUpService:
    def __init__(self) -> None:
        self.mfa = MfaService()

    def _methods(self, db: Session, user_id: int, request_host: str | None) -> list[str]:
        factors = self.mfa._list_factors(db, user_id)
        methods: list[str] = []
        if any(factor.factor_type == "totp" and factor.secret_encrypted for factor in factors):
            methods.append("totp")
        if self.mfa.can_add_passkey_here(request_host) and any(factor.factor_type == "webauthn" for factor in factors):
            methods.append("passkey")
        if not factors:
            methods.append("password")
        return methods

    def options(self, db: Session, user: CurrentUser, request_host: str | None) -> StepUpOptionsRead:
        return StepUpOptionsRead(methods=self._methods(db, user.user_id, request_host), auth_time=user.auth_time)  # type: ignore[arg-type]

    def start_passkey(self, db: Session, user: CurrentUser, *, request_host: str | None, request_origin: str) -> PasskeyAssertionStartRead:
        rp_id = self.mfa.rp_id_for_request_host(request_host)
        factors = [
            factor for factor in self.mfa._list_factors(db, user.user_id, factor_type="webauthn")
            if factor.webauthn_rp_id == rp_id and factor.webauthn_credential_id
        ]
        if not factors:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "passkey_not_registered", "message": "Kein Passkey auf dieser Domain"})
        challenge = generate_challenge()
        flow_token = self.mfa._create_flow("step_up_passkey", {"user_id": user.user_id, "challenge": challenge, "rp_id": rp_id, "origin": request_origin})
        return PasskeyAssertionStartRead(
            flow_token=flow_token,
            public_key=build_assertion_options(
                challenge=challenge, rp_id=rp_id,
                allow_credentials=[{"id": f.webauthn_credential_id, "type": "public-key", "transports": f.webauthn_transports_json or []} for f in factors],
            ),
        )

    def _fail(self, user: CurrentUser, method: str, code: str, message: str) -> HTTPException:
        events.record(event_type="stepup.failure", outcome="failure", user_id=user.user_id, tenant_id=user.current_tenant_id,
                      session_id=user.session_id, details={"method": method})
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": code, "message": message})

    def _verify_totp(self, db: Session, user: CurrentUser, code: str) -> None:
        attempt = consume_factor_attempt(user.user_id, kind="totp")
        for factor in self.mfa._list_factors(db, user.user_id, factor_type="totp"):
            if not factor.secret_encrypted:
                continue
            counter = verify_totp_code(decrypt_secret(factor.secret_encrypted), code, min_counter=factor.totp_last_counter)
            if counter is not None and claim_totp_counter(db, factor.id, counter):
                refund_factor_attempt(attempt)
                return
        raise self._fail(user, "totp", "totp_invalid", "Der TOTP-Code ist nicht gültig")

    def _verify_passkey(self, db: Session, user: CurrentUser, flow_token: str, credential: dict[str, Any]) -> None:
        flow = self.mfa._load_flow(flow_token, expected_kind="step_up_passkey")
        if int(flow["user_id"]) != user.user_id:
            raise self._fail(user, "passkey", "mfa_flow_invalid", "Ungültiger Vorgang")
        attempt = consume_factor_attempt(user.user_id, kind="passkey")
        credential_id = credential.get("rawId") or credential.get("id")
        factor = None
        if isinstance(credential_id, str) and credential_id:
            factor = db.query(UserMfaFactor).filter(
                UserMfaFactor.user_id == user.user_id, UserMfaFactor.factor_type == "webauthn",
                UserMfaFactor.webauthn_credential_id == credential_id, UserMfaFactor.webauthn_rp_id == str(flow["rp_id"]),
            ).one_or_none()
        if factor is None or not factor.webauthn_public_key_pem:
            raise self._fail(user, "passkey", "passkey_unknown", "Unbekannte Passkey-Anmeldung")
        try:
            result = verify_assertion(
                credential, expected_challenge=str(flow["challenge"]), expected_origin=str(flow["origin"]), expected_rp_id=str(flow["rp_id"]),
                public_key_pem=factor.webauthn_public_key_pem, stored_sign_count=factor.webauthn_sign_count or 0, expected_credential_id=credential_id,
            )
        except WebauthnError as exc:
            raise self._fail(user, "passkey", "passkey_invalid", str(exc)) from exc
        factor.webauthn_sign_count = result.sign_count
        factor.last_used_at = datetime.now(UTC)
        db.commit()
        self.mfa._delete_flow(flow_token)
        refund_factor_attempt(attempt)

    def _verify_password(self, db: Session, user: CurrentUser, password: str) -> None:
        key = f"stepup-password:{user.user_id}"
        consume_attempt(key, limit=_PASSWORD_LIMIT, period_seconds=_WINDOW)
        account = db.get(AppUser, user.user_id)
        if account is None or not account.password_hash or not verify_password(password, account.password_hash):
            raise self._fail(user, "password", "wrong_current_password", "Passwort ist nicht korrekt")
        release_attempt(key)

    def verify(self, db: Session, response: Response, user: CurrentUser, payload: StepUpRequest, *, request_host: str | None) -> StepUpRead:
        methods = self._methods(db, user.user_id, request_host)
        if payload.method not in methods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "step_up_method_unavailable", "message": "Diese Bestätigung ist für dein Konto nicht möglich"})
        if payload.method == "totp":
            self._verify_totp(db, user, payload.code or "")
        elif payload.method == "passkey":
            if not payload.flow_token or payload.credential is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "passkey_invalid", "message": "Passkey-Antwort fehlt"})
            self._verify_passkey(db, user, payload.flow_token, payload.credential)
        else:
            self._verify_password(db, user, payload.password or "")
        record = db.get(AuthSession, user.session_id) if user.session_id else None
        if record is None:
            # Session von vor dem Update (ohne sid): ins Register übernehmen, neues Cookie
            ctx = request_context.current()
            # Ende = Ablauf des alten Tokens, keine Verlängerung (Security-Review N5)
            record = session_register.adopt_legacy(
                db, user_id=user.user_id, tenant_id=user.current_tenant_id, mfa=user.mfa_verified, issued_at=user.token_issued_at,
                expires_at=user.token_expires_at, host=request_host, ip_net_hash=ctx.net_hash, user_agent_family=ctx.user_agent_family,
            )
        session_register.mark_strong_auth(db, record, payload.method)
        db.commit()
        if user.session_id != record.id:
            issue_session_cookie(response, user.user_id, mfa_verified=record.mfa, sid=str(record.id), expires_at=record.expires_at)
        events.record(event_type="stepup.success", outcome="success", user_id=user.user_id, tenant_id=user.current_tenant_id,
                      session_id=record.id, details={"method": payload.method})
        return StepUpRead(auth_time=record.auth_time)
