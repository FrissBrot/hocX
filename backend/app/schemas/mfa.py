from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.base import PublicIdModel
from app.schemas.user import SessionRead


MfaFactorType = Literal["totp", "webauthn"]


class MfaFactorRead(PublicIdModel):
    id: uuid.UUID
    factor_type: MfaFactorType
    label: str
    created_at: datetime
    last_used_at: datetime | None = None


class UserMfaRead(BaseModel):
    required: bool
    has_factors: bool
    can_add_passkey_here: bool
    preferred_factor_type: MfaFactorType | None = None
    preferred_factor_label: str | None = None
    factors: list[MfaFactorRead] = Field(default_factory=list)


class TotpEnrollmentStartRead(BaseModel):
    flow_token: str
    secret: str
    manual_entry_key: str
    provisioning_uri: str
    issuer: str
    account_name: str


# Längen für Tickets, Vorgänge und Codes (SEC-AUTH-002): Tickets sind 43 Zeichen, Codes 6.
_TICKET = Field(min_length=1, max_length=128)
_CODE = Field(min_length=1, max_length=16)
_LABEL = Field(default=None, max_length=200)


class TotpEnrollmentComplete(BaseModel):
    flow_token: str = _TICKET
    code: str = _CODE
    label: str | None = _LABEL


class PasskeyRegistrationStartRead(BaseModel):
    flow_token: str
    public_key: dict[str, Any]


class PasskeyRegistrationComplete(BaseModel):
    flow_token: str = _TICKET
    label: str | None = _LABEL
    credential: dict[str, Any]


class TotpLoginVerifyRequest(BaseModel):
    ticket: str = _TICKET
    code: str = _CODE


class MfaTicketRequest(BaseModel):
    ticket: str = _TICKET


class EmailChallengeVerifyRequest(BaseModel):
    """Bestätigungscode per E-Mail bei erhöhtem Risiko (app/auth_security/email_challenge.py)."""
    ticket: str = _TICKET
    code: str = _CODE


class PreferredMfaMethodUpdate(BaseModel):
    factor_type: MfaFactorType


class PasskeyAssertionStartRequest(BaseModel):
    ticket: str = _TICKET


class PasskeyAssertionStartRead(BaseModel):
    flow_token: str
    public_key: dict[str, Any]


class PasskeyAssertionVerifyRequest(BaseModel):
    flow_token: str = _TICKET
    credential: dict[str, Any]


class MfaPendingLoginMethodRead(BaseModel):
    factor_type: MfaFactorType
    label: str


class MfaPendingLoginRead(BaseModel):
    # email_verification_required: erhöhtes Risiko, Konto ohne Faktor - Code per E-Mail
    status: Literal["setup_required", "verification_required", "email_verification_required"]
    ticket: str
    required: bool
    # Pflicht kommt aus der Mandanten-Einstellung «MFA für alle Logins» (tenant.require_mfa)
    required_by_tenant: bool = False
    user_display_name: str
    user_email: str
    tenant_name: str | None = None
    available_methods: list[MfaPendingLoginMethodRead] = Field(default_factory=list)
    default_factor_type: MfaFactorType | None = None
    default_factor_label: str | None = None
    can_add_totp: bool = True
    can_add_passkey: bool = True
    # «Später einrichten» (POST /auth/mfa/setup/skip): Erstlogin über Einladung ohne MFA-Pflicht
    # oder bestehendes Konto in der 3-Tage-Frist (Migration 0192)
    can_skip: bool = False
    # Ende der Frist, wenn sie der Grund für can_skip ist
    grace_until: datetime | None = None


class MfaSkipRequest(BaseModel):
    ticket: str = _TICKET


class LoginResponse(SessionRead):
    mfa: MfaPendingLoginRead | None = None


class TenantMfaPolicyRead(BaseModel):
    """MFA-Pflicht der Organisation (tenant.require_mfa) mit dem Stand der Logins."""
    require_mfa: bool
    # Aktive Logins der Organisation (aktiv, Login erlaubt, nicht ausgetreten)
    logins_total: int
    # Davon ohne eingerichteten MFA-Faktor
    logins_without_mfa: int


class TenantMfaPolicyUpdate(BaseModel):
    require_mfa: bool


class TenantProtocolPolicy(BaseModel):
    """Vier-Augen-Prinzip für Protokolle (tenant.four_eyes_protocols, Migration 0191)."""
    four_eyes_protocols: bool


class AdminStepUpStart(BaseModel):
    """Zweck und Zielaktion der Bestätigung (app/core/admin_step_up.py) - die Assertion gilt nur für
    genau diese Anfrage: Methode, Pfad und SHA-256 des Bodys (leerer Body = Hash von b"")."""

    purpose: Literal[
        "passkey-manage", "admin-manage", "tenant-delete", "tenant-export", "storage-destructive",
        "backup-restore", "backup-settings", "catalog-change", "user-mfa-reset", "user-manage", "platform-settings",
        "user-credentials", "tenant-import", "security-block", "security-export", "security-resolve",
    ]
    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(pattern=r"^/api/admin/[A-Za-z0-9/_.%-]+$", max_length=500)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
