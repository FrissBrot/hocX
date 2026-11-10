"""Aufbewahrungsfristen für Job-, Ereignis- und Verlaufstabellen (Datenschutz-Audit PRIV-011).

Läuft im Job ``log_cleanup`` (main.py) neben audit_log/system_error_log/system_job_run/
system_health_event, die ihre eigenen Aufräumfunktionen haben. Die Fristen stehen in
``settings`` (``*_retention_days``) und lassen sich je Installation anpassen.

Fachdaten der Vereine (Protokolle, Fotos, Abgaben) sind bewusst nicht hier: deren Fristen legt der
Verein fest (Mandanten-Einstellungen → Aufbewahrung).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass(frozen=True)
class RetentionRule:
    table: str
    # SQL-Ausdruck für den massgeblichen Zeitpunkt (fester Bezeichner aus dieser Datei)
    timestamp: str
    setting: str
    # Zusätzliche Bedingung: nur abgeschlossene Zeilen
    condition: str | None = None


RULES: tuple[RetentionRule, ...] = (
    RetentionRule("gallery_upload_job", "COALESCE(finished_at, created_at)", "upload_job_retention_days", "status NOT IN ('queued', 'running')"),
    RetentionRule("photo_analysis_job", "COALESCE(finished_at, created_at)", "upload_job_retention_days", "status NOT IN ('queued', 'running')"),
    # PDF-Aufträge (Migration 0150): request_json kann Freitext enthalten; die PDFs selbst stehen
    # in document_export/document_registry und bleiben.
    RetentionRule("document_render_job", "COALESCE(finished_at, created_at)", "upload_job_retention_days", "status NOT IN ('queued', 'running')"),
    RetentionRule("submission_upload_log", "created_at", "submission_upload_log_retention_days"),
    RetentionRule("backup_event", "created_at", "operations_event_retention_days"),
    RetentionRule("storage_migration_event", "created_at", "operations_event_retention_days"),
    RetentionRule("maintenance_event", "created_at", "operations_event_retention_days"),
    RetentionRule("overload_rejection", "created_at", "operations_event_retention_days"),
    RetentionRule("identity_verification_request", "decided_at", "identity_request_retention_days", "decided_at IS NOT NULL"),
    RetentionRule("word_import_suggestion_outcome", "created_at", "word_import_outcome_retention_days"),
    # Widerrufene oder abgelaufene Freigabelinks (inkl. share_link_file per Kaskade)
    RetentionRule(
        "share_link", "COALESCE(revoked_at, expires_at)", "inactive_share_link_retention_days",
        "revoked_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at < now())",
    ),
)


def cleanup(db: Session) -> dict[str, int]:
    """Löscht je Regel die Zeilen, deren Zeitpunkt älter als die Frist ist. Eine Frist von 0 oder
    weniger schaltet die Regel ab."""
    deleted: dict[str, int] = {}
    for rule in RULES:
        days = int(getattr(settings, rule.setting))
        if days <= 0:
            continue
        where = f"{rule.timestamp} < now() - make_interval(days => :days)"
        if rule.condition:
            where += f" AND ({rule.condition})"
        result = db.execute(text(f"DELETE FROM {rule.table} WHERE {where}"), {"days": days})  # sql-ok: Tabellen/Spalten nur aus RULES
        deleted[rule.table] = result.rowcount or 0
    db.commit()
    return deleted
