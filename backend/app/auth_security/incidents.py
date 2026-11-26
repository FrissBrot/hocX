"""Vorfälle des Anmeldeschutzes (1.7, Migration 0282, Plan «1.7: Vorfälle und Lagebild").

Bündelung (User-Entscheid 2026-11-23): je Regelschlüssel ``auth:<regel>[:<pseudonym>]`` genau ein
offener Vorfall. Der Systemmonitor ruft bei jedem Durchlauf ``correlate`` mit den ausgelösten Regeln
(``threats.detect``) auf:

- Regel löst aus, offener Vorfall vorhanden → gebündelt (letzte Auslösung, ggf. «erneut ausgelöst»
  nach dem Abklingen, «verschärft» bei warning → critical).
- kein offener Vorfall → neuer Vorfall, ausser das auslösende Ereignis liegt nicht nach dem
  Abschluss des letzten Vorfalls desselben Schlüssels (derselbe Ausbruch wurde schon bearbeitet).
- Regel klingt ab → Vorfall bleibt im Status, «abgeklungen» in der Zeitleiste. Abschliessen und
  Wiederöffnen nur durch Plattform-Admins (owner, mit Passkey; Routen in admin_auth_security.py).

Fakten, Zeitleiste, Beteiligte und Gründe kommen beim Lesen aus ``auth_event`` im Bereich der Regel
(Netz-, Konto-Pseudonym, Admin oder Mandant, für plattformweite Regeln deren Bedingung) und im
Zeitraum des Vorfalls (höchstens 14 Tage). Ausgaben nur mit gekürzten Pseudonymen, nie Adressen.

Alle SQL-Teile sind feste Fragmente aus diesem Modul bzw. ``threats._RULE_SQL``; Werte gehen nur als
gebundene Parameter.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_security import threats

OPEN_STATUSES = ("new", "in_progress")
CLOSED_STATUSES = ("resolved", "false_positive")
STATUSES = OPEN_STATUSES + CLOSED_STATUSES
STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "open": OPEN_STATUSES,
    "new": ("new",),
    "in_progress": ("in_progress",),
    "closed": CLOSED_STATUSES,
    "all": STATUSES,
}
SEVERITIES = ("critical", "warning")
NET_RULES = frozenset({"spraying", "network", "cross_tenant"})
ACCOUNT_RULES = frozenset({"account_attack"})
ADMIN_RULES = frozenset({"admin_mfa", "admin_new_device"})
TENANT_RULES = frozenset({"tenant"})
MAX_SPAN = timedelta(days=14)
SPARK_BUCKETS = 12
STATS_DAYS = 30
NOTE_MAX = 1000
_SHORT = 12
_LIMIT_LAYERS = ("attempt_rate", "account_source", "source", "account")
_SEVERITY_RANK = {"warning": 1, "critical": 2}


class IncidentNotFound(LookupError):
    pass


class IncidentConflict(ValueError):
    """Zustand erlaubt die Änderung nicht (z. B. Wiederöffnen, solange ein anderer Vorfall desselben
    Schlüssels offen ist). Die Route antwortet 409."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── Bündelung (Systemmonitor) ───────────────────────────────────────────────────────────────


def _tenant_for(db: Session, threat) -> int | None:
    if threat.rule in TENANT_RULES and str(threat.subject or "").isdigit():
        return db.scalar(text("SELECT id FROM tenant WHERE id = :id"), {"id": int(threat.subject)})
    return None


def _activity(db: Session, incident_id: int, kind: str, *, admin_id: int | None = None, from_value: str | None = None,
              to_value: str | None = None, note: str | None = None, at: datetime | None = None) -> None:
    db.execute(
        text(
            "INSERT INTO security_incident_activity (incident_id, created_at, kind, admin_id, from_value, to_value, note) "
            "VALUES (:incident, coalesce(:at, clock_timestamp()), :kind, :admin, :from_value, :to_value, :note)"
        ),
        {"incident": incident_id, "at": at, "kind": kind, "admin": admin_id, "from_value": from_value, "to_value": to_value, "note": note},
    )


