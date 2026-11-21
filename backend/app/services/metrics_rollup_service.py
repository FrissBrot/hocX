"""Täglicher Kennzahlen-Rollup (Admin-Redesign Phase D, Migration 0208_platform_metrics).

Der Job ``metrics_rollup`` schreibt je Kalendertag (Europe/Zurich) Zählwerte in
``platform_metric_daily`` (plattformweit) und ``tenant_metric_daily`` (je Mandant). Dashboard und
Analysen lesen danach nur diese Tabellen statt teurer Live-Abfragen.

Grundsätze:
- **Nur Zählwerte, keine Personendaten.** Kein Name, keine E-Mail, keine Benutzer-ID landet in
  den Tabellen - auch ``users.active`` ist nur eine Anzahl.
- **Idempotent:** jeder Tag wird per ``ON CONFLICT DO UPDATE`` neu geschrieben; ein zweiter Lauf
  für denselben Tag ändert nichts ausser ``computed_at``.
- **Backfill** einmalig (Tabelle leer): die letzten ``BACKFILL_DAYS`` Tage aus ``audit_log``,
  ``system_error_log`` und ``created_at``-Spalten. Speicher, Feature-Buchungen und MRR sind
  Momentaufnahmen und entstehen erst ab Einführung (kein Backfill, so kommuniziert in den
  Analysen über ``collecting_since``).
- Läuft im job-worker (Speicher-SUM je Mandant ist teuer), Laufzeit je Tag über
  ``statement_timeout`` begrenzt.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.error_log import record_system_error

_logger = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Zurich")
BACKFILL_DAYS = 90
STATEMENT_TIMEOUT = "120s"

# Gleiche Aktionen wie die Systemprüfung «security» (system_health_service) - so passen Dashboard,
# Systemstatus und Analysen zusammen.
LOGIN_FAILURE_ACTIONS = ("user.login_failed", "admin.login_failed", "user.mfa_failed", "admin.mfa_failed", "user.passkey_failed")

# Nutzung je Modul: angelegte Datensätze pro Tag und Mandant (billige created_at-Zählungen).
USAGE_TABLES = {
    "usage.protocols": "protocol",
    "usage.files": "stored_file",
    "usage.events": "event",
}

# Metriken, die nur als Momentaufnahme für den aktuellen Rollup-Tag entstehen (kein Backfill).
SNAPSHOT_METRICS = ("storage.bytes_total", "mrr_rp", "feature.booked")


def today_local() -> date:
    return datetime.now(TZ).date()


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=TZ)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=TZ)
    return start, end


def _upsert_platform(db: Session, day: date, metric: str, value: float | int, dimension: str = "") -> None:
    db.execute(
        text(
            "INSERT INTO platform_metric_daily (day, metric, dimension, value, computed_at) "
            "VALUES (:day, :metric, :dimension, :value, now()) "
            "ON CONFLICT (day, metric, dimension) DO UPDATE SET value = EXCLUDED.value, computed_at = now()"
        ),
        {"day": day, "metric": metric, "dimension": dimension, "value": value},
    )


def _upsert_tenant_rows(db: Session, day: date, metric: str, rows: dict[int, float | int]) -> None:
    # Vorherige Werte des Tages für diese Metrik verwerfen: ein Mandant, der beim Neuberechnen
    # keinen Wert mehr hat (z. B. Datensatz gelöscht), darf keine alte Zahl behalten.
    db.execute(text("DELETE FROM tenant_metric_daily WHERE day = :day AND metric = :metric"), {"day": day, "metric": metric})
    for tenant_id, value in rows.items():
        db.execute(
            text(
                "INSERT INTO tenant_metric_daily (tenant_id, day, metric, value, computed_at) "
                "VALUES (:tenant_id, :day, :metric, :value, now()) "
                "ON CONFLICT (tenant_id, day, metric) DO UPDATE SET value = EXCLUDED.value, computed_at = now()"
            ),
            {"tenant_id": tenant_id, "day": day, "metric": metric, "value": value},
        )


def _scalar(db: Session, sql: str, params: dict) -> int:
    return int(db.execute(text(sql), params).scalar() or 0)


def _per_tenant(db: Session, sql: str, params: dict) -> dict[int, int]:
    return {int(tenant_id): int(value) for tenant_id, value in db.execute(text(sql), params).all() if tenant_id is not None and value}


def compute_day(db: Session, day: date, *, snapshot: bool) -> None:
    """Rechnet einen Tag (idempotent). ``snapshot`` ergänzt die Momentaufnahmen (Speicher,
    Feature-Buchungen, MRR) - nur für den jüngsten Tag sinnvoll, nie im Backfill."""
    start, end = _bounds(day)
    window_start = end - timedelta(days=30)
    params = {"start": start, "end": end, "window_start": window_start}
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))  # sql-ok: feste Konstante

    # Gelöschte Mandanten/Benutzer fehlen rückwirkend (kein Abgangsverlauf vor Einführung) - ab
    # Einführung hält der tägliche Wert den damaligen Stand fest.
    _upsert_platform(db, day, "tenants.total", _scalar(db, "SELECT count(*) FROM tenant WHERE created_at < :end", params))
    _upsert_platform(db, day, "tenants.new", _scalar(db, "SELECT count(*) FROM tenant WHERE created_at >= :start AND created_at < :end", params))
    _upsert_platform(db, day, "users.total", _scalar(db, "SELECT count(*) FROM app_user WHERE created_at < :end", params))
    _upsert_platform(
        db, day, "users.active_30d",
        _scalar(
            db,
            "SELECT count(DISTINCT actor_user_id) FROM audit_log "
            "WHERE action = 'user.login' AND created_at >= :window_start AND created_at < :end AND actor_user_id IS NOT NULL",
            params,
        ),
    )
    _upsert_platform(
        db, day, "logins.success",
        _scalar(db, "SELECT count(*) FROM audit_log WHERE action IN ('user.login', 'admin.login') AND created_at >= :start AND created_at < :end", params),
    )
    _upsert_platform(
        db, day, "logins.failure",
        _scalar(
            db,
            "SELECT count(*) FROM audit_log WHERE action = ANY(:actions) AND created_at >= :start AND created_at < :end",
            {**params, "actions": list(LOGIN_FAILURE_ACTIONS)},
        ),
    )
    _upsert_platform(db, day, "errors.total", _scalar(db, "SELECT count(*) FROM system_error_log WHERE created_at >= :start AND created_at < :end", params))

    # Je Mandant: nur Zählwerte.
    _upsert_tenant_rows(
        db, day, "logins",
        _per_tenant(
            db,
            "SELECT tenant_id, count(*) FROM audit_log WHERE action = 'user.login' AND created_at >= :start AND created_at < :end GROUP BY tenant_id",
            params,
        ),
    )
    _upsert_tenant_rows(
        db, day, "users.active",
        _per_tenant(
            db,
            "SELECT tenant_id, count(DISTINCT actor_user_id) FROM audit_log "
            "WHERE action = 'user.login' AND created_at >= :window_start AND created_at < :end AND actor_user_id IS NOT NULL GROUP BY tenant_id",
            params,
        ),
    )
    for metric, table in USAGE_TABLES.items():
        _upsert_tenant_rows(
            db, day, metric,
            _per_tenant(
                db,
                f"SELECT tenant_id, count(*) FROM {table} WHERE created_at >= :start AND created_at < :end GROUP BY tenant_id",  # sql-ok: Tabellenname aus fester Liste USAGE_TABLES
                params,
            ),
        )

    if snapshot:
        _compute_snapshots(db, day)
    db.commit()


def _compute_snapshots(db: Session, day: date) -> None:
    from app.services.storage_service import StorageService

    totals = StorageService().total_bytes_by_tenant(db)
    _upsert_tenant_rows(db, day, "storage.bytes", {tenant_id: value for tenant_id, value in totals.items() if value})
    _upsert_platform(db, day, "storage.bytes_total", sum(totals.values()))

    db.execute(text("DELETE FROM platform_metric_daily WHERE day = :day AND metric = 'feature.booked'"), {"day": day})
    for code, count in db.execute(
        text("SELECT feature_code, count(*) FROM tenant_feature WHERE access = 'full' GROUP BY feature_code")
    ).all():
        _upsert_platform(db, day, "feature.booked", int(count), dimension=str(code))

    # MRR (Run-Rate der laufenden Abos) aus dem Cashflow - Fehler dort dürfen den restlichen
    # Rollup nicht verhindern, landen aber im Fehlerprotokoll.
    try:
        from app.services import cashflow_service

        with db.begin_nested():
            overview = cashflow_service.overview(db)
        _upsert_platform(db, day, "mrr_rp", int(overview.run_rate.income_rp))
    except Exception as exc:
        record_system_error(db, exc=exc)


def run_job(db: Session, *, today: date | None = None) -> dict:
    """Task des Loops ``metrics_rollup``: fehlende Tage bis gestern rechnen.

    Erster Lauf (Tabelle leer): Backfill der letzten BACKFILL_DAYS Tage. Danach je Lauf nur Tage,
    für die noch keine Zeile existiert (in der Regel genau gestern). Der Loop tickt stündlich;
    ein bereits gerechneter Tag kostet nur eine Abfrage."""
    today = today or today_local()
    yesterday = today - timedelta(days=1)
    latest = db.execute(text("SELECT max(day) FROM platform_metric_daily WHERE metric = 'tenants.total'")).scalar()
    if latest is None:
        days = [yesterday - timedelta(days=offset) for offset in range(BACKFILL_DAYS - 1, -1, -1)]
    elif latest >= yesterday:
        return {"computed": 0}
    else:
        gap = min((yesterday - latest).days, BACKFILL_DAYS)
        days = [yesterday - timedelta(days=offset) for offset in range(gap - 1, -1, -1)]
    for day in days:
        compute_day(db, day, snapshot=day == yesterday)
    return {"computed": len(days), "from": days[0].isoformat(), "to": days[-1].isoformat()}


# --- Ressourcen-Stichproben (system_monitor) --------------------------------------------------

# Etwa alle 5 Minuten eine Stichprobe (der Monitor tickt alle 30 s, auf wechselnden Workern - darum
# zeitbasiert über den letzten Eintrag statt über einen Tick-Zähler je Prozess).
SAMPLE_INTERVAL_SECONDS = 5 * 60 - 15
SAMPLE_RETENTION_DAYS = 14


def _number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def samples_from_snapshot(snapshot) -> list[tuple[str, str, float]]:
    """(metric, subject, value) aus einem SystemHealthSnapshot - nur Zahlen, die der Snapshot
    ohnehin enthält; fehlende Werte werden übersprungen."""
    wanted = {
        ("postgres", "latencyMs"): "postgres.latency_ms",
        ("postgres", "connections"): "postgres.connections",
        ("postgres", "sizeMb"): "postgres.size_mb",
        ("redis", "latencyMs"): "redis.latency_ms",
        ("redis", "usedMb"): "redis.used_mb",
        ("runtime", "maxLagMs"): "runtime.loop_lag_ms",
        ("runtime", "poolPeakPercent"): "runtime.pool_peak_percent",
    }
    samples: list[tuple[str, str, float]] = []
    for check in snapshot.checks:
        for (key, param), metric in wanted.items():
            if check.key == key:
                value = _number(check.params.get(param))
                if value is not None:
                    samples.append((metric, "", value))
    for container in snapshot.containers:
        subject = (container.service or container.name or "")[:80]
        if container.cpu_percent is not None:
            samples.append(("container.cpu_percent", subject, float(container.cpu_percent)))
        if container.memory_bytes is not None:
            samples.append(("container.memory_mb", subject, round(container.memory_bytes / 1024 / 1024, 1)))
    return samples


def write_samples(db: Session, snapshot) -> int:
    samples = samples_from_snapshot(snapshot)
    for metric, subject, value in samples:
        db.execute(
            text("INSERT INTO system_metric_sample (ts, metric, subject, value) VALUES (:ts, :metric, :subject, :value)"),
            {"ts": snapshot.collected_at, "metric": metric, "subject": subject, "value": value},
        )
    db.commit()
    return len(samples)


def maybe_write_samples(db: Session, snapshot) -> None:
    """Vom system_monitor-Tick aufgerufen: schreibt höchstens alle ~5 min eine Stichprobe. Fehler
    dürfen den Monitor-Tick nie stoppen, landen aber im Fehlerprotokoll."""
    try:
        due = db.execute(
            text("SELECT NOT EXISTS (SELECT 1 FROM system_metric_sample WHERE ts > now() - make_interval(secs => :secs))"),
            {"secs": SAMPLE_INTERVAL_SECONDS},
        ).scalar()
        if due:
            write_samples(db, snapshot)
    except Exception as exc:
        db.rollback()
        record_system_error(db, exc=exc)


def cleanup_samples(db: Session, *, retention_days: int = SAMPLE_RETENTION_DAYS) -> dict:
    deleted = db.execute(
        text("DELETE FROM system_metric_sample WHERE ts < now() - make_interval(days => :days)"), {"days": retention_days}
    ).rowcount
    db.commit()
    return {"deleted": deleted or 0}
