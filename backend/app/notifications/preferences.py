"""Einstellungen der Person: Kategorie ein/aus (Standard aus catalog.CATEGORIES)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import NotificationPreference, Participant, PlatformNotificationSettings
from app.notifications.catalog import CATEGORIES
from app.schemas.notifications import NotificationPreferenceRead, NotificationPreferencesRead, NotificationPreferencesWrite


def read(db: Session, user_id: int, tenant_id: int) -> NotificationPreferencesRead:
    stored = dict(db.execute(
        select(NotificationPreference.category, NotificationPreference.enabled)
        .where(NotificationPreference.user_id == user_id, NotificationPreference.tenant_id == tenant_id)
    ).all())
    person = db.get(Participant, user_id)
    platform = db.get(PlatformNotificationSettings, 1)
    return NotificationPreferencesRead(
        preferences=[
            NotificationPreferenceRead(category=key, enabled=bool(stored.get(key, category.default)))  # type: ignore[arg-type]
            for key, category in CATEGORIES.items()
        ],
        has_email=bool(person and (person.email or "").strip()),
        email_enabled=bool(platform and platform.email_enabled),
    )


def write(db: Session, user_id: int, tenant_id: int, payload: NotificationPreferencesWrite) -> NotificationPreferencesRead:
    now = datetime.now(timezone.utc)
    for preference in payload.preferences:
        statement = insert(NotificationPreference).values(
            tenant_id=tenant_id, user_id=user_id, category=preference.category, enabled=preference.enabled, updated_at=now,
        ).on_conflict_do_update(
            index_elements=[NotificationPreference.user_id, NotificationPreference.category],
            set_={"enabled": preference.enabled, "updated_at": now},
        )
        db.execute(statement)
    db.commit()
    return read(db, user_id, tenant_id)