def correlate(db: Session, detected: list, *, now: datetime | None = None) -> dict:
    """Ausgelöste Regeln zu Vorfällen bündeln (ein Durchlauf des Systemmonitors, unter dessen
    Advisory-Lock). Liefert Zähler für Tests und Protokoll; committet selbst."""
    now = now or datetime.now(UTC)
    active = {threat.key: threat for threat in detected if len(threat.key) <= 200}
    rows = {
        row.rule_key: row
        for row in db.execute(
            text(
                "SELECT id, rule_key, severity, active, last_triggered_at FROM security_incident "
                "WHERE status IN ('new', 'in_progress') ORDER BY id FOR UPDATE"
            )
        )
    }
    created = bundled = cleared = 0
    for key, threat in active.items():
        triggered_at = threat.last_at or now
        row = rows.get(key)
        if row is not None:
            bundled += 1
            changes = {"last": max(row.last_triggered_at, triggered_at)}
            if not row.active:
                _activity(db, row.id, "retriggered", to_value=threat.severity, at=now)
                db.execute(
                    text("UPDATE security_incident SET active = true, trigger_count = trigger_count + 1, updated_at = :now WHERE id = :id"),
                    {"id": row.id, "now": now},
                )
            if _SEVERITY_RANK.get(threat.severity, 1) > _SEVERITY_RANK.get(row.severity, 1):
                _activity(db, row.id, "escalated", from_value=row.severity, to_value=threat.severity, at=now)
                db.execute(text("UPDATE security_incident SET severity = :severity, updated_at = :now WHERE id = :id"),
                           {"id": row.id, "severity": threat.severity, "now": now})
            db.execute(text("UPDATE security_incident SET last_triggered_at = :last WHERE id = :id"), {"id": row.id, **changes})
            continue
        last_closed = db.scalar(
            text("SELECT max(closed_at) FROM security_incident WHERE rule_key = :key AND status IN ('resolved', 'false_positive')"),
            {"key": key},
        )
        if last_closed is not None and triggered_at <= last_closed:
            # Derselbe Ausbruch wurde schon abgeschlossen; erst ein neues Ereignis eröffnet einen Vorfall
            continue
        incident_id = db.scalar(
            text(
                "INSERT INTO security_incident (rule_key, rule, subject, severity, tenant_id, first_seen_at, last_triggered_at, updated_at) "
                "VALUES (:key, :rule, :subject, :severity, :tenant, :now, :last, :now) "
                "ON CONFLICT (rule_key) WHERE status IN ('new', 'in_progress') DO NOTHING RETURNING id"
            ),
            {"key": key, "rule": threat.rule, "subject": threat.subject, "severity": threat.severity if threat.severity in SEVERITIES else "warning",
             "tenant": _tenant_for(db, threat), "now": now, "last": triggered_at},
        )
        if incident_id is not None:
            _activity(db, incident_id, "triggered", to_value=threat.severity, at=now)
            created += 1
    for key, row in rows.items():
        if key not in active and row.active:
            db.execute(text("UPDATE security_incident SET active = false, cleared_at = :now, updated_at = :now WHERE id = :id"),
                       {"id": row.id, "now": now})
            _activity(db, row.id, "cleared", at=now)
            cleared += 1
    # Abgeschlossene Vorfälle, deren Regel noch auslöste, klingen ebenfalls ab (Anzeige «aktiv»)
    db.execute(
        text(
            "UPDATE security_incident SET active = false, cleared_at = :now WHERE active AND status IN ('resolved', 'false_positive') "
            "AND NOT (rule_key = ANY(:keys))"
        ),
        {"now": now, "keys": list(active)},
    )
    db.commit()
    return {"created": created, "bundled": bundled, "cleared": cleared}


def open_new_count(db: Session) -> int:
    """Offene Vorfälle im Status «Neu» (Nav-Badge und Glocke, ersetzt die Quittung aus 0209)."""
    return int(db.scalar(text("SELECT count(*) FROM security_incident WHERE status = 'new'")) or 0)


def open_incident_for_keys(db: Session, keys: list[str]) -> dict[str, dict]:
    """Offener (sonst jüngster) Vorfall je Regelschlüssel - für die Warnungsliste der Alarmregeln."""
    if not keys:
        return {}
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (i.rule_key) i.rule_key, i.id, i.status, a.display_name AS assignee "
            "FROM security_incident i LEFT JOIN platform_admin a ON a.id = i.assignee_admin_id "
            "WHERE i.rule_key = ANY(:keys) ORDER BY i.rule_key, (i.status IN ('new', 'in_progress')) DESC, i.id DESC"
        ),
        {"keys": keys},
    )
    return {row.rule_key: {"id": row.id, "status": row.status, "assignee": row.assignee} for row in rows}


