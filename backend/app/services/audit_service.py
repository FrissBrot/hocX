from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit_context import current_client_ip, ip_fingerprint
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
        outcome: str = "success",
        actor_user_id: int | None = None,
    ) -> None:
        """actor is a customer-side CurrentUser (has current_tenant_id/user_id/email).
        Platform-admin actions have no such user - pass actor_email instead (there's no
        matching app_user row, so actor_user_id stays NULL for those)."""
        effective_tenant_id = tenant_id or (actor.current_tenant_id if actor else None)
        effective_actor_email = actor.email if actor else actor_email
        db.execute(
            text("""
                INSERT INTO audit_log (tenant_id, actor_user_id, actor_email, action, entity_type, entity_id, details_json, ip_hash, outcome)
                VALUES (:tenant_id, :actor_user_id, :actor_email, :action, :entity_type, :entity_id, CAST(:details_json AS jsonb), :ip_hash, :outcome)
            """),
            {
                "tenant_id": effective_tenant_id,
                "actor_user_id": actor.user_id if actor else actor_user_id,
                "actor_email": effective_actor_email,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details_json": json.dumps(details or {}),
                # Gekürzte, gehashte Quelladresse des Requests (app/core/audit_context.py)
                "ip_hash": ip_fingerprint(current_client_ip()),
                "outcome": outcome,
            },
        )
        db.commit()

    def cleanup_old_entries(self, db: Session, *, retention_days: int) -> dict:
        """Periodic retention sweep (see main.py's log_cleanup_loop). Die Laufzeitrolle darf
        audit_log nicht selbst löschen (Migration 0143); die Frist erzwingt die
        SECURITY-DEFINER-Funktion audit_log_purge (mindestens 30 Tage). retention_days is the
        caller's call (settings.audit_log_retention_days) - the right retention period is a legal
        question, not an engineering one."""
        deleted = db.scalar(text("SELECT audit_log_purge(:retention_days)"), {"retention_days": retention_days})
        db.commit()
        return {"deleted": int(deleted or 0)}

    def forget_actors(self, db: Session, user_ids: list[int]) -> int:
        """E-Mail und IP-Hash gelöschter Personen entfernen (vor dem Löschen aufrufen, danach ist
        actor_user_id per FK NULL). Die Einträge selbst bleiben als Nachweis. Committet nicht."""
        if not user_ids:
            return 0
        return int(db.scalar(text("SELECT audit_log_forget_actors(CAST(:ids AS bigint[]))"), {"ids": list(user_ids)}) or 0)

    def forget_tenant(self, db: Session, tenant_id: int) -> int:
        """Wie forget_actors für alle Konten eines Mandanten (vor der Mandantenlöschung). Committet nicht."""
        return int(db.scalar(text("SELECT audit_log_forget_tenant(:tenant_id)"), {"tenant_id": tenant_id}) or 0)
