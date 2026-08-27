from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rate_limit import enforce_rate_limit
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.security import CurrentUser, build_current_user, require_admin
from app.core.totp import build_totp_uri, generate_totp_secret, verify_totp_code
from app.core.webauthn import (
    RegisteredCredential,
    WebauthnError,
    build_assertion_options,
    build_registration_options,
    generate_challenge,
    register_credential,
    verify_assertion,
)
from app.core.config import settings
from app.core.redis_client import get_redis_sync
from app.models import AppUser, Role, UserMfaFactor, UserTenantRole
from app.schemas.mfa import (
    MfaFactorRead,
    MfaPendingLoginMethodRead,
    MfaPendingLoginRead,
    PasskeyAssertionStartRead,
    PasskeyRegistrationStartRead,
    TotpEnrollmentStartRead,
    UserMfaRead,
)


_FLOW_PREFIX = "mfa:flow:"
_FLOW_TTL_SECONDS = 10 * 60
_ISSUER = "hocX"


@dataclass
class PendingLoginContext:
    user: AppUser
    current_user: CurrentUser
    request_host: str | None


class MfaService:
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

    def _list_factors(self, db: Session, user_id: int, *, factor_type: str | None = None) -> list[UserMfaFactor]:
        statement = select(UserMfaFactor).where(UserMfaFactor.user_id == user_id).order_by(UserMfaFactor.created_at.asc(), UserMfaFactor.id.asc())
        if factor_type is not None:
            statement = statement.where(UserMfaFactor.factor_type == factor_type)
        return list(db.scalars(statement))

    def _get_factor(self, db: Session, *, factor_id: int, user_id: int) -> UserMfaFactor | None:
        return db.scalar(select(UserMfaFactor).where(UserMfaFactor.id == factor_id, UserMfaFactor.user_id == user_id))

    def user_requires_mfa(self, db: Session, user_id: int) -> bool:
        admin_role_id = db.scalar(select(Role.id).where(Role.code == "admin"))
        if admin_role_id is None:
            return False
        return (
            db.scalar(
                select(func.count())
                .select_from(UserTenantRole)
                .where(
                    UserTenantRole.user_id == user_id,
                    UserTenantRole.role_id == admin_role_id,
                    UserTenantRole.is_active.is_(True),
                )
            )
            > 0
        )

    def can_add_passkey_here(self, request_host: str | None) -> bool:
        if not request_host:
            return False
        if settings.traefik_domain:
            return request_host == settings.traefik_domain
        return True

    def rp_id_for_request_host(self, request_host: str | None) -> str:
        if not request_host:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passkeys benötigen einen gültigen Hostnamen")
        if settings.traefik_domain:
            return settings.traefik_domain
        return request_host

    def _method_labels_by_type(self, factors: list[UserMfaFactor]) -> dict[str, str]:
        labels: dict[str, str] = {}
        totp_count = sum(1 for factor in factors if factor.factor_type == "totp")
        passkey_count = sum(1 for factor in factors if factor.factor_type == "webauthn")
        if totp_count:
            labels["totp"] = "Authenticator-App" if totp_count == 1 else f"{totp_count} Authenticator-Apps"
        if passkey_count:
            labels["webauthn"] = "Passkey" if passkey_count == 1 else f"{passkey_count} Passkeys"
        return labels

    def _resolve_preferred_factor_type(self, user: AppUser, factors: list[UserMfaFactor]) -> str | None:
        if not factors:
            return None
        available_types: list[str] = []
        for factor in factors:
            if factor.factor_type not in available_types:
                available_types.append(factor.factor_type)
        if user.preferred_mfa_factor_type in available_types:
            return user.preferred_mfa_factor_type
        if "webauthn" in available_types:
            return "webauthn"
        return available_types[0]

    def _sync_preferred_factor_type(self, db: Session, user: AppUser, factors: list[UserMfaFactor]) -> str | None:
        effective_type = self._resolve_preferred_factor_type(user, factors)
        if user.preferred_mfa_factor_type == effective_type:
            return effective_type
        user.preferred_mfa_factor_type = effective_type
        db.add(user)
        db.commit()
        db.refresh(user)
        return effective_type

    def _factor_read(self, factor: UserMfaFactor) -> MfaFactorRead:
        return MfaFactorRead(
            id=factor.public_id,
            factor_type=factor.factor_type,  # type: ignore[arg-type]
            label=factor.label,
            created_at=factor.created_at,
            last_used_at=factor.last_used_at,
        )

    def _overview_read(
        self,
        *,
        user: AppUser,
        factors: list[UserMfaFactor],
        required: bool,
        can_add_passkey_here: bool,
    ) -> UserMfaRead:
        preferred_factor_type = self._resolve_preferred_factor_type(user, factors)
        method_labels = self._method_labels_by_type(factors)
        return UserMfaRead(
            required=required,
            has_factors=bool(factors),
            can_add_passkey_here=can_add_passkey_here,
            preferred_factor_type=preferred_factor_type,  # type: ignore[arg-type]
            preferred_factor_label=method_labels.get(preferred_factor_type) if preferred_factor_type else None,
            factors=[self._factor_read(factor) for factor in factors],
        )

    def get_self_overview(self, db: Session, actor: CurrentUser, request_host: str | None) -> UserMfaRead:
        user = db.get(AppUser, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        factors = self._list_factors(db, actor.user_id)
        return self._overview_read(
            user=user,
            factors=factors,
            required=self.user_requires_mfa(db, actor.user_id),
            can_add_passkey_here=self.can_add_passkey_here(request_host),
        )

    def _managed_user(self, db: Session, actor: CurrentUser, user_id: int) -> AppUser:
        require_admin(actor)
        manageable_ids = {
            membership.user_id
            for membership in db.scalars(
                select(UserTenantRole).where(
                    UserTenantRole.tenant_id == actor.current_tenant_id,
                    UserTenantRole.is_active.is_(True),
                )
            )
        }
        if user_id not in manageable_ids:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user = db.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    def get_managed_user_overview(self, db: Session, actor: CurrentUser, user_id: int) -> UserMfaRead:
        user = self._managed_user(db, actor, user_id)
        factors = self._list_factors(db, user.id)
        return self._overview_read(
            user=user,
            factors=factors,
            required=self.user_requires_mfa(db, user.id),
            can_add_passkey_here=False,
        )

    def get_platform_admin_user_overview(self, db: Session, user_id: int) -> UserMfaRead:
        user = db.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        factors = self._list_factors(db, user.id)
        return self._overview_read(
            user=user,
            factors=factors,
            required=self.user_requires_mfa(db, user.id),
            can_add_passkey_here=False,
        )

    def delete_self_factor(self, db: Session, actor: CurrentUser, factor_id: int) -> UserMfaRead:
        factor = self._get_factor(db, factor_id=factor_id, user_id=actor.user_id)
        if factor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MFA-Faktor nicht gefunden")
        user = db.get(AppUser, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        remaining = db.scalar(
            select(func.count())
            .select_from(UserMfaFactor)
            .where(UserMfaFactor.user_id == actor.user_id, UserMfaFactor.id != factor.id)
        )
        if self.user_requires_mfa(db, actor.user_id) and remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tenant-Administratoren müssen mindestens einen MFA-Faktor behalten",
            )
        db.delete(factor)
        db.commit()
        self._sync_preferred_factor_type(db, user, self._list_factors(db, actor.user_id))
        return self.get_self_overview(db, actor, request_host=None)

    def delete_managed_user_factor(self, db: Session, actor: CurrentUser, user_id: int, factor_id: int) -> UserMfaRead:
        user = self._managed_user(db, actor, user_id)
        factor = self._get_factor(db, factor_id=factor_id, user_id=user.id)
        if factor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MFA-Faktor nicht gefunden")
        db.delete(factor)
        db.commit()
        self._sync_preferred_factor_type(db, user, self._list_factors(db, user.id))
        return self.get_managed_user_overview(db, actor, user.id)

    def delete_platform_admin_user_factor(self, db: Session, user_id: int, factor_id: int) -> UserMfaRead:
        user = db.get(AppUser, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        factor = self._get_factor(db, factor_id=factor_id, user_id=user.id)
        if factor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MFA-Faktor nicht gefunden")
        db.delete(factor)
        db.commit()
        self._sync_preferred_factor_type(db, user, self._list_factors(db, user.id))
        return self.get_platform_admin_user_overview(db, user.id)

    def set_self_preferred_method(self, db: Session, actor: CurrentUser, *, factor_type: str, request_host: str | None) -> UserMfaRead:
        user = db.get(AppUser, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        factors = self._list_factors(db, actor.user_id)
        if factor_type not in {factor.factor_type for factor in factors}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Diese MFA-Methode ist für dieses Konto noch nicht eingerichtet",
            )
        user.preferred_mfa_factor_type = factor_type
        db.add(user)
        db.commit()
        return self.get_self_overview(db, actor, request_host)

    def _default_totp_label(self, user: AppUser) -> str:
        return f"Authenticator App für {user.email}"

    def _default_passkey_label(self, user: AppUser) -> str:
        return f"Passkey für {user.email}"

    def start_self_totp_enrollment(self, db: Session, actor: CurrentUser) -> TotpEnrollmentStartRead:
        user = db.get(AppUser, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        secret = generate_totp_secret()
        flow_token = self._create_flow("self_totp_enrollment", {"user_id": user.id, "secret": secret})
        return TotpEnrollmentStartRead(
            flow_token=flow_token,
            secret=secret,
            manual_entry_key=secret,
            provisioning_uri=build_totp_uri(issuer=_ISSUER, account_name=user.email, secret=secret),
            issuer=_ISSUER,
            account_name=user.email,
        )

    def complete_self_totp_enrollment(self, db: Session, actor: CurrentUser, *, flow_token: str, code: str, label: str | None) -> UserMfaFactor:
        return self._complete_totp_enrollment(
            db,
            flow_token=flow_token,
            code=code,
            label=label,
            expected_kind="self_totp_enrollment",
            expected_user_id=actor.user_id,
        )

    def start_login_totp_enrollment(self, db: Session, ticket: str) -> TotpEnrollmentStartRead:
        context = self._load_login_ticket(db, ticket)
        secret = generate_totp_secret()
        flow_token = self._create_flow(
            "login_totp_enrollment",
            {"user_id": context.user.id, "secret": secret, "ticket": ticket},
        )
        return TotpEnrollmentStartRead(
            flow_token=flow_token,
            secret=secret,
            manual_entry_key=secret,
            provisioning_uri=build_totp_uri(issuer=_ISSUER, account_name=context.user.email, secret=secret),
            issuer=_ISSUER,
            account_name=context.user.email,
        )

    def complete_login_totp_enrollment(self, db: Session, *, flow_token: str, code: str, label: str | None) -> PendingLoginContext:
        flow = self._load_flow(flow_token, expected_kind="login_totp_enrollment")
        factor = self._complete_totp_enrollment(
            db,
            flow_token=flow_token,
            code=code,
            label=label,
            expected_kind="login_totp_enrollment",
            expected_user_id=int(flow["user_id"]),
            ticket_to_preserve=str(flow["ticket"]),
        )
        _ = factor
        return self._consume_login_ticket(db, str(flow["ticket"]))

    def _complete_totp_enrollment(
        self,
        db: Session,
        *,
        flow_token: str,
        code: str,
        label: str | None,
        expected_kind: str,
        expected_user_id: int,
        ticket_to_preserve: str | None = None,
    ) -> UserMfaFactor:
        flow = self._load_flow(flow_token, expected_kind=expected_kind)
        if int(flow["user_id"]) != expected_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dieser MFA-Vorgang gehört zu einem anderen Benutzer")
        user = db.get(AppUser, expected_user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        secret = str(flow["secret"])
        enforce_rate_limit(f"mfa-enroll-totp:{flow_token}", limit=10, period_seconds=_FLOW_TTL_SECONDS)
        counter = verify_totp_code(secret, code)
        if counter is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Der TOTP-Code ist nicht gültig")
        factor = UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label=(label or self._default_totp_label(user)).strip() or self._default_totp_label(user),
            secret_encrypted=encrypt_secret(secret),
            totp_last_counter=counter,
            last_used_at=datetime.now(UTC),
        )
        db.add(factor)
        db.commit()
        db.refresh(factor)
        self._sync_preferred_factor_type(db, user, self._list_factors(db, user.id))
        self._delete_flow(flow_token)
        return factor

    def start_self_passkey_registration(
        self,
        db: Session,
        actor: CurrentUser,
        *,
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyRegistrationStartRead:
        user = db.get(AppUser, actor.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return self._start_passkey_registration(
            db,
            user=user,
            flow_kind="self_passkey_registration",
            extra_flow_data={},
            request_host=request_host,
            request_origin=request_origin,
        )

    def start_login_passkey_registration(
        self,
        db: Session,
        ticket: str,
        *,
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyRegistrationStartRead:
        context = self._load_login_ticket(db, ticket)
        return self._start_passkey_registration(
            db,
            user=context.user,
            flow_kind="login_passkey_registration",
            extra_flow_data={"ticket": ticket},
            request_host=request_host,
            request_origin=request_origin,
        )

    def _start_passkey_registration(
        self,
        db: Session,
        *,
        user: AppUser,
        flow_kind: str,
        extra_flow_data: dict[str, Any],
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyRegistrationStartRead:
        if not self.can_add_passkey_here(request_host):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passkeys können nur auf der Hauptdomain eingerichtet werden",
            )
        rp_id = self.rp_id_for_request_host(request_host)
        challenge = generate_challenge()
        exclude_credentials = [
            {
                "id": factor.webauthn_credential_id,
                "type": "public-key",
                "transports": factor.webauthn_transports_json or [],
            }
            for factor in self._list_factors(db, user.id, factor_type="webauthn")
            if factor.webauthn_rp_id == rp_id and factor.webauthn_credential_id
        ]
        flow_token = self._create_flow(
            flow_kind,
            {
                "user_id": user.id,
                "challenge": challenge,
                "rp_id": rp_id,
                "origin": request_origin,
                **extra_flow_data,
            },
        )
        return PasskeyRegistrationStartRead(
            flow_token=flow_token,
            public_key=build_registration_options(
                rp_id=rp_id,
                rp_name=_ISSUER,
                user_id=user.id,
                user_name=user.email,
                display_name=user.display_name,
                challenge=challenge,
                exclude_credentials=exclude_credentials,
            ),
        )

    def complete_self_passkey_registration(
        self,
        db: Session,
        actor: CurrentUser,
        *,
        flow_token: str,
        label: str | None,
        credential: dict[str, Any],
    ) -> UserMfaFactor:
        return self._complete_passkey_registration(
            db,
            flow_token=flow_token,
            label=label,
            credential=credential,
            expected_kind="self_passkey_registration",
            expected_user_id=actor.user_id,
        )

    def complete_login_passkey_registration(
        self,
        db: Session,
        *,
        flow_token: str,
        label: str | None,
        credential: dict[str, Any],
    ) -> PendingLoginContext:
        flow = self._load_flow(flow_token, expected_kind="login_passkey_registration")
        self._complete_passkey_registration(
            db,
            flow_token=flow_token,
            label=label,
            credential=credential,
            expected_kind="login_passkey_registration",
            expected_user_id=int(flow["user_id"]),
        )
        return self._consume_login_ticket(db, str(flow["ticket"]))

    def _complete_passkey_registration(
        self,
        db: Session,
        *,
        flow_token: str,
        label: str | None,
        credential: dict[str, Any],
        expected_kind: str,
        expected_user_id: int,
    ) -> UserMfaFactor:
        flow = self._load_flow(flow_token, expected_kind=expected_kind)
        if int(flow["user_id"]) != expected_user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dieser MFA-Vorgang gehört zu einem anderen Benutzer")
        user = db.get(AppUser, expected_user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
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
        factor = self._create_passkey_factor(db, user, registered, rp_id=str(flow["rp_id"]), label=label)
        self._delete_flow(flow_token)
        return factor

    def _create_passkey_factor(
        self,
        db: Session,
        user: AppUser,
        registered: RegisteredCredential,
        *,
        rp_id: str,
        label: str | None,
    ) -> UserMfaFactor:
        factor = UserMfaFactor(
            user_id=user.id,
            factor_type="webauthn",
            label=(label or self._default_passkey_label(user)).strip() or self._default_passkey_label(user),
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
        self._sync_preferred_factor_type(db, user, self._list_factors(db, user.id))
        return factor

    def prepare_login(
        self,
        db: Session,
        *,
        user: AppUser,
        current_user: CurrentUser,
        request_host: str | None,
    ) -> MfaPendingLoginRead | None:
        factors = self._list_factors(db, user.id)
        required = self.user_requires_mfa(db, user.id)
        if not factors and not required:
            return None

        ticket = self._create_flow(
            "login_ticket",
            {
                "user_id": user.id,
                "tenant_id": current_user.current_tenant_id,
                "request_host": request_host,
            },
        )
        if factors:
            default_factor_type = self._resolve_preferred_factor_type(user, factors)
            return self._build_pending_login(
                ticket=ticket,
                user=user,
                current_user=current_user,
                status_value="verification_required",
                required=required,
                factors=factors,
                default_factor_type=default_factor_type,
                can_add_passkey=self.can_add_passkey_here(request_host),
            )
        return self._build_pending_login(
            ticket=ticket,
            user=user,
            current_user=current_user,
            status_value="setup_required",
            required=True,
            factors=[],
            default_factor_type=None,
            can_add_passkey=self.can_add_passkey_here(request_host),
        )

    def _build_pending_login(
        self,
        *,
        ticket: str,
        user: AppUser,
        current_user: CurrentUser,
        status_value: str,
        required: bool,
        factors: list[UserMfaFactor],
        default_factor_type: str | None,
        can_add_passkey: bool,
    ) -> MfaPendingLoginRead:
        method_labels = self._method_labels_by_type(factors)
        methods = [
            MfaPendingLoginMethodRead(factor_type=factor_type, label=label)  # type: ignore[arg-type]
            for factor_type, label in method_labels.items()
        ]
        return MfaPendingLoginRead(
            status=status_value,  # type: ignore[arg-type]
            ticket=ticket,
            required=required,
            user_display_name=user.display_name,
            user_email=user.email,
            tenant_name=current_user.current_tenant_name,
            available_methods=methods,
            default_factor_type=default_factor_type,  # type: ignore[arg-type]
            default_factor_label=method_labels.get(default_factor_type) if default_factor_type else None,
            can_add_totp=True,
            can_add_passkey=can_add_passkey,
        )

    def _load_login_ticket(self, db: Session, ticket: str) -> PendingLoginContext:
        flow = self._load_flow(ticket, expected_kind="login_ticket")
        user = db.get(AppUser, int(flow["user_id"]))
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzerkonto ist nicht mehr aktiv")
        if (user.external_identity_json or {}).get("login_enabled") is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login ist für dieses Konto deaktiviert")
        current_user = build_current_user(db, user, flow.get("tenant_id"), mfa_verified=False)
        if current_user.current_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant membership assigned")
        return PendingLoginContext(user=user, current_user=current_user, request_host=flow.get("request_host"))

    def _consume_login_ticket(self, db: Session, ticket: str) -> PendingLoginContext:
        context = self._load_login_ticket(db, ticket)
        self._delete_flow(ticket)
        return context

    def verify_login_totp(self, db: Session, *, ticket: str, code: str) -> PendingLoginContext:
        context = self._load_login_ticket(db, ticket)
        enforce_rate_limit(f"mfa-login-totp:{ticket}", limit=10, period_seconds=_FLOW_TTL_SECONDS)
        factors = self._list_factors(db, context.user.id, factor_type="totp")
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Der TOTP-Code ist nicht gültig")

    def start_login_passkey_assertion(
        self,
        db: Session,
        *,
        ticket: str,
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyAssertionStartRead:
        context = self._load_login_ticket(db, ticket)
        rp_id = self.rp_id_for_request_host(request_host)
        factors = [
            factor
            for factor in self._list_factors(db, context.user.id, factor_type="webauthn")
            if factor.webauthn_rp_id == rp_id and factor.webauthn_credential_id
        ]
        if not factors:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Für dieses Konto ist kein Passkey auf dieser Domain hinterlegt")
        challenge = generate_challenge()
        flow_token = self._create_flow(
            "login_passkey_assertion",
            {
                "ticket": ticket,
                "user_id": context.user.id,
                "challenge": challenge,
                "rp_id": rp_id,
                "origin": request_origin,
            },
        )
        return PasskeyAssertionStartRead(
            flow_token=flow_token,
            public_key=build_assertion_options(
                challenge=challenge,
                rp_id=rp_id,
                allow_credentials=[
                    {
                        "id": factor.webauthn_credential_id,
                        "type": "public-key",
                        "transports": factor.webauthn_transports_json or [],
                    }
                    for factor in factors
                ],
            ),
        )

    def verify_login_passkey(
        self,
        db: Session,
        *,
        flow_token: str,
        credential: dict[str, Any],
    ) -> PendingLoginContext:
        flow = self._load_flow(flow_token, expected_kind="login_passkey_assertion")
        ticket = str(flow["ticket"])
        context = self._load_login_ticket(db, ticket)
        credential_id = credential.get("rawId") or credential.get("id")
        if not isinstance(credential_id, str) or not credential_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passkey-Antwort enthält keine Credential-ID")
        factor = db.scalar(
            select(UserMfaFactor).where(
                UserMfaFactor.user_id == context.user.id,
                UserMfaFactor.factor_type == "webauthn",
                UserMfaFactor.webauthn_credential_id == credential_id,
                UserMfaFactor.webauthn_rp_id == str(flow["rp_id"]),
            )
        )
        if factor is None or not factor.webauthn_public_key_pem:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unbekannte Passkey-Anmeldung")
        try:
            result = verify_assertion(
                credential,
                expected_challenge=str(flow["challenge"]),
                expected_origin=str(flow["origin"]),
                expected_rp_id=str(flow["rp_id"]),
                public_key_pem=factor.webauthn_public_key_pem,
                stored_sign_count=factor.webauthn_sign_count or 0,
                expected_credential_id=credential_id,
            )
        except WebauthnError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        factor.webauthn_sign_count = result.sign_count
        factor.last_used_at = datetime.now(UTC)
        db.add(factor)
        db.commit()
        self._delete_flow(flow_token)
        return self._consume_login_ticket(db, ticket)