def purge(db: Session, *, retention_days: int) -> int:
    """Aufbewahrung (Plan: 365 Tage): Vorfälle samt Zeitleiste und Notizen löschen, deren letzte
    Aktivität (Änderung oder Auslösung) älter ist - unabhängig vom Status."""
    deleted = db.execute(
        text(
            "DELETE FROM security_incident WHERE updated_at < now() - make_interval(days => :days) "
            "AND last_triggered_at < now() - make_interval(days => :days)"
        ),
        {"days": max(1, int(retention_days))},
    ).rowcount or 0
    db.commit()
    return deleted


# ── Bereich einer Regel in auth_event ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scope:
    sql: str
    params: dict
    scoped: bool          # an ein Netz, Konto, Admin oder Mandant gebunden (sonst plattformweit)


def _prefix(column: str, name: str, value: str) -> tuple[str, dict]:
    # wie event_query._PREFIX_SQL: Bereich + left() nutzt den Index (spalte, ts)
    return (
        f"e.{column} >= :{name} AND e.{column} < :{name}_hi AND left(e.{column}, :{name}_len) = :{name}",  # sql-ok: feste Spaltennamen
        {name: value, f"{name}_hi": value + "g", f"{name}_len": len(value)},
    )


def _is_hex(value: str | None) -> bool:
    return bool(value) and 4 <= len(value) <= 64 and all(ch in "0123456789abcdef" for ch in value)


def scope_for(rule: str, subject: str | None) -> Scope:
    if rule in NET_RULES and _is_hex(subject):
        sql, params = _prefix("src_net_hash", "scope_net", subject)
        return Scope(sql, params, True)
    if rule in ACCOUNT_RULES and _is_hex(subject):
        sql, params = _prefix("subject_hash", "scope_subject", subject)
        return Scope(sql, params, True)
    if rule in ADMIN_RULES and str(subject or "").isdigit():
        return Scope("e.platform_admin_id = :scope_admin", {"scope_admin": int(subject)}, True)
    if rule in TENANT_RULES and str(subject or "").isdigit():
        return Scope("e.tenant_id = :scope_tenant", {"scope_tenant": int(subject)}, True)
    condition = threats._RULE_SQL.get(rule, ("false", None, ""))[0]
    return Scope(f"({condition})", {}, False)


def _window(row) -> tuple[datetime, datetime]:
    """Zeitraum des Vorfalls: Regel-Fenster vor der ersten Erkennung bis jetzt (aktiv) bzw. bis zum
    Abklingen; höchstens MAX_SPAN."""
    minutes = threats.RULE_WINDOW_MINUTES.get(row.rule, 60)
    now = datetime.now(UTC)
    if row.active:
        end = now
    else:
        end = row.cleared_at or (row.last_triggered_at + timedelta(minutes=minutes))
    end = min(end, now)
    start = row.first_seen_at - timedelta(minutes=minutes)
    start = max(start, end - MAX_SPAN)
    return start, max(end, start + timedelta(minutes=1))


def _short(value: str | None) -> str | None:
    return value[:_SHORT] if value else None


# ── Lesen ────────────────────────────────────────────────────────────────────────────────


_INCIDENT_COLUMNS = (
    "i.id, i.rule_key, i.rule, i.subject, i.severity, i.status, i.tenant_id, i.first_seen_at, i.last_triggered_at, i.active, "
    "i.cleared_at, i.trigger_count, i.acknowledged_at, i.closed_at, i.updated_at, a.public_id AS assignee_id, "
    "a.display_name AS assignee_name, t.public_id AS tenant_public_id, t.name AS tenant_name"
)
_INCIDENT_FROM = (
    "FROM security_incident i LEFT JOIN platform_admin a ON a.id = i.assignee_admin_id LEFT JOIN tenant t ON t.id = i.tenant_id"
)


def _subject_label(db: Session, row) -> str | None:
    if row.rule in ADMIN_RULES and str(row.subject or "").isdigit():
        return db.scalar(text("SELECT display_name FROM platform_admin WHERE id = :id"), {"id": int(row.subject)})
    if row.rule in TENANT_RULES:
        return row.tenant_name
    return None


