"""Benachrichtigungen: Einstellungen der Person (app/notifications/)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.mfa import MfaPendingLoginRead

NotificationCategory = Literal["todo_new", "todo_reminders", "todo_submissions", "fines", "submission_changes", "exports", "security_logins", "imports"]


class NotificationPreferenceRead(BaseModel):
    category: NotificationCategory
    enabled: bool


class NotificationPreferencesRead(BaseModel):
    preferences: list[NotificationPreferenceRead]
    # Ohne E-Mail-Adresse kommt nichts an - die Oberfläche weist darauf hin.
    has_email: bool
    email_enabled: bool


class NotificationPreferencesWrite(BaseModel):
    preferences: list[NotificationPreferenceRead] = Field(max_length=20)


# ── Konto (Phase 3): «Passwort vergessen» und Einladung ──────────────────


class PasswordResetAvailableRead(BaseModel):
    # Nur ob der Versand eingerichtet ist (Login-Seite blendet «Passwort vergessen» sonst aus).
    enabled: bool
    # Versand eingerichtet, aber gestört (notifications/delivery_status.py): Hinweis auf
    # «Passwort vergessen» und bei Einladungen. Plattformweiter Zustand, sagt nichts über Konten.
    disturbed: bool = False


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)


class AccountLinkToken(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class AccountLinkComplete(AccountLinkToken):
    password: str = Field(min_length=12, max_length=1024)


class AccountLinkPreviewRead(BaseModel):
    purpose: Literal["password_reset", "invite"]
    display_name: str
    email: str
    tenant_name: str


class AccountLinkCompleteRead(BaseModel):
    purpose: Literal["password_reset", "invite"]
    # Erstlogin über Einladung: Login-Ticket für den zweiten Faktor (None, wenn das Konto schon
    # einen Faktor hat - dann normaler Login) und ob MFA Pflicht ist (account_requires_mfa).
    mfa: MfaPendingLoginRead | None = None
    mfa_required: bool | None = None
