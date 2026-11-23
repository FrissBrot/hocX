from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin
from app.core.config import settings
from app.auth_security import events
from app.auth_security.guard import consume_factor_attempt, refund_factor_attempt
from app.core.rate_limit import enforce_rate_limit
from app.core.redis_client import get_redis_sync
from app.core.webauthn import (
    SignCountError,
    WebauthnError,
    build_assertion_options,
    build_registration_options,
    generate_challenge,
    passkey_factor_fields,
    register_credential,
    verify_assertion,
)
from app.models import PlatformAdmin, UserMfaFactor
from app.schemas.mfa import (
    MfaFactorRead,
    MfaPendingLoginMethodRead,
    MfaPendingLoginRead,
    PasskeyAssertionStartRead,
    PasskeyRegistrationStartRead,
    UserMfaRead,
)
from app.services.audit_service import AuditService

"""MFA für Plattform-Admins: ausschliesslich Passkeys (WebAuthn), erzwungen.

Bis 1.4.x gab es für Admins TOTP und ein globales SSO (OIDC); beides ist entfernt (Migration
0205). Ablauf:

- Login: Passwort → Ticket (Redis, 10 min) → Passkey-Assertion → Session. Eine Session gibt es
  nie ohne erfolgreichen Passkey (`issue_admin_session_cookie`, Claim `amr=passkey`).
- Ohne Passkey (neues Konto, nach dem Update, nach `admin_cli reset-passkeys`): nach dem Passwort
  muss ein Passkey registriert werden (Trust on first use) - erst danach gibt es eine Session. Bis
  dahin erreicht das Konto keine andere Admin-API (es hat ja keine Session).
- Weitere Passkeys über die Kontoeinstellungen (mit Session); der letzte ist nicht entfernbar.
- Step-up (Backup-Wiederherstellung): frische Passkey-Bestätigung zusätzlich zur Session.

WebAuthn: RP-ID = Admin-Domain (`TRAEFIK_ADMIN_DOMAIN`), erwarteter Origin = `https://<Admin-Domain>`
(von der Route übergeben, nie aus dem Request übernommen, Security-Audit SEC-021). Nur lokal ohne
Admin-Domain gelten Host/Origin der Anfrage. userVerification = required. Jede Challenge ist
einmalig: der Vorgang wird vor der Prüfung atomar aus Redis genommen (GETDEL), eine zweite
Verwendung findet ihn nicht mehr.
"""


_audit = AuditService()
logger = logging.getLogger(__name__)

_PASSKEY_INVALID = {"code": "passkey_invalid", "message": "Der Passkey konnte nicht geprüft werden"}

_FLOW_PREFIX = "admin-mfa:flow:"
_FLOW_TTL_SECONDS = 10 * 60
_ISSUER = "hocX Admin"
_PASSKEY_LABEL = "Passkey"

# Konto-Sperre für fehlgeschlagene Passkey-Prüfungen (wie bisher für TOTP): ein neues Ticket gibt es
# nach jedem richtigen Passwort, deshalb zählt das Konto, nicht das Ticket.


def _flow_error(code: str = "mfa_flow_expired", message: str = "MFA-Vorgang ist abgelaufen") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": code, "message": message})


@dataclass
class AdminPendingLoginContext:
    admin: PlatformAdmin