def _spark(db: Session, row) -> list[int]:
    start, end = _window(row)
    scope = scope_for(row.rule, row.subject)
    condition = threats._RULE_SQL.get(row.rule, ("false", None, ""))[0]
    values = [0] * SPARK_BUCKETS
    rows = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            f"SELECT least(width_bucket(extract(epoch FROM e.ts), :s, :e, {SPARK_BUCKETS}), {SPARK_BUCKETS}) AS b, count(*) AS n "  # sql-ok: feste Zahl
            f"FROM auth_event e WHERE e.ts >= :start AND e.ts < :end AND {scope.sql} AND ({condition}) GROUP BY 1"  # sql-ok: feste Fragmente
        ),
        {**scope.params, "start": start, "end": end, "s": start.timestamp(), "e": end.timestamp()},
    )
    for bucket, count in rows:
        if bucket and 1 <= bucket <= SPARK_BUCKETS:
            values[bucket - 1] = int(count)
    return values


def _item(db: Session, row, *, with_spark: bool) -> dict:
    return {
        "id": row.id, "key": row.rule_key, "rule": row.rule, "subject": row.subject, "subject_label": _subject_label(db, row),
        "severity": row.severity, "status": row.status, "active": row.active, "trigger_count": row.trigger_count,
        "first_seen_at": row.first_seen_at, "last_triggered_at": row.last_triggered_at, "cleared_at": row.cleared_at,
        "acknowledged_at": row.acknowledged_at, "closed_at": row.closed_at, "updated_at": row.updated_at,
        "assignee": {"id": row.assignee_id, "name": row.assignee_name} if row.assignee_id else None,
        "tenant": {"id": row.tenant_public_id, "name": row.tenant_name} if row.tenant_public_id else None,
        "window_minutes": threats.RULE_WINDOW_MINUTES.get(row.rule),
        "spark": _spark(db, row) if with_spark else None,
    }


@dataclass(frozen=True)
class IncidentFilter:
    status: str = "open"
    severities: tuple[str, ...] = ()
    assignee: str = "all"          # all | me | none
    q: str | None = None


def _filter_sql(flt: IncidentFilter, admin_id: int) -> tuple[list[str], dict]:
    conditions: list[str] = []
    params: dict = {}
    if flt.severities:
        conditions.append("i.severity = ANY(:severities)")
        params["severities"] = list(flt.severities)
    if flt.assignee == "me":
        conditions.append("i.assignee_admin_id = :me")
        params["me"] = admin_id
    elif flt.assignee == "none":
        conditions.append("i.assignee_admin_id IS NULL")
    term = (flt.q or "").strip().lower()
    if term:
        number = term.removeprefix("inc-").removeprefix("#").lstrip("0") or "0"
        parts = ["i.rule = :q_rule", "(i.subject IS NOT NULL AND left(i.subject, :q_len) = :q)"]
        params.update({"q_rule": term, "q": term, "q_len": len(term)})
        if number.isdigit() and len(number) <= 18:
            parts.append("i.id = :q_id")
            params["q_id"] = int(number)
        conditions.append("(" + " OR ".join(parts) + ")")
    return conditions, params


def list_incidents(db: Session, flt: IncidentFilter, *, admin_id: int, offset: int = 0, limit: int = 50) -> dict:
    base, params = _filter_sql(flt, admin_id)
    where_base = (" WHERE " + " AND ".join(base)) if base else ""
    counts_row = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT count(*) FILTER (WHERE i.status IN ('new', 'in_progress')) AS open, count(*) FILTER (WHERE i.status = 'new') AS new, "
            "count(*) FILTER (WHERE i.status = 'in_progress') AS in_progress, "
            "count(*) FILTER (WHERE i.status IN ('resolved', 'false_positive')) AS closed, count(*) AS all "
            f"FROM security_incident i{where_base}"  # sql-ok: feste Bedingungen aus _filter_sql
        ),
        params,
    ).mappings().one()
    conditions = [*base, "i.status = ANY(:statuses)"]
    params = {**params, "statuses": list(STATUS_GROUPS.get(flt.status, OPEN_STATUSES)), "limit": limit, "offset": offset}
    rows = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            f"SELECT {_INCIDENT_COLUMNS} {_INCIDENT_FROM} WHERE {' AND '.join(conditions)} "  # sql-ok: feste Spalten und Bedingungen
            "ORDER BY (i.status IN ('new', 'in_progress')) DESC, (i.severity = 'critical') DESC, i.first_seen_at DESC, i.id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        params,
    ).all()
    total = int(counts_row[flt.status] if flt.status in STATUS_GROUPS else counts_row["open"])
    return {
        "items": [_item(db, row, with_spark=True) for row in rows],
        "total": total, "offset": offset, "limit": limit,
        "counts": {key: int(value) for key, value in counts_row.items()},
    }


