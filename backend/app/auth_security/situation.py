"""Lagebild des Sicherheitsbereichs (1.7, Design «hocX Sicherheit Lagebild»).

Nur echte Daten aus ``auth_event``, den Vorfällen und den Alarmregeln:

- Lage-Stufe: Angriffsmodus (Regel «stuffing» löst aus - der Anmeldeschutz prüft unbekannte Geräte
  zusätzlich), Angriff (offener kritischer Vorfall, dessen Regel noch auslöst), erhöht (offene
  Vorfälle oder eine Regel nahe der Schwelle), sonst ruhig.
- Kennzahlen des Zeitraums mit Vorperiode und Verlauf (gleiche Abschnitte wie das Diagramm).
- Verlauf Fehlversuche/abgewiesen/Zusatzprüfung/erfolgreich mit Vorfall-Markierungen.
- Fehlversuche nach Wochentag × Stunde (immer 7 Tage, Zeitzone Europe/Zurich).
- Herkunft der Fehlversuche nach Land (GeoIP-Code, nie die Adresse), auffällige Netze und Konten (gekürzt).

Je Zeitraum 30 s im Prozess zwischengespeichert (Live-Ansicht fragt alle 30 s).
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_security import incidents, read_service

RANGES: dict[str, tuple[timedelta, int]] = {
    # Zeitraum → (Dauer, Abschnitt in Minuten)
    "24h": (timedelta(hours=24), 30),
    "7d": (timedelta(days=7), 180),
}
HEATMAP_DAYS = 7
_TZ = "Europe/Zurich"
_CACHE_SECONDS = 30
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _series(db: Session, start: datetime, end: datetime, bucket_minutes: int) -> list[dict]:
    step = bucket_minutes * 60
    rows = {
        int(row.b): row
        for row in db.execute(
            text(
                "SELECT floor((extract(epoch FROM ts) - :origin) / :step) AS b, "
                "count(*) FILTER (WHERE outcome = 'failure') AS failures, count(*) FILTER (WHERE outcome = 'blocked') AS blocked, "
                "count(*) FILTER (WHERE outcome = 'challenged') AS challenged, "
                "count(*) FILTER (WHERE event_type IN ('login.success', 'admin.login.success')) AS successes "
                "FROM auth_event WHERE ts >= :start AND ts < :end GROUP BY 1"
            ),
            {"origin": start.timestamp(), "step": step, "start": start, "end": end},
        )
    }
    count = int((end - start).total_seconds() // step)
    points = []
    for index in range(count):
        row = rows.get(index)
        points.append({
            "start": start + timedelta(seconds=index * step),
            "failures": int(row.failures) if row else 0, "blocked": int(row.blocked) if row else 0,
            "challenged": int(row.challenged) if row else 0, "successes": int(row.successes) if row else 0,
        })
    return points


def _totals(db: Session, start: datetime, end: datetime) -> dict:
    """Summen eines Zeitraums (aktuell und Vorperiode, gleiche Definition wie der Verlauf)."""
    row = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE outcome = 'failure') AS failures, count(*) FILTER (WHERE outcome = 'blocked') AS blocked, "
            "count(*) FILTER (WHERE outcome = 'challenged') AS challenged, "
            "count(*) FILTER (WHERE event_type IN ('login.success', 'admin.login.success')) AS successes, "
            "count(*) FILTER (WHERE event_type = 'admin.login.success') AS admin_logins "
            "FROM auth_event WHERE ts >= :start AND ts < :end"
        ),
        {"start": start, "end": end},
    ).mappings().one()
    return {key: int(value or 0) for key, value in row.items()}


def _heatmap(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT extract(isodow FROM ts AT TIME ZONE :tz)::int AS dow, extract(hour FROM ts AT TIME ZONE :tz)::int AS hour, count(*) AS n "
            "FROM auth_event WHERE outcome = 'failure' AND ts > now() - make_interval(days => :days) GROUP BY 1, 2"
        ),
        {"tz": _TZ, "days": HEATMAP_DAYS},
    )
    return [{"dow": row.dow, "hour": row.hour, "count": int(row.n)} for row in rows]


def _countries(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT src_country AS code, count(*) AS failures FROM auth_event WHERE outcome = 'failure' AND ts >= :start AND ts < :end "
            "GROUP BY src_country ORDER BY failures DESC LIMIT 8"
        ),
        {"start": start, "end": end},
    )
    return [{"code": row.code, "failures": int(row.failures)} for row in rows]


def _networks(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT src_net_hash, count(*) FILTER (WHERE outcome = 'failure') AS failures, count(DISTINCT subject_hash) AS accounts, "
            "count(DISTINCT tenant_id) AS tenants, max(src_country) AS country FROM auth_event "
            "WHERE ts >= :start AND ts < :end AND src_net_hash IS NOT NULL "
            "GROUP BY src_net_hash HAVING count(*) FILTER (WHERE outcome = 'failure') > 0 ORDER BY failures DESC LIMIT 5"
        ),
        {"start": start, "end": end},
    )
    return [
        {"net": row.src_net_hash[:12], "failures": int(row.failures), "accounts": int(row.accounts), "tenants": int(row.tenants),
         "country": row.country}
        for row in rows
    ]


def _accounts(db: Session, start: datetime, end: datetime) -> list[dict]:
    """Auffällige Konten (Plan: top_accounts nicht verlieren) - nur gekürzte Pseudonyme."""
    rows = db.execute(
        text(
            "SELECT subject_hash, count(*) AS failures, count(DISTINCT src_net_hash) AS networks FROM auth_event "
            "WHERE ts >= :start AND ts < :end AND outcome = 'failure' AND subject_hash IS NOT NULL "
            "GROUP BY subject_hash ORDER BY failures DESC LIMIT 5"
        ),
        {"start": start, "end": end},
    )
    return [{"subject": row.subject_hash[:12], "failures": int(row.failures), "networks": int(row.networks)} for row in rows]


def _markers(db: Session, start: datetime) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT id, rule, severity, status, first_seen_at FROM security_incident WHERE first_seen_at >= :start "
            "ORDER BY first_seen_at LIMIT 50"
        ),
        {"start": start},
    )
    return [{"id": row.id, "rule": row.rule, "severity": row.severity, "status": row.status, "at": row.first_seen_at} for row in rows]


def _posture(db: Session) -> dict:
    alerts, measured = read_service._detect(db)
    rules_near = 0
    for measurement in measured.values():
        if measurement.threshold and measurement.value / measurement.threshold >= read_service.NEAR_RATIO:
            rules_near += 1
    open_row = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE status IN ('new', 'in_progress')) AS open, "
            "count(*) FILTER (WHERE status IN ('new', 'in_progress') AND severity = 'critical') AS critical, "
            "count(*) FILTER (WHERE status IN ('new', 'in_progress') AND severity = 'critical' AND active) AS critical_active "
            "FROM security_incident"
        )
    ).mappings().one()
    attack_mode = any(alert["rule"] == "stuffing" for alert in alerts)
    if attack_mode:
        level = "attack_mode"
    elif open_row["critical_active"]:
        level = "attack"
    elif open_row["open"] or alerts or rules_near:
        level = "elevated"
    else:
        level = "calm"
    return {
        "level": level, "attack_mode": attack_mode, "open": int(open_row["open"] or 0), "critical": int(open_row["critical"] or 0),
        "active_rules": len({alert["rule"] for alert in alerts}), "rules_near": rules_near,
    }


def situation(db: Session, range_: str) -> dict:
    if range_ not in RANGES:
        raise ValueError("Zeitraum ungültig")
    now = time.monotonic()
    with _lock:
        hit = _cache.get(range_)
        if hit and now - hit[0] < _CACHE_SECONDS:
            return hit[1]
    span, bucket_minutes = RANGES[range_]
    step = bucket_minutes * 60
    # Abschnitte an festen Grenzen (gleiche Balken über mehrere Abrufe), letzter Abschnitt bis jetzt
    end_ts = (int(datetime.now(UTC).timestamp()) // step + 1) * step
    end = datetime.fromtimestamp(end_ts, UTC)
    start = end - span
    points = _series(db, start, end, bucket_minutes)
    result = {
        "range": range_, "start": start, "end": end, "bucket_minutes": bucket_minutes,
        "posture": _posture(db),
        "points": points, "totals": _totals(db, start, end), "previous": _totals(db, start - span, start),
        "incident_stats": incidents.stats(db),
        "markers": _markers(db, start),
        "heatmap": _heatmap(db), "heatmap_days": HEATMAP_DAYS,
        "countries": _countries(db, start, end),
        "networks": _networks(db, start, end),
        "accounts": _accounts(db, start, end),
        "active_blocks": len(read_service.blocks.active_blocks()),
    }
    with _lock:
        _cache[range_] = (now, result)
    return result
