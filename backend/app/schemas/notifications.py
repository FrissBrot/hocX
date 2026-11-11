"""Benachrichtigungen: Einstellungen der Person (app/notifications/)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NotificationCategory = Literal["todo_new", "todo_reminders"]


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
