from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.user import SessionRead


MfaFactorType = Literal["totp", "webauthn"]


class MfaFactorRead(BaseModel):
    id: int
    factor_type: MfaFactorType
    label: str
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserMfaRead(BaseModel):
    required: bool
    has_factors: bool
    can_add_passkey_here: bool
    factors: list[MfaFactorRead] = Field(default_factory=list)


class TotpEnrollmentStartRead(BaseModel):
    flow_token: str
    secret: str
    manual_entry_key: str
    provisioning_uri: str
    issuer: str
    account_name: str


class TotpEnrollmentComplete(BaseModel):
    flow_token: str
    code: str
    label: str | None = None


class PasskeyRegistrationStartRead(BaseModel):
    flow_token: str
    public_key: dict[str, Any]


class PasskeyRegistrationComplete(BaseModel):
    flow_token: str
    label: str | None = None
    credential: dict[str, Any]


class TotpLoginVerifyRequest(BaseModel):
    ticket: str
    code: str


class MfaTicketRequest(BaseModel):
    ticket: str


class PasskeyAssertionStartRequest(BaseModel):
    ticket: str


class PasskeyAssertionStartRead(BaseModel):
    flow_token: str
    public_key: dict[str, Any]


class PasskeyAssertionVerifyRequest(BaseModel):
    flow_token: str
    credential: dict[str, Any]


class MfaPendingLoginMethodRead(BaseModel):
    factor_type: MfaFactorType
    label: str


class MfaPendingLoginRead(BaseModel):
    status: Literal["setup_required", "verification_required"]
    ticket: str
    required: bool
    user_display_name: str
    user_email: str
    tenant_name: str | None = None
    available_methods: list[MfaPendingLoginMethodRead] = Field(default_factory=list)
    can_add_totp: bool = True
    can_add_passkey: bool = True


class LoginResponse(SessionRead):
    mfa: MfaPendingLoginRead | None = None
