from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin
from app.core.rate_limit import check_account_lockout, enforce_rate_limit, record_failed_attempt
from app.core.redis_client import get_redis_sync
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.totp import build_totp_uri, generate_totp_secret, verify_totp_code
from app.core.webauthn import (
    RegisteredCredential,
    WebauthnError,
    build_registration_options,
    generate_challenge,
    register_credential,
)
from app.models import PlatformAdmin, UserMfaFactor
from app.schemas.mfa import (
    MfaFactorRead,
    MfaPendingLoginMethodRead,
    MfaPendingLoginRead,
    PasskeyRegistrationStartRead,
    TotpEnrollmentStartRead,
    UserMfaRead,
)

"""MFA for PlatformAdmin - platform admins are the highest-privilege tier (full cross-tenant
access, backup export, admin management) but previously had no MFA option at all (audit
finding, 2026-08-27), unlike tenant admins (see mfa_service.py's user_requires_mfa /
core.security's get_optional_current_user enforcement), who are forced to enroll TOTP/passkey
MFA before getting a full session.

Also supports WebAuthn/passkeys (added 2026-09-02), self-service only (mirrors
start_self_passkey_registration/complete_self_passkey_registration on MfaService). Unlike
MfaService.rp_id_for_request_host / can_add_passkey_here, which gate on the tenant-facing
traefik_domain because a tenant can be reached through several custom domains (TenantDomain),
the admin panel has no equivalent multi-domain routing - it is only ever served from whatever
host the request actually came in on - so passkeys are always allowed here and the RP ID is
just that request host directly, no traefik_domain comparison needed. Login-time passkey
enrollment (the ticket-based flow, for an admin with zero factors) is intentionally not
included: unlike login-time TOTP setup, a first factor being a passkey would leave the account
with no fallback if the authenticator is unavailable, so the first factor is always TOTP and
passkeys can only be added afterwards as an additional factor via this self-service surface.

Reuses the same TOTP/crypto/WebAuthn primitives (core/totp.py, core/secret_crypto.py,
core/webauthn.py) and rate-limit primitives (core/rate_limit.py) as MfaService/AuthService
rather than re-implementing any of that - only the redis-backed "flow" bookkeeping and the
PlatformAdmin-vs-AppUser wiring are duplicated, mirroring MfaService's own shape closely."""


_FLOW_PREFIX = "admin-mfa:flow:"
_FLOW_TTL_SECONDS = 10 * 60
_ISSUER = "hocX Admin"

# Same rationale as MfaService's login-TOTP account ceiling (audit finding, 2026-08-27, see
# mfa_service.py) - built in from the start here rather than retrofitted, since platform
# admins are the highest-privilege tier and a fresh login ticket is mintable on every
# successful password check just like the tenant flow.
_ACCOUNT_TOTP_ATTEMPT_LIMIT = 10
_ACCOUNT_TOTP_WINDOW_SECONDS = 15 * 60


@dataclass
class AdminPendingLoginContext:
    admin: PlatformAdmin