class AdminMfaService:
    def _redis(self):
        return get_redis_sync()

    # ── Redis-Vorgänge ─────────────────────────────────────────────────────────────────────

    def _create_flow(self, kind: str, data: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        self._redis().set(f"{_FLOW_PREFIX}{token}", json.dumps({"kind": kind, **data}), nx=True, ex=_FLOW_TTL_SECONDS)
        return token

    @staticmethod
    def _decode_flow(raw: Any, expected_kind: str) -> dict[str, Any]:
        if raw is None:
            raise _flow_error()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise _flow_error("mfa_flow_invalid", "Ungültiger MFA-Vorgang") from exc
        if data.get("kind") != expected_kind:
            raise _flow_error("mfa_flow_invalid", "Ungültiger MFA-Vorgang")
        return data

    def _load_flow(self, token: str, *, expected_kind: str) -> dict[str, Any]:
        return self._decode_flow(self._redis().get(f"{_FLOW_PREFIX}{token}"), expected_kind)

    def _take_flow(self, token: str, *, expected_kind: str) -> dict[str, Any]:
        """Einmalig verbrauchen (GETDEL): eine Challenge lässt sich nie zweimal verwenden, auch nicht
        bei gleichzeitigen Anfragen."""
        return self._decode_flow(self._redis().getdel(f"{_FLOW_PREFIX}{token}"), expected_kind)

    # ── Faktoren ───────────────────────────────────────────────────────────────────────────

    def _list_passkeys(self, db: Session, admin_id: int, *, for_update: bool = False) -> list[UserMfaFactor]:
        statement = (
            select(UserMfaFactor)
            .where(UserMfaFactor.platform_admin_id == admin_id, UserMfaFactor.factor_type == "webauthn")
            .order_by(UserMfaFactor.created_at.asc(), UserMfaFactor.id.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        return list(db.scalars(statement))

    def _usable_passkeys(self, db: Session, admin_id: int, rp_id: str) -> list[UserMfaFactor]:
        return [
            factor
            for factor in self._list_passkeys(db, admin_id)
            if factor.webauthn_rp_id == rp_id and factor.webauthn_credential_id and factor.webauthn_public_key_pem
            and factor.locked_at is None
        ]

    def _factor_read(self, factor: UserMfaFactor) -> MfaFactorRead:
        return MfaFactorRead(
            id=factor.public_id,
            factor_type="webauthn",
            label=factor.label,
            created_at=factor.created_at,
            last_used_at=factor.last_used_at,
        )

    def get_self_overview(self, db: Session, actor: CurrentAdmin) -> UserMfaRead:
        factors = self._list_passkeys(db, actor.admin_id)
        return UserMfaRead(
            required=True,
            has_factors=bool(factors),
            can_add_passkey_here=True,
            preferred_factor_type="webauthn" if factors else None,
            preferred_factor_label=_PASSKEY_LABEL if factors else None,
            factors=[self._factor_read(factor) for factor in factors],
        )

    @staticmethod
    def rp_id(request_host: str | None) -> str:
        """RP-ID der Admin-Passkeys: die Admin-Domain. Nur lokal (ohne Admin-Domain) der Host der
        Anfrage - Entwicklung und E2E-Stack."""
        if settings.traefik_admin_domain:
            return settings.traefik_admin_domain.strip().lower().rstrip(".")
        from app.core.admin_gate import is_development

        if not is_development() or not request_host:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "passkey_host_invalid", "message": "Passkeys benötigen einen gültigen Hostnamen"})
        return request_host

    def _registration_options(self, db: Session, admin: PlatformAdmin, *, rp_id: str, challenge: str) -> dict[str, Any]:
        return build_registration_options(
            rp_id=rp_id,
            rp_name=_ISSUER,
            user_id=admin.id,
            user_name=admin.email,
            display_name=admin.display_name,
            challenge=challenge,
            exclude_credentials=[
                {"id": f.webauthn_credential_id, "type": "public-key", "transports": f.webauthn_transports_json or []}
                for f in self._usable_passkeys(db, admin.id, rp_id)
            ],
        )

    def _register(self, db: Session, admin: PlatformAdmin, flow: dict[str, Any], *, label: str | None, credential: dict[str, Any]) -> UserMfaFactor:
        try:
            registered = register_credential(
                credential,
                expected_challenge=str(flow["challenge"]),
                expected_origin=str(flow["origin"]),
                expected_rp_id=str(flow["rp_id"]),
            )
        except WebauthnError as exc:
            logger.info("Admin-Passkey-Registrierung abgelehnt: %s", exc)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_PASSKEY_INVALID) from exc
        if db.scalar(select(UserMfaFactor.id).where(UserMfaFactor.webauthn_credential_id == registered.credential_id)) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "passkey_already_registered", "message": "Diese Passkey-Anmeldung ist bereits hinterlegt"})
        default_label = f"Passkey für {admin.email}"
        factor = UserMfaFactor(
            platform_admin_id=admin.id,
            label=(label or default_label).strip()[:200] or default_label,
            **passkey_factor_fields(registered, rp_id=str(flow["rp_id"])),
        )
        db.add(factor)
        db.commit()
        db.refresh(factor)
        return factor

    def _assertion(
        self, db: Session, admin_id: int, flow: dict[str, Any], credential: dict[str, Any], *, event_type: str, purpose: str | None = None
    ) -> UserMfaFactor:
        """Prüft eine Passkey-Assertion gegen einen bereits verbrauchten Vorgang. Jeder Versuch wird
        VOR der Prüfung gezählt (Anmeldeschutz L6, eigener Admin-Zähler, danach 1/min Drip) und bei
        Erfolg zurückgegeben; Fehlschläge werden als Sicherheitsereignis (``event_type``: Login
        ``admin.login.mfa``, Bestätigung ``admin.stepup`` - Alarmregel admin_mfa) und im Audit
        (``admin.mfa_failed``) festgehalten."""
        counter = consume_factor_attempt(admin_id, kind="passkey", principal="admin")
        extra = {"purpose": purpose} if purpose else {}

        def failed(reason: str) -> None:
            events.record(event_type=event_type, outcome="failure", platform_admin_id=admin_id, details={"reason": reason, "factor": "passkey", **extra})
            admin = db.get(PlatformAdmin, admin_id)
            _audit.log(
                db, action="admin.mfa_failed", outcome="failure", actor_email=admin.email if admin is not None else None,
                entity_type="platform_admin", entity_id=admin_id,
                details={"reason": reason, "context": "step_up" if event_type == "admin.stepup" else "login", **extra},
            )

        credential_id = credential.get("rawId") or credential.get("id")
        factor = None
        if isinstance(credential_id, str) and credential_id:
            factor = db.scalar(
                select(UserMfaFactor)
                .where(
                    UserMfaFactor.platform_admin_id == admin_id,
                    UserMfaFactor.factor_type == "webauthn",
                    UserMfaFactor.webauthn_credential_id == credential_id,
                    UserMfaFactor.webauthn_rp_id == str(flow["rp_id"]),
                )
                .with_for_update()
            )
        if factor is None or not factor.webauthn_public_key_pem or factor.locked_at is not None:
            failed("passkey_locked" if factor is not None and factor.locked_at is not None else "passkey_unknown")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "passkey_unknown", "message": "Unbekannte Passkey-Anmeldung"})
        try:
            result = verify_assertion(
                credential,
                expected_challenge=str(flow["challenge"]),
                expected_origin=str(flow["origin"]),
                expected_rp_id=str(flow["rp_id"]),
                public_key_pem=factor.webauthn_public_key_pem,
                stored_sign_count=factor.webauthn_sign_count or 0,
                expected_credential_id=str(credential_id),
            )
        except SignCountError as exc:
            # Review L8: Zähler läuft zurück - möglicherweise ein geklonter Schlüssel. Passkey sperren
            # (gilt für Login und Step-up nicht mehr), Systemcheck admin_passkeys alarmiert, Eintrag im
            # Fehlerprotokoll. Aufheben: den gesperrten Passkey in den Kontoeinstellungen entfernen
            # (mit einem anderen Passkey bestätigt) oder Notausgang admin_cli reset-passkeys.
            factor.locked_at = datetime.now(UTC)
            db.add(factor)
            db.commit()
            failed("sign_count")
            logger.error("Admin-Passkey %s gesperrt: Zähler nicht gestiegen", factor.id)
            from app.core.error_log import record_system_error

            record_system_error(db, exc=RuntimeError(f"Admin-Passkey (Faktor {factor.id}) gesperrt: Zähler nicht gestiegen, möglicher Klon"))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_PASSKEY_INVALID) from exc
        except WebauthnError as exc:
            failed("passkey_invalid")
            logger.info("Admin-Passkey-Prüfung abgelehnt: %s", exc)
            # Generische Meldung (Review, Info): Details nur im Log
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_PASSKEY_INVALID) from exc
        factor.webauthn_sign_count = result.sign_count
        factor.last_used_at = datetime.now(UTC)
        db.add(factor)
        db.commit()
        refund_factor_attempt(counter)
        events.record(event_type=event_type, outcome="success", platform_admin_id=admin_id, details={"factor": "passkey", **extra})
        return factor

    # ── Selbstverwaltung (mit Session) ─────────────────────────────────────────────────────

    def start_self_passkey_registration(
        self, db: Session, actor: CurrentAdmin, *, request_host: str | None, request_origin: str
    ) -> PasskeyRegistrationStartRead:
        admin = db.get(PlatformAdmin, actor.admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
        # Jeder Start legt einen Redis-Vorgang an (noeviction) - je Konto begrenzt wie bei Mitgliedern
        enforce_rate_limit(f"admin-mfa-self-flow-start:{admin.id}", limit=60, period_seconds=15 * 60)
        rp_id = self.rp_id(request_host)
        challenge = generate_challenge()
        flow_token = self._create_flow(
            "admin_self_passkey_registration",
            {"admin_id": admin.id, "challenge": challenge, "rp_id": rp_id, "origin": request_origin},
        )
        return PasskeyRegistrationStartRead(
            flow_token=flow_token, public_key=self._registration_options(db, admin, rp_id=rp_id, challenge=challenge)
        )

    def complete_self_passkey_registration(
        self, db: Session, actor: CurrentAdmin, *, flow_token: str, label: str | None, credential: dict[str, Any]
    ) -> UserMfaFactor:
        flow = self._take_flow(flow_token, expected_kind="admin_self_passkey_registration")
        if int(flow["admin_id"]) != actor.admin_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "mfa_flow_invalid", "message": "Dieser MFA-Vorgang gehört zu einem anderen Konto"})
        admin = db.get(PlatformAdmin, actor.admin_id)
        if admin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
        return self._register(db, admin, flow, label=label, credential=credential)

    def delete_self_factor(self, db: Session, actor: CurrentAdmin, factor_id: int) -> UserMfaRead:
        # FOR UPDATE über alle Passkeys des Kontos: zwei gleichzeitige Löschungen können nicht beide
        # «es bleibt noch einer» sehen.
        passkeys = self._list_passkeys(db, actor.admin_id, for_update=True)
        factor = next((f for f in passkeys if f.id == factor_id), None)
        if factor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MFA-Faktor nicht gefunden")
        if len(passkeys) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "last_passkey", "message": "Der letzte Passkey kann nicht entfernt werden - zuerst einen weiteren hinzufügen"},
            )
        db.delete(factor)
        db.commit()
        return self.get_self_overview(db, actor)

    # ── Login (Ticket nach dem Passwort) ───────────────────────────────────────────────────

    def prepare_login(self, db: Session, admin: PlatformAdmin) -> MfaPendingLoginRead:
        """Nie eine Session: mit Passkey → Bestätigung, ohne → Pflicht-Einrichtung (TOFU)."""
        has_passkey = bool(self._list_passkeys(db, admin.id))
        ticket = self._create_flow("admin_login_ticket", {"admin_id": admin.id, "issued_at_ms": int(time.time() * 1000)})
        return MfaPendingLoginRead(
            status="verification_required" if has_passkey else "setup_required",
            ticket=ticket,
            required=True,
            user_display_name=admin.display_name,
            user_email=admin.email,
            tenant_name=None,
            available_methods=[MfaPendingLoginMethodRead(factor_type="webauthn", label=_PASSKEY_LABEL)] if has_passkey else [],
            default_factor_type="webauthn" if has_passkey else None,
            default_factor_label=_PASSKEY_LABEL if has_passkey else None,
            can_add_totp=False,
            # Im Login nur bei Ersteinrichtung einen Passkey anbieten (MAIN-SEC-001)
            can_add_passkey=not has_passkey,
        )

    def _load_login_ticket(self, db: Session, ticket: str) -> AdminPendingLoginContext:
        flow = self._load_flow(ticket, expected_kind="admin_login_ticket")
        admin = db.get(PlatformAdmin, int(flow["admin_id"]))
        if admin is None or not admin.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "account_inactive", "message": "Admin-Konto ist nicht mehr aktiv"})
        # Wer nach Ausstellung des Tickets alle Sessions beendet hat (Deaktivierung, Passkey-Reset
        # über admin_cli), beendet auch das Ticket (SECURITY-RULES 3.3).
        issued_at_ms = int(flow.get("issued_at_ms") or 0)
        if admin.session_revoke_at is not None and int(admin.session_revoke_at.timestamp() * 1000) >= issued_at_ms:
            raise _flow_error()
        return AdminPendingLoginContext(admin=admin)

    def _consume_login_ticket(self, db: Session, ticket: str) -> AdminPendingLoginContext:
        context = self._load_login_ticket(db, ticket)
        if self._redis().getdel(f"{_FLOW_PREFIX}{ticket}") is None:
            raise _flow_error()
        return context

    def start_login_passkey_assertion(
        self, db: Session, *, ticket: str, request_host: str | None, request_origin: str
    ) -> PasskeyAssertionStartRead:
        context = self._load_login_ticket(db, ticket)
        enforce_rate_limit(f"admin-mfa-login-start:{ticket}", limit=10, period_seconds=_FLOW_TTL_SECONDS)
        rp_id = self.rp_id(request_host)
        factors = self._usable_passkeys(db, context.admin.id, rp_id)
        if not factors:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "passkey_not_registered", "message": "Für dieses Konto ist kein Passkey hinterlegt"})
        challenge = generate_challenge()
        flow_token = self._create_flow(
            "admin_login_passkey_assertion",
            {"ticket": ticket, "admin_id": context.admin.id, "challenge": challenge, "rp_id": rp_id, "origin": request_origin},
        )
        return PasskeyAssertionStartRead(
            flow_token=flow_token,
            public_key=build_assertion_options(
                challenge=challenge,
                rp_id=rp_id,
                allow_credentials=[
                    {"id": f.webauthn_credential_id, "type": "public-key", "transports": f.webauthn_transports_json or []}
                    for f in factors
                ],
            ),
        )

    def verify_login_passkey(self, db: Session, *, flow_token: str, credential: dict[str, Any]) -> AdminPendingLoginContext:
        flow = self._take_flow(flow_token, expected_kind="admin_login_passkey_assertion")
        ticket = str(flow["ticket"])
        context = self._load_login_ticket(db, ticket)
        if context.admin.id != int(flow["admin_id"]):
            raise _flow_error("mfa_flow_invalid", "Ungültiger MFA-Vorgang")
        self._assertion(db, context.admin.id, flow, credential, event_type="admin.login.mfa")
        return self._consume_login_ticket(db, ticket)

    def start_login_passkey_setup(
        self, db: Session, *, ticket: str, request_host: str | None, request_origin: str
    ) -> PasskeyRegistrationStartRead:
        context = self._load_login_ticket(db, ticket)
        self._ensure_login_setup_allowed(db, context.admin.id)
        enforce_rate_limit(f"admin-mfa-setup-start:{ticket}", limit=10, period_seconds=_FLOW_TTL_SECONDS)
        rp_id = self.rp_id(request_host)
        challenge = generate_challenge()
        flow_token = self._create_flow(
            "admin_login_passkey_setup",
            {"ticket": ticket, "admin_id": context.admin.id, "challenge": challenge, "rp_id": rp_id, "origin": request_origin},
        )
        return PasskeyRegistrationStartRead(
            flow_token=flow_token, public_key=self._registration_options(db, context.admin, rp_id=rp_id, challenge=challenge)
        )

    def complete_login_passkey_setup(
        self, db: Session, *, flow_token: str, label: str | None, credential: dict[str, Any]
    ) -> AdminPendingLoginContext:
        flow = self._take_flow(flow_token, expected_kind="admin_login_passkey_setup")
        ticket = str(flow["ticket"])
        context = self._load_login_ticket(db, ticket)
        if context.admin.id != int(flow["admin_id"]):
            raise _flow_error("mfa_flow_invalid", "Ungültiger MFA-Vorgang")
        # Zeilensperre auf dem Konto: zwei gleichzeitige Ersteinrichtungen ergeben nicht zwei
        # «erste» Passkeys ohne Bestätigung.
        db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.id == context.admin.id).with_for_update())
        self._ensure_login_setup_allowed(db, context.admin.id)
        self._register(db, context.admin, flow, label=label, credential=credential)
        return self._consume_login_ticket(db, ticket)

    def _ensure_login_setup_allowed(self, db: Session, admin_id: int) -> None:
        """Einrichtung im Login nur ohne bestehenden Passkey (Audit MAIN-SEC-001) - sonst genügte
        das Passwort, um einen eigenen Passkey hinzuzufügen und eine Session zu erhalten."""
        if self._list_passkeys(db, admin_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "mfa_already_configured", "message": "Für dieses Konto ist bereits ein Passkey eingerichtet. Bitte mit diesem anmelden."},
            )

    # ── Step-up (frische Bestätigung für kritische Aktionen) ───────────────────────────────

    def start_step_up(
        self, db: Session, *, admin_id: int, purpose: str, binding: str, request_host: str | None, request_origin: str
    ) -> PasskeyAssertionStartRead:
        """binding = «METHODE PFAD SHA256(Body)» der Aktion, die bestätigt werden soll (Review L7)."""
        enforce_rate_limit(f"admin-mfa-step-up-start:{admin_id}", limit=30, period_seconds=_FLOW_TTL_SECONDS)
        rp_id = self.rp_id(request_host)
        factors = self._usable_passkeys(db, admin_id, rp_id)
        if not factors:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "passkey_not_registered", "message": "Für diese Aktion ist ein Passkey erforderlich"})
        challenge = generate_challenge()
        flow_token = self._create_flow(
            "admin_step_up",
            {"admin_id": admin_id, "purpose": purpose, "binding": binding, "challenge": challenge, "rp_id": rp_id, "origin": request_origin},
        )
        return PasskeyAssertionStartRead(
            flow_token=flow_token,
            public_key=build_assertion_options(
                challenge=challenge,
                rp_id=rp_id,
                allow_credentials=[
                    {"id": f.webauthn_credential_id, "type": "public-key", "transports": f.webauthn_transports_json or []}
                    for f in factors
                ],
            ),
        )

    def verify_step_up(
        self, db: Session, *, admin_id: int, purpose: str, flow_token: str, credential: dict[str, Any], binding: str
    ) -> None:
        flow = self._take_flow(flow_token, expected_kind="admin_step_up")
        if (
            int(flow["admin_id"]) != admin_id
            or flow.get("purpose") != purpose
            or not hmac.compare_digest(str(flow.get("binding", "")).encode("utf-8"), binding.encode("utf-8"))
        ):
            raise _flow_error("step_up_mismatch", "Die Bestätigung gehört zu einer anderen Aktion")
        self._assertion(db, admin_id, flow, credential, event_type="admin.stepup", purpose=purpose)

    # ── Notausgang (admin_cli) ─────────────────────────────────────────────────────────────

    def reset_passkeys(self, db: Session, admin: PlatformAdmin, *, commit: bool = True) -> int:
        """Löscht alle Passkeys eines Admins und beendet seine Sessions und offenen Login-Tickets
        (session_revoke_at). Beim nächsten Login richtet er einen neuen Passkey ein. commit=False:
        der Aufrufer schreibt den Audit-Eintrag in derselben Transaktion (admin_cli)."""
        # Alle Faktoren des Kontos (nach 0205 nur noch Passkeys)
        factors = list(db.scalars(select(UserMfaFactor).where(UserMfaFactor.platform_admin_id == admin.id).with_for_update()))
        for factor in factors:
            db.delete(factor)
        removed = len(factors)
        admin.session_revoke_at = datetime.now(UTC)
        db.add(admin)
        if commit:
            db.commit()
        return removed


