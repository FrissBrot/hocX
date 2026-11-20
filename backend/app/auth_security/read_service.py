"""Abfragen für die Sicherheits-Dashboards (zweiter Schritt, Audit Abschnitt 10.4).

Plattform (``/api/admin/auth-security/*``): Zeitreihe, auffällige Netze und Konten (nur gekürzte
Pseudonyme), aktive Sperren, letzte Ereignisse.

Mandant (``/api/auth-security/activity``, Recht ``access.manage``): nur eigene Konten,
datensparsam - letzte Anmeldung, Fehlversuche, aktive Sitzungen, Ereignisse ohne Netz-/Geräte-
Pseudonyme und ohne Risikowert (nur die Klasse). Immer mit ``tenant_id``-Filter UND RLS.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_security import blocks
from app.auth_security.risk import level_for

_EVENT_TYPES_FOR_TENANTS = (
    "login.password", "login.locked", "login.challenge", "login.mfa.totp", "login.mfa.passkey", "login.success",
    "mfa.enroll", "mfa.remove", "session.revoke", "session.logout", "reset.request", "reset.complete", "password.change",
    "stepup.success", "stepup.failure",
)


def _short(value: str | None) -> str | None:
    return value[:12] if value else None


# ── Plattform ──────────────────────────────────────────────────────────


def timeseries(db: Session, *, hours: int = 48, bucket_minutes: int = 5) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT to_timestamp(floor(extract(epoch FROM ts) / (:bucket * 60)) * (:bucket * 60)) AS bucket, "
            "count(*) FILTER (WHERE outcome = 'failure') AS failures, "
            "count(*) FILTER (WHERE event_type = 'login.success') AS successes, "
            "count(*) FILTER (WHERE outcome = 'blocked') AS blocked, "
            "count(*) FILTER (WHERE outcome = 'challenged') AS challenged "
            "FROM auth_event WHERE ts > now() - make_interval(hours => :hours) GROUP BY 1 ORDER BY 1"
        ),
        {"bucket": max(1, bucket_minutes), "hours": max(1, min(hours, 24 * 14))},
    ).mappings()
    return [dict(row) for row in rows]


def top_networks(db: Session, *, hours: int = 24, limit: int = 10) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT src_net_hash, count(*) FILTER (WHERE outcome = 'failure') AS failures, count(DISTINCT subject_hash) AS accounts, "
            "count(DISTINCT tenant_id) AS tenants, max(ts) AS last_seen FROM auth_event "
            "WHERE ts > now() - make_interval(hours => :hours) AND src_net_hash IS NOT NULL "
            "GROUP BY src_net_hash HAVING count(*) FILTER (WHERE outcome = 'failure') > 0 ORDER BY failures DESC LIMIT :limit"
        ),
        {"hours": hours, "limit": limit},
    ).mappings()
    return [{**dict(row), "src_net_hash": _short(row["src_net_hash"])} for row in rows]


def top_accounts(db: Session, *, hours: int = 24, limit: int = 10) -> list[dict]:
    """Betroffene Konten pseudonym (gekürzter Subjekt-Hash); das Konto selbst nur, wenn es existiert."""
    rows = db.execute(
        text(
            "SELECT subject_hash, max(actor_user_id) AS user_id, max(tenant_id) AS tenant_id, count(*) AS failures, "
            "count(DISTINCT src_net_hash) AS networks, max(ts) AS last_seen FROM auth_event "
            "WHERE ts > now() - make_interval(hours => :hours) AND outcome = 'failure' AND subject_hash IS NOT NULL "
            "GROUP BY subject_hash ORDER BY failures DESC LIMIT :limit"
        ),
        {"hours": hours, "limit": limit},
    ).mappings()
    return [{**dict(row), "subject_hash": _short(row["subject_hash"])} for row in rows]


def active_blocks() -> list[dict]:
    now = int(datetime.now(UTC).timestamp())
    return [{**asdict(block), "subject": block.subject, "remaining_seconds": max(0, block.until - now)} for block in blocks.active_blocks()]


def recent_events(db: Session, *, limit: int = 100, offset: int = 0, event_type: str | None = None, outcome: str | None = None) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT event_id, ts, event_type, outcome, actor_kind, actor_user_id, platform_admin_id, tenant_id, subject_hash, src_net_hash, "
            "device_hash, session_id, request_id, risk_score, risk_reasons, enforcement, policy_version, endpoint, host_kind, "
            "user_agent_family, details FROM auth_event "
            "WHERE (CAST(:event_type AS text) IS NULL OR event_type = :event_type) AND (CAST(:outcome AS text) IS NULL OR outcome = :outcome) "
            "ORDER BY ts DESC LIMIT :limit OFFSET :offset"
        ),
        {"event_type": event_type, "outcome": outcome, "limit": min(limit, 500), "offset": offset},
    ).mappings()
    return [
        {**dict(row), "subject_hash": _short(row["subject_hash"]), "src_net_hash": _short(row["src_net_hash"]), "device_hash": _short(row["device_hash"])}
        for row in rows
    ]


def platform_summary(db: Session) -> dict:
    return {
        "timeseries": timeseries(db),
        "top_networks": top_networks(db),
        "top_accounts": top_accounts(db),
        "active_blocks": active_blocks(),
    }


# ── Mandant ────────────────────────────────────────────────────────────


def tenant_accounts(db: Session, tenant_id: int) -> list[dict]:
    """Je Konto mit Login: letzte Anmeldung, Fehlversuche 7 Tage, aktive Sitzungen."""
    rows = db.execute(
        text(
            "SELECT u.public_id AS user_id, u.display_name, "
            "(SELECT max(e.ts) FROM auth_event e WHERE e.actor_user_id = u.id AND e.tenant_id = :tenant_id AND e.event_type = 'login.success') AS last_login, "
            "(SELECT count(*) FROM auth_event e WHERE e.actor_user_id = u.id AND e.tenant_id = :tenant_id AND e.outcome = 'failure' "
            " AND e.ts > now() - interval '7 days') AS failures_7d, "
            "(SELECT count(*) FROM auth_session s WHERE s.user_id = u.id AND s.tenant_id = :tenant_id AND s.revoked_at IS NULL "
            " AND s.expires_at > now()) AS active_sessions "
            "FROM app_user u WHERE u.tenant_id = :tenant_id AND u.login_enabled ORDER BY u.display_name"
        ),
        {"tenant_id": tenant_id},
    ).mappings()
    return [dict(row) for row in rows]


def tenant_events(db: Session, tenant_id: int, *, limit: int = 100) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT e.ts, e.event_type, e.outcome, u.public_id AS user_id, u.display_name, e.user_agent_family, e.risk_score, e.risk_reasons "
            "FROM auth_event e LEFT JOIN app_user u ON u.id = e.actor_user_id AND u.tenant_id = :tenant_id "
            "WHERE e.tenant_id = :tenant_id AND e.event_type = ANY(:types) ORDER BY e.ts DESC LIMIT :limit"
        ),
        {"tenant_id": tenant_id, "types": list(_EVENT_TYPES_FOR_TENANTS), "limit": min(limit, 500)},
    ).mappings()
    result = []
    for row in rows:
        item = dict(row)
        score = item.pop("risk_score")
        item["risk_level"] = level_for(score) if score is not None else None
        result.append(item)
    return result


def tenant_summary(db: Session, tenant_id: int) -> dict:
    row = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE outcome = 'failure' AND ts > now() - interval '24 hours') AS failures_24h, "
            "count(DISTINCT actor_user_id) FILTER (WHERE outcome = 'failure' AND ts > now() - interval '24 hours') AS accounts_with_failures_24h, "
            "count(*) FILTER (WHERE event_type = 'login.success' AND (details->>'new_device')::boolean AND ts > now() - interval '7 days') AS new_device_logins_7d, "
            "count(*) FILTER (WHERE outcome = 'blocked' AND ts > now() - interval '24 hours') AS blocked_24h "
            "FROM auth_event WHERE tenant_id = :tenant_id AND ts > now() - interval '7 days'"
        ),
        {"tenant_id": tenant_id},
    ).mappings().one()
    return dict(row)