class AdminMfaService:
    def _redis(self):
        return get_redis_sync()

    def _create_flow(self, kind: str, data: dict[str, Any], *, ttl_seconds: int = _FLOW_TTL_SECONDS) -> str:
        token = secrets.token_urlsafe(32)
        payload = json.dumps({"kind": kind, **data})
        self._redis().set(f"{_FLOW_PREFIX}{token}", payload, nx=True, ex=ttl_seconds)
        return token

    def _load_flow(self, token: str, *, expected_kind: str) -> dict[str, Any]:
        raw = self._redis().get(f"{_FLOW_PREFIX}{token}")
        if raw is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA-Vorgang ist abgelaufen")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger MFA-Vorgang") from exc
        if data.get("kind") != expected_kind:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger MFA-Vorgang")
        return data

    def _delete_flow(self, token: str) -> None:
        self._redis().delete(f"{_FLOW_PREFIX}{token}")

    def _list_factors(self, db: Session, admin_id: int, *, factor_type: str | None = None) -> list[UserMfaFactor]:
        statement = (
            select(UserMfaFactor)
            .where(UserMfaFactor.platform_admin_id == admin_id)
            .order_by(UserMfaFactor.created_at.asc(), UserMfaFactor.id.asc())
        )
        if factor_type is not None:
            statement = statement.where(UserMfaFactor.factor_type == factor_type)
        return list(db.scalars(statement))

    def _get_factor(self, db: Session, *, factor_id: int, admin_id: int) -> UserMfaFactor | None:
        return db.scalar(
            select(UserMfaFactor).where(UserMfaFactor.id == factor_id, UserMfaFactor.platform_admin_id == admin_id)
        )

    def _factor_read(self, factor: UserMfaFactor) -> MfaFactorRead:
        return MfaFactorRead(
            id=factor.public_id,
            factor_type=factor.factor_type,  # type: ignore[arg-type]
            label=factor.label,
            created_at=factor.created_at,
            last_used_at=factor.last_used_at,
        )

    def _default_totp_label(self, admin: PlatformAdmin) -> str:
        return f"Authenticator App für {admin.email}"

    def _default_passkey_label(self, admin: PlatformAdmin) -> str:
        return f"Passkey für {admin.email}"

    def _preferred_factor_type(self, factors: list[UserMfaFactor]) -> str | None:
        if not factors:
            return None
        return "webauthn" if any(factor.factor_type == "webauthn" for factor in factors) else "totp"

    def _preferred_factor_label(self, factors: list[UserMfaFactor]) -> str | None:
        preferred = self._preferred_factor_type(factors)
        if preferred is None:
            return None
        return "Passkey" if preferred == "webauthn" else "Authenticator-App"

    def get_self_overview(self, db: Session, actor: CurrentAdmin) -> UserMfaRead:
        factors = self._list_factors(db, actor.admin_id)
        return UserMfaRead(
            required=True,
            has_factors=bool(factors),
            can_add_passkey_here=True,
            preferred_factor_type=self._preferred_factor_type(factors),  # type: ignore[arg-type]
            preferred_factor_label=self._preferred_factor_label(factors),
            factors=[self._factor_read(factor) for factor in factors],
        )

    # ---- self-service enrollment (already-authenticated admin) ----

    def start_self_totp_enrollment(self, db: Session, actor: CurrentAdmin) -> TotpEnrollmentStartRead:
        admin = db.get(PlatformAdmin, actor.admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
        secret = generate_totp_secret()
        flow_token = self._create_flow("admin_self_totp_enrollment", {"admin_id": admin.id, "secret": secret})
        return TotpEnrollmentStartRead(
            flow_token=flow_token,
            secret=secret,
            manual_entry_key=secret,
            provisioning_uri=build_totp_uri(issuer=_ISSUER, account_name=admin.email, secret=secret),
            issuer=_ISSUER,
            account_name=admin.email,
        )

    def complete_self_totp_enrollment(
        self, db: Session, actor: CurrentAdmin, *, flow_token: str, code: str, label: str | None
    ) -> UserMfaFactor:
        return self._complete_totp_enrollment(
            db,
            flow_token=flow_token,
            code=code,
            label=label,
            expected_kind="admin_self_totp_enrollment",
            expected_admin_id=actor.admin_id,
        )

    def _rp_id_for_request_host(self, request_host: str | None) -> str:
        if not request_host:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passkeys benötigen einen gültigen Hostnamen")
        return request_host

    def start_self_passkey_registration(
        self,
        db: Session,
        actor: CurrentAdmin,
        *,
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyRegistrationStartRead:
        admin = db.get(PlatformAdmin, actor.admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
        rp_id = self._rp_id_for_request_host(request_host)
        challenge = generate_challenge()
        exclude_credentials = [
            {
                "id": factor.webauthn_credential_id,
                "type": "public-key",
                "transports": factor.webauthn_transports_json or [],
            }
            for factor in self._list_factors(db, admin.id, factor_type="webauthn")
            if factor.webauthn_rp_id == rp_id and factor.webauthn_credential_id
        ]
        flow_token = self._create_flow(
            "admin_self_passkey_registration",
            {
                "admin_id": admin.id,
                "challenge": challenge,
                "rp_id": rp_id,
                "origin": request_origin,
            },
        )
        return PasskeyRegistrationStartRead(
            flow_token=flow_token,
            public_key=build_registration_options(
                rp_id=rp_id,
                rp_name=_ISSUER,
                user_id=admin.id,
                user_name=admin.email,
                display_name=admin.display_name,
                challenge=challenge,
                exclude_credentials=exclude_credentials,
            ),
        )

    def complete_self_passkey_registration(
        self, db: Session, actor: CurrentAdmin, *, flow_token: str, label: str | None, credential: dict[str, Any]
    ) -> UserMfaFactor:
        flow = self._load_flow(flow_token, expected_kind="admin_self_passkey_registration")
        if int(flow["admin_id"]) != actor.admin_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dieser MFA-Vorgang gehört zu einem anderen Konto")
        admin = db.get(PlatformAdmin, actor.admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
        try:
            registered = register_credential(
                credential,
                expected_challenge=str(flow["challenge"]),
                expected_origin=str(flow["origin"]),
                expected_rp_id=str(flow["rp_id"]),
            )
        except WebauthnError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        existing = db.scalar(
            select(UserMfaFactor).where(UserMfaFactor.webauthn_credential_id == registered.credential_id)
        )
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Diese Passkey-Anmeldung ist bereits hinterlegt")
        factor = self._create_passkey_factor(db, admin, registered, rp_id=str(flow["rp_id"]), label=label)
        self._delete_flow(flow_token)
        return factor

    def _create_passkey_factor(
        self, db: Session, admin: PlatformAdmin, registered: RegisteredCredential, *, rp_id: str, label: str | None
    ) -> UserMfaFactor:
        factor = UserMfaFactor(
            platform_admin_id=admin.id,
            factor_type="webauthn",
            label=(label or self._default_passkey_label(admin)).strip() or self._default_passkey_label(admin),
            webauthn_credential_id=registered.credential_id,
            webauthn_public_key_pem=registered.public_key_pem,
            webauthn_sign_count=registered.sign_count,
            webauthn_aaguid=registered.aaguid,
            webauthn_rp_id=rp_id,
            webauthn_transports_json=registered.transports,
            last_used_at=datetime.now(UTC),
        )
        db.add(factor)
        db.commit()
        db.refresh(factor)
        return factor

    def delete_self_factor(self, db: Session, actor: CurrentAdmin, factor_id: int) -> UserMfaRead:
        factor = self._get_factor(db, factor_id=factor_id, admin_id=actor.admin_id)
        if factor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MFA-Faktor nicht gefunden")
        remaining = len(self._list_factors(db, actor.admin_id)) - 1
        if remaining == 0:
            # Every platform admin requires MFA unconditionally (unlike tenant users, where
            # this guard only applies to admin-role members) - see get_self_overview's
            # required=True and admin_security.get_optional_current_admin's enforcement.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Platform-Administratoren müssen mindestens einen MFA-Faktor behalten",
            )
        db.delete(factor)
        db.commit()
        return self.get_self_overview(db, actor)

    # ---- login-ticket flow (mirrors MfaService.prepare_login / verify_login_totp) ----

    def prepare_login(self, db: Session, admin: PlatformAdmin) -> MfaPendingLoginRead:
        """Unlike MfaService.prepare_login for tenant users, this never returns None: every
        platform admin requires MFA, so a correct password alone never grants a session -
        it always returns a pending ticket, either for verification (a factor already
        exists) or forced setup (none yet)."""
        factors = self._list_factors(db, admin.id)
        ticket = self._create_flow("admin_login_ticket", {"admin_id": admin.id})
        if factors:
            return self._build_pending_login(ticket=ticket, admin=admin, status_value="verification_required", has_factor=True)
        return self._build_pending_login(ticket=ticket, admin=admin, status_value="setup_required", has_factor=False)

    def _build_pending_login(
        self, *, ticket: str, admin: PlatformAdmin, status_value: str, has_factor: bool
    ) -> MfaPendingLoginRead:
        methods = [MfaPendingLoginMethodRead(factor_type="totp", label="Authenticator-App")] if has_factor else []
        return MfaPendingLoginRead(
            status=status_value,  # type: ignore[arg-type]
            ticket=ticket,
            required=True,
            user_display_name=admin.display_name,
            user_email=admin.email,
            tenant_name=None,
            available_methods=methods,
            default_factor_type="totp" if has_factor else None,
            default_factor_label="Authenticator-App" if has_factor else None,
            can_add_totp=True,
            can_add_passkey=False,
        )

    def _load_login_ticket(self, db: Session, ticket: str) -> AdminPendingLoginContext:
        flow = self._load_flow(ticket, expected_kind="admin_login_ticket")
        admin = db.get(PlatformAdmin, int(flow["admin_id"]))
        if admin is None or not admin.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin-Konto ist nicht mehr aktiv")
        return AdminPendingLoginContext(admin=admin)

    def _consume_login_ticket(self, db: Session, ticket: str) -> AdminPendingLoginContext:
        context = self._load_login_ticket(db, ticket)
        self._delete_flow(ticket)
        return context

    def start_login_totp_enrollment(self, db: Session, ticket: str) -> TotpEnrollmentStartRead:
        context = self._load_login_ticket(db, ticket)
        secret = generate_totp_secret()
        flow_token = self._create_flow(
            "admin_login_totp_enrollment",
            {"admin_id": context.admin.id, "secret": secret, "ticket": ticket},
        )
        return TotpEnrollmentStartRead(
            flow_token=flow_token,
            secret=secret,
            manual_entry_key=secret,
            provisioning_uri=build_totp_uri(issuer=_ISSUER, account_name=context.admin.email, secret=secret),
            issuer=_ISSUER,
            account_name=context.admin.email,
        )

    def complete_login_totp_enrollment(
        self, db: Session, *, flow_token: str, code: str, label: str | None
    ) -> AdminPendingLoginContext:
        flow = self._load_flow(flow_token, expected_kind="admin_login_totp_enrollment")
        self._complete_totp_enrollment(
            db,
            flow_token=flow_token,
            code=code,
            label=label,
            expected_kind="admin_login_totp_enrollment",
            expected_admin_id=int(flow["admin_id"]),
        )
        return self._consume_login_ticket(db, str(flow["ticket"]))

    def _complete_totp_enrollment(
        self,
        db: Session,
        *,
        flow_token: str,
        code: str,
        label: str | None,
        expected_kind: str,
        expected_admin_id: int,
    ) -> UserMfaFactor:
        flow = self._load_flow(flow_token, expected_kind=expected_kind)
        if int(flow["admin_id"]) != expected_admin_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dieser MFA-Vorgang gehört zu einem anderen Konto")
        admin = db.get(PlatformAdmin, expected_admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
        secret = str(flow["secret"])
        enforce_rate_limit(f"admin-mfa-enroll-totp:{flow_token}", limit=10, period_seconds=_FLOW_TTL_SECONDS)
        counter = verify_totp_code(secret, code)
        if counter is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Der TOTP-Code ist nicht gültig")
        factor = UserMfaFactor(
            platform_admin_id=admin.id,
            factor_type="totp",
            label=(label or self._default_totp_label(admin)).strip() or self._default_totp_label(admin),
            secret_encrypted=encrypt_secret(secret),
            totp_last_counter=counter,
            last_used_at=datetime.now(UTC),
        )
        db.add(factor)
        db.commit()
        db.refresh(factor)
        self._delete_flow(flow_token)
        return factor

    def verify_login_totp(self, db: Session, *, ticket: str, code: str) -> AdminPendingLoginContext:
        context = self._load_login_ticket(db, ticket)
        # Account-level ceiling first (see mfa_service.py's identical 2026-08-27 fix for the
        # tenant-user equivalent) - this is what actually stops multi-ticket abuse; the
        # per-ticket limit below is kept as defense in depth for a single ticket being
        # hammered.
        account_lockout_key = f"admin-mfa-account:{context.admin.id}"
        check_account_lockout(account_lockout_key, limit=_ACCOUNT_TOTP_ATTEMPT_LIMIT)
        enforce_rate_limit(f"admin-mfa-login-totp:{ticket}", limit=10, period_seconds=_FLOW_TTL_SECONDS)
        factors = self._list_factors(db, context.admin.id)
        if not factors:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Für dieses Konto ist kein TOTP-Faktor hinterlegt")
        for factor in factors:
            if not factor.secret_encrypted:
                continue
            counter = verify_totp_code(
                decrypt_secret(factor.secret_encrypted),
                code,
                min_counter=factor.totp_last_counter,
            )
            if counter is None:
                continue
            factor.totp_last_counter = counter
            factor.last_used_at = datetime.now(UTC)
            db.add(factor)
            db.commit()
            return self._consume_login_ticket(db, ticket)
        record_failed_attempt(account_lockout_key, period_seconds=_ACCOUNT_TOTP_WINDOW_SECONDS)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Der TOTP-Code ist nicht gültig")