def stats(db: Session) -> dict:
    """Kacheln der Vorfall-Seite: offen, kritisch, ohne Zuständige, Ø bis Übernahme/erledigt und
    Fehlalarm-Quote der letzten 30 Tage."""
    row = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE status IN ('new', 'in_progress')) AS open, "
            "count(*) FILTER (WHERE status IN ('new', 'in_progress') AND severity = 'critical') AS critical, "
            "count(*) FILTER (WHERE status IN ('new', 'in_progress') AND assignee_admin_id IS NULL) AS unassigned, "
            "count(*) FILTER (WHERE status = 'new') AS new, "
            "avg(extract(epoch FROM acknowledged_at - first_seen_at)) FILTER (WHERE acknowledged_at IS NOT NULL "
            " AND first_seen_at > now() - make_interval(days => :days)) AS mtta, "
            "avg(extract(epoch FROM closed_at - first_seen_at)) FILTER (WHERE closed_at > now() - make_interval(days => :days)) AS mttr, "
            "count(*) FILTER (WHERE status = 'false_positive' AND closed_at > now() - make_interval(days => :days)) AS false_positives, "
            "count(*) FILTER (WHERE closed_at > now() - make_interval(days => :days)) AS closed "
            "FROM security_incident"
        ),
        {"days": STATS_DAYS},
    ).mappings().one()
    closed = int(row["closed"] or 0)
    return {
        "open": int(row["open"] or 0), "critical": int(row["critical"] or 0), "unassigned": int(row["unassigned"] or 0),
        "new": int(row["new"] or 0),
        "mtta_seconds": round(float(row["mtta"])) if row["mtta"] is not None else None,
        "mttr_seconds": round(float(row["mttr"])) if row["mttr"] is not None else None,
        "false_positives": int(row["false_positives"] or 0), "closed": closed,
        "false_positive_rate": (int(row["false_positives"] or 0) / closed) if closed else None,
        "days": STATS_DAYS,
    }


def _row(db: Session, incident_id: int, *, lock: bool = False):
    row = db.execute(
        text(f"SELECT {_INCIDENT_COLUMNS} {_INCIDENT_FROM} WHERE i.id = :id" + (" FOR UPDATE OF i" if lock else "")),  # sql-ok: feste Spalten
        {"id": incident_id},
    ).first()
    if row is None:
        raise IncidentNotFound(incident_id)
    return row


def _facts(db: Session, row, start: datetime, end: datetime, scope: Scope) -> dict:
    facts = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT count(*) AS events, count(*) FILTER (WHERE e.outcome = 'failure') AS failures, "
            "count(*) FILTER (WHERE e.outcome = 'blocked') AS blocked, count(*) FILTER (WHERE e.outcome = 'challenged') AS challenged, "
            "count(*) FILTER (WHERE e.event_type IN ('login.success', 'admin.login.success')) AS successes, "
            "count(DISTINCT e.subject_hash) AS accounts, count(DISTINCT e.src_net_hash) AS networks, "
            "count(DISTINCT e.tenant_id) AS tenants, count(DISTINCT e.src_country) AS countries, max(e.risk_score) AS max_risk, "
            "bool_or(e.outcome = 'failure') AS s1, "
            "bool_or(e.event_type = 'login.locked' AND e.details->>'layer' = ANY(:layers)) AS s2, "
            "bool_or(e.outcome = 'challenged') AS s3, "
            "bool_or(e.outcome = 'blocked' OR (e.event_type = 'block.set' AND e.details->>'stage' = '4')) AS s4, "
            "bool_or(e.event_type = 'block.set' AND e.details->>'stage' = '5') AS s5 "
            f"FROM auth_event e WHERE e.ts >= :start AND e.ts < :end AND {scope.sql}"  # sql-ok: feste Fragmente aus scope_for
        ),
        {**scope.params, "start": start, "end": end, "layers": list(_LIMIT_LAYERS)},
    ).mappings().one()
    manual_block = db.scalar(
        text("SELECT EXISTS (SELECT 1 FROM security_incident_activity WHERE incident_id = :id AND kind = 'block')"), {"id": row.id}
    )
    stage = 0
    for level in (1, 2, 3, 4, 5):
        if facts[f"s{level}"]:
            stage = level
    if manual_block:
        stage = 5
    return {
        "counts": {key: int(facts[key] or 0) for key in ("events", "failures", "blocked", "challenged", "successes", "accounts", "networks",
                                                       "tenants", "countries")},
        "max_risk": facts["max_risk"], "stage": stage,
    }


