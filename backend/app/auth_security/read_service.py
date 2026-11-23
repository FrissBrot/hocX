"""Abfragen für die Sicherheits-Dashboards (zweiter Schritt, Audit Abschnitt 10.4).

Plattform (``/api/admin/auth-security/*``): Zeitreihe, auffällige Netze und Konten (nur gekürzte
Pseudonyme), aktive Sperren, letzte Ereignisse.

Mandant (``/api/auth-security/activity``, Recht ``security.read``): nur eigene Konten,
datensparsam - letzte Anmeldung, Fehlversuche, aktive Sitzungen, Ereignisse ohne Netz-/Geräte-
Pseudonyme und ohne Risikowert (nur die Klasse). Immer mit ``tenant_id``-Filter UND RLS.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

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


def active_blocks(db: Session | None = None) -> list[dict]:
    """Aktive Sperren mit Restzeit, Abgewiesen-Zähler und (mit ``db``) Namen des setzenden Admins.
    ``subject`` bleibt vollständig (Schlüssel für Aufheben/Verlängern), ``short`` ist die Anzeige."""
    now = int(datetime.now(UTC).timestamp())
    active = blocks.active_blocks()
    hits = blocks.rejections([block.subject for block in active])
    names: dict[int, str] = {}
    admin_ids = sorted({block.admin_id for block in active if block.admin_id})
    if db is not None and admin_ids:
        names = dict(db.execute(text("SELECT id, display_name FROM platform_admin WHERE id = ANY(:ids)"), {"ids": admin_ids}).all())
    return [
        {
            **asdict(block), "short": block.short, "remaining_seconds": max(0, block.until - now), "rejected": hits.get(block.subject, 0),
            "admin_name": names.get(block.admin_id) if block.admin_id else None,
        }
        for block in active
    ]


# Abwehrleiter der Sperren-Seite: Stufen 1-3 gibt es nur als gleitende Redis-Zähler je Quelle (ohne
# Übersicht), darum Ereignisse der letzten 24 h; Stufen 4/5 sind die aktiven Sperren (jetzt).
_LIMIT_LAYERS = ("attempt_rate", "account_source", "source", "account")
_CACHE_SECONDS = 30
_ladder_cache: tuple[float, dict] | None = None


def defense_ladder(db: Session) -> dict:
    global _ladder_cache
    import time

    now = time.monotonic()
    if _ladder_cache is not None and now - _ladder_cache[0] < _CACHE_SECONDS:
        counts = dict(_ladder_cache[1])
    else:
        row = db.execute(
            text(
                "SELECT count(*) FILTER (WHERE outcome = 'failure') AS observed, "
                "count(*) FILTER (WHERE event_type = 'login.locked' AND details->>'layer' = ANY(:layers)) AS limited, "
                "count(*) FILTER (WHERE outcome = 'challenged') AS challenged "
                "FROM auth_event WHERE ts > now() - interval '24 hours'"
            ),
            {"layers": list(_LIMIT_LAYERS)},
        ).mappings().one()
        counts = {key: int(value or 0) for key, value in row.items()}
        _ladder_cache = (now, counts)
    active = blocks.active_blocks()
    from app.core.config import settings

    return {
        "events_24h": counts,
        "automatic": sum(1 for block in active if not block.manual),
        "manual": sum(1 for block in active if block.manual),
        # Regeln für die Zeile unter der Leiter (wirksame Einstellungen, keine Geheimnisse)
        "strikes": settings.auth_block_strikes,
        "durations": blocks.automatic_durations(),
        "max_automatic_minutes": blocks.MAX_AUTOMATIC_MINUTES,
        "max_manual_minutes": blocks.MAX_MANUAL_MINUTES,
    }


BLOCK_HISTORY_DAYS = 7
_HISTORY_ROWS = 5000
_HISTORY_SUBJECTS = 60


def block_history(db: Session, *, days: int = BLOCK_HISTORY_DAYS) -> dict:
    """Sperren der letzten Tage aus ``block.set``/``block.clear`` (je Quelle Balken von Setzen bis
    Ablauf bzw. Aufheben). Ältere Ereignisse ohne ``details.subject`` (vor 1.6) fehlen."""
    start = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        text(
            "SELECT ts, event_type, src_country, details FROM auth_event "
            "WHERE event_type IN ('block.set', 'block.clear') AND ts > :start AND details ? 'subject' ORDER BY ts, id LIMIT :limit"
        ),
        {"start": start, "limit": _HISTORY_ROWS},
    ).mappings()
    sources: dict[str, dict] = {}
    for row in rows:
        details = row["details"] or {}
        subject = str(details.get("subject") or "")[:12]
        if not subject:
            continue
        source = sources.setdefault(subject, {"subject": subject, "scope": details.get("scope"), "country": None, "bars": [], "last": row["ts"]})
        source["last"] = row["ts"]
        source["country"] = source["country"] or row["src_country"]
        open_bar = source["bars"][-1] if source["bars"] and source["bars"][-1]["open"] else None
        if row["event_type"] == "block.set":
            if open_bar is not None:
                # Verlängert bzw. ersetzt: der alte Balken endet hier
                open_bar.update(end=row["ts"], open=False, replaced=True)
            minutes = int(details.get("minutes") or 0)
            source["bars"].append({
                "start": row["ts"], "end": row["ts"] + timedelta(minutes=minutes), "minutes": minutes,
                "manual": details.get("kind") == "manual" or details.get("stage") == 5, "stage": details.get("stage"),
                "reason": details.get("reason"), "cleared": False, "replaced": False, "open": True,
            })
            source["scope"] = details.get("scope") or source["scope"]
        elif open_bar is not None:
            open_bar.update(end=min(open_bar["end"], row["ts"]), open=False, cleared=True)
    result = sorted(sources.values(), key=lambda item: item["last"], reverse=True)[:_HISTORY_SUBJECTS]
    for item in result:
        for bar in item["bars"]:
            bar.pop("open", None)
        item.pop("last", None)
    return {"start": start, "end": datetime.now(UTC), "sources": result}


def platform_summary(db: Session) -> dict:
    return {
        "timeseries": timeseries(db),
        "top_networks": top_networks(db),
        "top_accounts": top_accounts(db),
        "active_blocks": active_blocks(db),
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


# Warnungen der eigenen Organisation (Seite «Sicherheit & Anmeldungen», Recht security.read).
# Je Warnung nur Konto (öffentliche ID, Anzeigename), Anzahl und Zeitpunkt - keine Adressen, keine
# Netz-/Geräte-Pseudonyme, kein Risikowert.
TENANT_ACCOUNT_ATTACK_FAILURES = 10


def tenant_warnings(db: Session, tenant_id: int) -> list[dict]:
    rows = db.execute(
        text(
            # Gesperrte Versuche tragen nur den Subjekt-Hash: das Konto über frühere Ereignisse desselben
            # Subjekts im selben Mandanten auflösen (kein Hash verlässt die Abfrage).
            "WITH ev0 AS (SELECT e.actor_user_id, e.subject_hash, e.event_type, e.outcome, e.ts, e.details FROM auth_event e "
            " WHERE e.tenant_id = :tenant_id AND e.ts > now() - interval '7 days'), "
            "ev AS (SELECT coalesce(ev0.actor_user_id, (SELECT max(x.actor_user_id) FROM auth_event x WHERE x.tenant_id = :tenant_id "
            " AND x.subject_hash = ev0.subject_hash AND x.actor_user_id IS NOT NULL)) AS actor_user_id, ev0.event_type, ev0.outcome, ev0.ts, ev0.details "
            " FROM ev0 WHERE ev0.actor_user_id IS NOT NULL OR ev0.event_type = 'login.locked'), "
            # Privilegiert = Standardrolle admin (alle Rechte) oder eigene Rolle mit access.manage/settings.manage
            # (wie role_service.count_capable_admins; Security-Review N2)
            "admins AS (SELECT ur.user_id FROM user_role ur JOIN tenant_role r ON r.id = ur.role_id "
            " WHERE r.tenant_id = :tenant_id AND (r.system_key = 'admin' OR EXISTS (SELECT 1 FROM tenant_role_permission p "  # rbac-ok: Standardrolle admin hat all_permissions ohne Einzelzeilen
            " WHERE p.role_id = r.id AND p.permission_key IN ('access.manage', 'settings.manage')))), "
            "w AS ("
            " SELECT 'account_attack' AS kind, actor_user_id, count(*) AS count, max(ts) AS last_at FROM ev "
            "  WHERE outcome = 'failure' AND ts > now() - interval '24 hours' GROUP BY actor_user_id HAVING count(*) >= :attack "
            " UNION ALL "
            " SELECT 'privileged_new_device', actor_user_id, count(*), max(ts) FROM ev "
            "  WHERE event_type = 'login.success' AND (details->>'new_device')::boolean AND actor_user_id IN (SELECT user_id FROM admins) "
            "  GROUP BY actor_user_id "
            " UNION ALL "
            " SELECT 'mfa_removed', actor_user_id, count(*), max(ts) FROM ev WHERE event_type = 'mfa.remove' AND outcome = 'success' GROUP BY actor_user_id "
            " UNION ALL "
            " SELECT 'account_locked', actor_user_id, count(*), max(ts) FROM ev WHERE event_type = 'login.locked' GROUP BY actor_user_id"
            ") "
            "SELECT w.kind, u.public_id AS user_id, u.display_name, w.count, w.last_at FROM w "
            "JOIN app_user u ON u.id = w.actor_user_id AND u.tenant_id = :tenant_id ORDER BY w.last_at DESC LIMIT 100"
        ),
        {"tenant_id": tenant_id, "attack": TENANT_ACCOUNT_ATTACK_FAILURES},
    ).mappings()
    return [dict(row) for row in rows]


# ── Plattform: Warnungen (Alarmregeln live) ─────────────────────────────


_ALERTS_CACHE_SECONDS = 30
_alerts_cache: tuple[float, list[dict]] | None = None
# Messwerte aller Regeln aus demselben detect()-Lauf (1.6, Seite «Alarmregeln»)
_measured_cache: dict | None = None


def _detect(db: Session) -> tuple[list[dict], dict]:
    global _alerts_cache, _measured_cache
    import time

    from app.auth_security import threats

    now = time.monotonic()
    if _alerts_cache is not None and _measured_cache is not None and now - _alerts_cache[0] < _ALERTS_CACHE_SECONDS:
        return [dict(item) for item in _alerts_cache[1]], dict(_measured_cache)
    measured: dict = {}
    alerts = [
        {
            "key": threat.key, "rule": threat.rule, "subject": threat.subject, "severity": threat.severity, "title": threat.title,
            "message": threat.message, "last_at": threat.last_at, "window_minutes": threat.window_minutes,
            # Ohne neues Ereignis klingt die Warnung von selbst ab (Fenster aus threats.RULE_WINDOW_MINUTES)
            "clears_at": threat.last_at + timedelta(minutes=threat.window_minutes) if threat.last_at else None,
        }
        for threat in threats.detect(db, measured)
    ]
    _alerts_cache = (now, alerts)
    _measured_cache = measured
    return [dict(item) for item in alerts], dict(measured)


def platform_alerts(db: Session) -> list[dict]:
    """Aktuell ausgelöste Alarmregeln (``threats.detect``), dieselben Schlüssel wie im Systemmonitor.
    30 s im Prozess zwischengespeichert: Übersicht und Warnungsseite fragen kurz nacheinander, die
    Erkennung läuft über mehrere Abfragen auf auth_event (Security-Review N4)."""
    return _detect(db)[0]


# ── Plattform: Alarmregeln (1.6) ───────────────────────────────────────

NEAR_RATIO = 0.6
TRIGGER_DAYS = 30
_RECENT_PER_RULE = 3
_series_cache: dict[str, tuple[float, dict]] = {}
_SERIES_CACHE_SECONDS = 60


def _rule_triggers(db: Session) -> dict[str, dict]:
    """Auslösungen der letzten 30 Tage aus dem Verlauf des Systemmonitors (system_health_event,
    Art «problem», Schlüssel ``auth:<regel>[:<subjekt>]``): Anzahl, je Tag, letzte drei."""
    start = datetime.now(UTC) - timedelta(days=TRIGGER_DAYS)
    rows = db.execute(
        text(
            "SELECT split_part(subject, ':', 2) AS rule, split_part(subject, ':', 3) AS subject, severity, created_at FROM system_health_event "
            "WHERE kind = 'problem' AND subject LIKE 'auth:%' AND created_at > :start ORDER BY created_at DESC LIMIT 5000"
        ),
        {"start": start},
    ).mappings()
    today = datetime.now(UTC).date()
    result: dict[str, dict] = {}
    for row in rows:
        item = result.setdefault(row["rule"], {"count": 0, "daily": [0] * TRIGGER_DAYS, "recent": []})
        item["count"] += 1
        age = (today - row["created_at"].astimezone(UTC).date()).days
        if 0 <= age < TRIGGER_DAYS:
            item["daily"][TRIGGER_DAYS - 1 - age] += 1
        if len(item["recent"]) < _RECENT_PER_RULE:
            item["recent"].append({"at": row["created_at"], "subject": (row["subject"] or None) and row["subject"][:12], "severity": row["severity"]})
    return result


def alert_rules(db: Session) -> list[dict]:
    """Alle zehn Regeln mit Messwert gegen Schwelle (auch darunter), Zustand, Auslösungen 30 Tage
    und wirksamen Einstellungen (nur lesen)."""
    from app.auth_security import threats
    from app.core.config import settings

    alerts, measured = _detect(db)
    triggers = _rule_triggers(db)
    result = []
    for rule, window in threats.RULE_WINDOW_MINUTES.items():
        measurement = measured.get(rule)
        fired = [alert for alert in alerts if alert["rule"] == rule]
        value = measurement.value if measurement else 0.0
        threshold = measurement.threshold if measurement else 0.0
        if fired:
            state = "fired"
        elif threshold and value / threshold >= NEAR_RATIO:
            state = "near"
        else:
            state = "quiet"
        history = triggers.get(rule, {"count": 0, "daily": [0] * TRIGGER_DAYS, "recent": []})
        result.append({
            "rule": rule, "window_minutes": window, "value": value, "threshold": threshold,
            "comparator": measurement.comparator if measurement else ">=", "state": state,
            "severity": "critical" if any(alert["severity"] == "critical" for alert in fired) else threats.RULE_SEVERITY.get(rule, "warning"),
            "fired": len(fired), "triggers_30d": history["count"], "daily_30d": history["daily"], "recent": history["recent"],
            "settings": {name: getattr(settings, name) for name in threats.RULE_SETTINGS[rule]},
        })
    return result


def alert_rule_series(db: Session, rule: str) -> dict:
    """Kurve 24 h einer Regel mit allen Abschnitten (auch leeren), 60 s zwischengespeichert."""
    import time

    from app.auth_security import threats

    now = time.monotonic()
    cached = _series_cache.get(rule)
    if cached and now - cached[0] < _SERIES_CACHE_SECONDS:
        return cached[1]
    raw = threats.series(db, rule)
    step = timedelta(minutes=raw["bucket_minutes"])
    end = datetime.now(UTC)
    first = datetime.fromtimestamp((int((end - timedelta(hours=raw["hours"])).timestamp()) // int(step.total_seconds()) + 1) * int(step.total_seconds()), UTC)
    points = []
    at = first
    while at <= end:
        points.append({"start": at, "value": raw["values"].get(at, 0.0)})
        at += step
    result = {**{key: value for key, value in raw.items() if key != "values"}, "points": points}
    _series_cache[rule] = (now, result)
    return result


def platform_counters(db: Session) -> dict:
    """Kennzahlen für die Kacheln der Sicherheits-Übersicht (24 h)."""
    row = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE outcome = 'failure') AS failures_24h, "
            "count(*) FILTER (WHERE event_type = 'admin.login.success') AS admin_logins_24h, "
            "count(*) FILTER (WHERE outcome = 'blocked') AS blocked_24h "
            "FROM auth_event WHERE ts > now() - interval '24 hours'"
        )
    ).mappings().one()
    previous = db.scalar(
        text("SELECT count(*) FROM auth_event WHERE outcome = 'failure' AND ts BETWEEN now() - interval '48 hours' AND now() - interval '24 hours'")
    )
    return {**dict(row), "failures_prev_24h": int(previous or 0)}
