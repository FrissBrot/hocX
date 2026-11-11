"""Benachrichtigungen: Einstellungen der Person (app/notifications/)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NotificationCategory = Literal["todo_new", "todo_reminders", "exports"]


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