def _participants(db: Session, start: datetime, end: datetime, scope: Scope) -> dict:
    params = {**scope.params, "start": start, "end": end}
    where = f"e.ts >= :start AND e.ts < :end AND {scope.sql}"  # sql-ok: feste Fragmente aus scope_for
    networks = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT e.src_net_hash AS key, count(*) AS events, count(*) FILTER (WHERE e.outcome = 'failure') AS failures, "
            f"max(e.src_country) AS country FROM auth_event e WHERE {where} AND e.src_net_hash IS NOT NULL "  # sql-ok: feste Fragmente
            "GROUP BY e.src_net_hash ORDER BY failures DESC, events DESC LIMIT 8"
        ),
        params,
    ).mappings()
    accounts = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT e.subject_hash AS key, count(*) AS events, count(*) FILTER (WHERE e.outcome = 'failure') AS failures "
            f"FROM auth_event e WHERE {where} AND e.subject_hash IS NOT NULL "  # sql-ok: feste Fragmente
            "GROUP BY e.subject_hash ORDER BY failures DESC, events DESC LIMIT 8"
        ),
        params,
    ).mappings()
    tenants = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT t.public_id AS id, t.name, count(*) AS events, count(*) FILTER (WHERE e.outcome = 'failure') AS failures, "
            f"count(DISTINCT e.subject_hash) AS accounts FROM auth_event e JOIN tenant t ON t.id = e.tenant_id WHERE {where} "  # sql-ok: feste Fragmente
            "GROUP BY t.public_id, t.name ORDER BY failures DESC, events DESC LIMIT 8"
        ),
        params,
    ).mappings()
    countries = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT e.src_country AS code, count(*) AS events, count(*) FILTER (WHERE e.outcome = 'failure') AS failures "
            f"FROM auth_event e WHERE {where} AND e.src_country IS NOT NULL "  # sql-ok: feste Fragmente
            "GROUP BY e.src_country ORDER BY failures DESC, events DESC LIMIT 8"
        ),
        params,
    ).mappings()
    return {
        "networks": [{**dict(row), "key": _short(row["key"])} for row in networks],
        "accounts": [{**dict(row), "key": _short(row["key"])} for row in accounts],
        "tenants": [dict(row) for row in tenants],
        "countries": [dict(row) for row in countries],
    }


def _reasons(db: Session, start: datetime, end: datetime, scope: Scope) -> list[dict]:
    rows = db.execute(
        text(  # sql-ok: nur feste Fragmente aus diesem Modul bzw. threats._RULE_SQL, Werte gebunden
            "SELECT r AS code, count(*) AS count, max(CASE WHEN e.details->'weights'->>r ~ '^[0-9]{1,3}$' "
            "THEN (e.details->'weights'->>r)::int END) AS weight "
            f"FROM auth_event e CROSS JOIN LATERAL unnest(e.risk_reasons) AS r WHERE e.ts >= :start AND e.ts < :end AND {scope.sql} "  # sql-ok: feste Fragmente
            "GROUP BY r ORDER BY weight DESC NULLS LAST, count DESC LIMIT 8"
        ),
        {**scope.params, "start": start, "end": end},
    ).mappings()
    return [dict(row) for row in rows]


_NOTABLE = (
    "(e.event_type IN ('block.set', 'block.clear', 'login.locked', 'login.challenge', 'login.success', 'admin.login.success', "
    "'reset.complete', 'password.change', 'session.revoke', 'mfa.remove') OR e.outcome IN ('blocked', 'challenged'))"
)
TIMELINE_EVENTS = 30


