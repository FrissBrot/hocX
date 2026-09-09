from __future__ import annotations

import json

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
        actor_email: str | None = None,
        tenant_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        """actor is a customer-side CurrentUser (has current_tenant_id/user_id/email).
        Platform-admin actions have no such user - pass actor_email instead (there's no
        matching app_user row, so actor_user_id stays NULL for those)."""
        effective_tenant_id = tenant_id or (actor.current_tenant_id if actor else None)
        effective_actor_email = actor.email if actor else actor_email
        db.execute(
            text("""
                INSERT INTO audit_log (tenant_id, actor_user_id, actor_email, action, entity_type, entity_id, details_json)
                VALUES (:tenant_id, :actor_user_id, :actor_email, :action, :entity_type, :entity_id, CAST(:details_json AS jsonb))
            """),
            {
                "tenant_id": effective_tenant_id,
                "actor_user_id": actor.user_id if actor else None,
                "actor_email": effective_actor_email,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details_json": json.dumps(details or {}),
            },
        )
        db.commit()

    def cleanup_old_entries(self, db: Session, *, retention_days: int) -> dict:
        """Periodic retention sweep (see main.py's log_cleanup_loop) - audit_log had no
        cleanup at all before this (audit finding, 2026-08-26), so it grew unbounded
        forever. retention_days is intentionally the caller's call (settings.audit_log_
        retention_days), not hardcoded here - this is the compliance/security trail, so the
        right retention period is a legal question, not an engineering one."""
        result = db.execute(
            text("DELETE FROM audit_log WHERE created_at < NOW() - make_interval(days => :retention_days)"),
            {"retention_days": retention_days},
        )
        db.commit()
        return {"deleted": result.rowcount}
