from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import CurrentUser


class AuditService:
    def log(
        self,
        db: Session,
        *,
        action: str,
        actor: CurrentUser | None = None,
        tenant_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        effective_tenant_id = tenant_id or (actor.current_tenant_id if actor else None)
        db.execute(
            text("""
                INSERT INTO audit_log (tenant_id, actor_user_id, actor_email, action, entity_type, entity_id, details_json)
                VALUES (:tenant_id, :actor_user_id, :actor_email, :action, :entity_type, :entity_id, CAST(:details_json AS jsonb))
            """),
            {
                "tenant_id": effective_tenant_id,
                "actor_user_id": actor.user_id if actor else None,
                "actor_email": actor.email if actor else None,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details_json": __import__("json").dumps(details or {}),
            },
        )
        db.commit()