def _timeline_events(db: Session, row, start: datetime, end: datetime, scope: Scope) -> list[dict]:
    condition = threats._RULE_SQL.get(row.rule, ("false", None, ""))[0]
    params = {**scope.params, "start": start, "end": end, "limit": TIMELINE_EVENTS}
    where = f"e.ts >= :start AND e.ts < :end AND {scope.sql}"  # sql-ok: feste Fragmente aus scope_for
    columns = "e.event_id, e.ts, e.event_type, e.outcome, e.risk_score, e.subject_hash, e.src_net_hash, e.src_country, e.details"
    picked: dict = {}
    for order in ("ASC", "DESC"):
        first = db.execute(
            text(f"SELECT {columns} FROM auth_event e WHERE {where} AND ({condition}) ORDER BY e.ts {order}, e.id {order} LIMIT 1"),  # sql-ok: feste Fragmente
            params,
        ).mappings().first()
        if first:
            picked[first["event_id"]] = (first, "first" if order == "ASC" else "last")
    # plattformweite Regeln: nur die Ereignisse der Regel selbst (Sperren, Limiter-Ausfälle); gebundene
    # Regeln: alles Auffällige im Bereich (Sperren, Prüfungen, Erfolge)
    notable = condition if not scope.scoped else _NOTABLE
    if scope.scoped or row.rule in ("blocks", "limiter"):
        for item in db.execute(
            text(f"SELECT {columns} FROM auth_event e WHERE {where} AND {notable} ORDER BY e.ts DESC, e.id DESC LIMIT :limit"),  # sql-ok: feste Fragmente
            params,
        ).mappings():
            picked.setdefault(item["event_id"], (item, None))
    result = []
    for item, marker in picked.values():
        details = item["details"] or {}
        result.append({
            "kind": "event", "at": item["ts"], "event_id": item["event_id"], "event_type": item["event_type"], "outcome": item["outcome"],
            "risk_score": item["risk_score"], "subject": _short(item["subject_hash"]), "net": _short(item["src_net_hash"]),
            "country": item["src_country"], "marker": marker,
            "stage": details.get("stage") if item["event_type"] == "block.set" else None,
            "block_scope": details.get("scope") if item["event_type"] in ("block.set", "block.clear") else None,
        })
    return result


def detail(db: Session, incident_id: int) -> dict:
    row = _row(db, incident_id)
    start, end = _window(row)
    scope = scope_for(row.rule, row.subject)
    activity = [
        {
            "kind": "activity", "id": item.id, "at": item.created_at, "type": item.kind, "admin": item.admin_name,
            "from": item.from_value, "to": item.to_value, "note": item.note,
        }
        for item in db.execute(
            text(
                "SELECT x.id, x.created_at, x.kind, x.from_value, x.to_value, x.note, a.display_name AS admin_name "
                "FROM security_incident_activity x LEFT JOIN platform_admin a ON a.id = x.admin_id "
                "WHERE x.incident_id = :id ORDER BY x.created_at, x.id"
            ),
            {"id": row.id},
        )
    ]
    events = _timeline_events(db, row, start, end, scope)
    timeline = sorted([item for item in activity if item["type"] != "note"] + events, key=lambda item: item["at"])
    facts = _facts(db, row, start, end, scope)
    assignees = [
        {"id": item.public_id, "name": item.display_name}
        for item in db.execute(text("SELECT public_id, display_name FROM platform_admin WHERE role = 'owner' AND is_active ORDER BY display_name"))  # rbac-ok: Plattform-Admin-Rolle (Zuständige nur owner, wie require_admin_owner)
    ]
    return {
        **_item(db, row, with_spark=True),
        "window": {"start": start, "end": end},
        "facts": facts["counts"], "max_risk": facts["max_risk"], "stage": facts["stage"],
        "participants": _participants(db, start, end, scope),
        "reasons": _reasons(db, start, end, scope),
        "timeline": timeline,
        "notes": [item for item in activity if item["type"] == "note"],
        "assignees": assignees,
        "can_block": row.rule in NET_RULES and _is_hex(row.subject),
        # Für «Alle Ereignisse»: Pseudonym-Präfix als Filter der Ereignisseite (keine Namen)
        "event_filter": {"net": row.subject} if row.rule in NET_RULES and _is_hex(row.subject)
        else {"subject": row.subject} if row.rule in ACCOUNT_RULES and _is_hex(row.subject)
        else {"tenant_id": row.tenant_public_id} if row.tenant_public_id else {},
    }


# ── Ändern (Routen mit Passkey, owner) ────────────────────────────────────────────────────


def _touch(db: Session, incident_id: int) -> None:
    db.execute(text("UPDATE security_incident SET updated_at = now() WHERE id = :id"), {"id": incident_id})