def clear_admin_lockouts(admin: PlatformAdmin) -> int:
    """Sperrzähler eines Admin-Kontos löschen - für den Notausgang (admin_cli), damit ein
    zurückgesetztes Konto sich sofort wieder anmelden kann: Passwortphase (LoginGuard, Scope
    login-admin), Passkey-Versuche (L6, Admin-Zähler) und der Drip danach. Die Zähler je Konto und
    Quelle (login-admin-ip) sind über Konto+Adresse gehasht und nicht einzeln auffindbar: es werden
    die Quell-Zähler aller Admin-Konten gelöscht (nur der Admin-Login, nie Mandanten)."""
    from app.core.auth_pseudonym import counter_subject, subject_hash
    from app.core.rate_limit import PREFIX, redis_key
    from app.core.redis_client import get_ratelimit_redis_sync

    counters = get_ratelimit_redis_sync()
    # Gleitende Zähler liegen je Zeitfenster unter «<Schlüssel>:<Fenster>» (rate_limit._SLIDING_LUA)
    keys: list = []
    for base in (redis_key("login-admin", subject_hash(admin.email)), redis_key("admin-passkey-account", str(admin.id))):
        keys += list(counters.scan_iter(match=f"{base}*", count=500))
    keys += list(counters.scan_iter(match=f"{PREFIX}login-admin-ip:*", count=500))
    deleted = int(counters.delete(*keys) or 0) if keys else 0
    deleted += int(get_redis_sync().delete(f"authsec:drip:admin:passkey:{counter_subject('drip', str(admin.id))}") or 0)
    return deleted