def set_status(db: Session, incident_id: int, status: str, *, admin_id: int, note: str | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError("Status ungültig")
    row = _row(db, incident_id, lock=True)
    if row.status == status:
        raise IncidentConflict("status_unchanged", "Der Vorfall hat diesen Status bereits.")
    if status in OPEN_STATUSES and row.status in CLOSED_STATUSES:
        other = db.scalar(
            text("SELECT id FROM security_incident WHERE rule_key = :key AND status IN ('new', 'in_progress') AND id <> :id"),
            {"key": row.rule_key, "id": row.id},
        )
        if other is not None:
            raise IncidentConflict("other_open", f"Zu dieser Regel ist schon Vorfall INC-{other:04d} offen.")
    db.execute(
        text(
            "UPDATE security_incident SET status = :status, updated_at = now(), "
            "closed_at = CASE WHEN :status IN ('resolved', 'false_positive') THEN now() ELSE NULL END, "
            "acknowledged_at = CASE WHEN acknowledged_at IS NULL AND :status <> 'new' THEN now() ELSE acknowledged_at END "
            "WHERE id = :id"
        ),
        {"id": row.id, "status": status},
    )
    _activity(db, row.id, "status", admin_id=admin_id, from_value=row.status, to_value=status)
    if note:
        _activity(db, row.id, "note", admin_id=admin_id, note=note[:NOTE_MAX])
    db.commit()
    return {"id": row.id, "from": row.status, "to": status}


def assign(db: Session, incident_id: int, assignee_public_id: uuid.UUID | None, *, admin_id: int) -> dict:
    row = _row(db, incident_id, lock=True)
    if row.status in CLOSED_STATUSES:
        raise IncidentConflict("closed", "Abgeschlossene Vorfälle werden nicht mehr zugewiesen.")
    target = None
    target_name = None
    if assignee_public_id is not None:
        found = db.execute(
            text("SELECT id, display_name FROM platform_admin WHERE public_id = :id AND role = 'owner' AND is_active"),  # rbac-ok: Plattform-Admin-Rolle, zuständig nur owner
            {"id": assignee_public_id},
        ).first()
        if found is None:
            raise IncidentNotFound("assignee")
        target, target_name = found.id, found.display_name
    unchanged = row.assignee_id is None if assignee_public_id is None else str(row.assignee_id) == str(assignee_public_id)
    if unchanged:
        raise IncidentConflict("assignee_unchanged", "Die Zuständigkeit ist bereits so gesetzt.")
    db.execute(
        text(
            "UPDATE security_incident SET assignee_admin_id = :target, updated_at = now(), "
            "acknowledged_at = CASE WHEN acknowledged_at IS NULL AND :target IS NOT NULL THEN now() ELSE acknowledged_at END WHERE id = :id"
        ),
        {"id": row.id, "target": target},
    )
    _activity(db, row.id, "assigned", admin_id=admin_id, from_value=row.assignee_name[:64] if row.assignee_name else None,
              to_value=target_name[:64] if target_name else None)
    status_changed = False
    if target is not None and row.status == "new":
        # Übernehmen = «In Bearbeitung» (Design «Vorfälle»)
        db.execute(text("UPDATE security_incident SET status = 'in_progress' WHERE id = :id"), {"id": row.id})
        _activity(db, row.id, "status", admin_id=admin_id, from_value="new", to_value="in_progress")
        status_changed = True
    db.commit()
    return {"id": row.id, "assignee": target_name, "status_changed": status_changed}


def add_note(db: Session, incident_id: int, note: str, *, admin_id: int) -> dict:
    row = _row(db, incident_id, lock=True)
    _activity(db, row.id, "note", admin_id=admin_id, note=note[:NOTE_MAX])
    _touch(db, row.id)
    db.commit()
    return {"id": row.id}


def block_target(db: Session, incident_id: int) -> tuple[str, str]:
    """(voller Netz-Fingerprint, gekürzt) des jüngsten Ereignisses im Netz des Vorfalls, das nicht
    von einem Plattform-Admin stammt. ValueError, wenn der Vorfall kein Netz betrifft."""
    row = _row(db, incident_id)
    if row.rule not in NET_RULES or not _is_hex(row.subject):
        raise IncidentConflict("no_network", "Dieser Vorfall betrifft kein einzelnes Netz.")
    scope = scope_for(row.rule, row.subject)
    fingerprint = db.scalar(
        text(f"SELECT e.src_net_hash FROM auth_event e WHERE {scope.sql} AND e.actor_kind <> 'admin' ORDER BY e.ts DESC LIMIT 1"),  # sql-ok: feste Fragmente
        scope.params,
    )
    if not fingerprint:
        raise IncidentConflict("no_network", "Zu diesem Vorfall ist kein Netz bekannt.")
    return fingerprint, fingerprint[:_SHORT]


def record_block(db: Session, incident_id: int, short: str, *, admin_id: int) -> None:
    _activity(db, incident_id, "block", admin_id=admin_id, to_value=short)
    _touch(db, incident_id)
    db.commit()
