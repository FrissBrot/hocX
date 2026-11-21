"""Plattform-Admin: Analysen (Admin-Redesign Phase D).

Liest ausschliesslich die Rollup-Tabellen (``platform_metric_daily``, ``tenant_metric_daily``) und die
Ressourcen-Stichproben (``system_metric_sample``) aus Migration 0208 - nie Live-Abfragen über
Fachtabellen. Alle Werte sind Zählwerte ohne Personendaten.

Rechte: Wachstum, Features, Umsatz, Auslastung und Speicher sieht jeder Plattform-Admin (wie
Mandantenliste, Katalog und Cashflow). Nutzung (Anmeldungen) und Fehler kommen aus O-Quellen
(audit_log, system_error_log) und sind nur für ``owner`` (require_admin_owner).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner
from app.core.db import get_db
from app.services.metrics_rollup_service import today_local

router = APIRouter(dependencies=[Depends(get_current_admin)])

Range = Literal["30d", "90d", "12m"]
PublicSeries = Literal["growth", "features", "revenue", "load", "storage"]

RANGE_DAYS = {"30d": 30, "90d": 90, "12m": 365}

# Bestandswerte (Stand am Tag) werden im Monatsraster mit dem letzten Wert verdichtet, Ereignis-
# zählungen summiert.
GAUGE_METRICS = {"tenants.total", "users.total", "users.active_30d", "storage.bytes_total", "mrr_rp"}

SERIES_METRICS: dict[str, tuple[str, ...]] = {
    "growth": ("tenants.total", "tenants.new", "users.total"),
    "usage": ("users.active_30d", "logins.success", "logins.failure"),
    "revenue": ("mrr_rp",),
    "storage": ("storage.bytes_total",),
    "errors": ("errors.total",),
}

LOAD_METRICS = ("postgres.latency_ms", "postgres.connections", "postgres.size_mb", "redis.used_mb", "runtime.loop_lag_ms")


def _range_start(range_: str, today: date) -> date:
    return today - timedelta(days=RANGE_DAYS[range_])


def _collecting_since(db: Session, metrics: tuple[str, ...]) -> date | None:
    return db.execute(
        text("SELECT min(day) FROM platform_metric_daily WHERE metric = ANY(:metrics)"), {"metrics": list(metrics)}
    ).scalar()


def _daily_points(db: Session, metrics: tuple[str, ...], range_: str) -> list[dict]:
    start = _range_start(range_, today_local())
    rows = db.execute(
        text(
            "SELECT day, metric, value FROM platform_metric_daily "
            "WHERE metric = ANY(:metrics) AND dimension = '' AND day >= :start ORDER BY day"
        ),
        {"metrics": list(metrics), "start": start},
    ).all()
    by_day: dict[date, dict[str, float]] = {}
    for day, metric, value in rows:
        by_day.setdefault(day, {})[metric] = float(value)
    if range_ != "12m":
        return [{"bucket": day.isoformat(), "values": values} for day, values in sorted(by_day.items())]
    # 12 Monate: Monatsraster (Bestand = letzter Tag des Monats, Ereignisse = Summe).
    months: dict[str, dict[str, float]] = {}
    for day, values in sorted(by_day.items()):
        bucket = months.setdefault(day.strftime("%Y-%m"), {})
        for metric, value in values.items():
            bucket[metric] = value if metric in GAUGE_METRICS else bucket.get(metric, 0.0) + value
    return [{"bucket": month, "values": values} for month, values in months.items()]


def _series_response(db: Session, series: str, range_: str) -> dict:
    metrics = SERIES_METRICS[series]
    return {
        "series": series,
        "range": range_,
        "bucket": "month" if range_ == "12m" else "day",
        "metrics": list(metrics),
        "collecting_since": _collecting_since(db, metrics),
        "points": _daily_points(db, metrics, range_),
    }


@router.get("/analytics/usage")
def analytics_usage(range_: Range = Query("30d", alias="range"), db: Session = Depends(get_db), _: CurrentAdmin = Depends(require_admin_owner)):
    return _series_response(db, "usage", range_)


@router.get("/analytics/errors")
def analytics_errors(range_: Range = Query("30d", alias="range"), db: Session = Depends(get_db), _: CurrentAdmin = Depends(require_admin_owner)):
    return _series_response(db, "errors", range_)


@router.get("/analytics/{series}")
def analytics_series(series: PublicSeries, range_: Range = Query("30d", alias="range"), db: Session = Depends(get_db)):
    if series == "features":
        return _features(db, range_)
    if series == "load":
        return _load(db, range_)
    response = _series_response(db, series, range_)
    if series == "storage":
        response["top_tenants"] = _top_storage_tenants(db)
    return response


def _features(db: Session, range_: str) -> dict:
    latest = db.execute(text("SELECT max(day) FROM platform_metric_daily WHERE metric = 'feature.booked'")).scalar()
    items: list[dict] = []
    tenants_total = 0.0
    if latest is not None:
        tenants_total = float(
            db.execute(
                text("SELECT value FROM platform_metric_daily WHERE day = :day AND metric = 'tenants.total' AND dimension = ''"), {"day": latest}
            ).scalar()
            or 0
        )
        for code, value in db.execute(
            text("SELECT dimension, value FROM platform_metric_daily WHERE day = :day AND metric = 'feature.booked' ORDER BY value DESC, dimension"),
            {"day": latest},
        ).all():
            items.append({"code": code, "tenants": float(value), "share": float(value) / tenants_total if tenants_total else None})
    return {
        "series": "features",
        "range": range_,
        "collecting_since": _collecting_since(db, ("feature.booked",)),
        "as_of": latest,
        "tenants_total": tenants_total,
        "items": items,
    }


def _load(db: Session, range_: str) -> dict:
    # Stichproben werden 14 Tage aufbewahrt - längere Zeiträume zeigen ehrlich nur diese.
    start = _range_start(range_, today_local())
    rows = db.execute(
        text(
            "SELECT (ts AT TIME ZONE 'Europe/Zurich')::date AS day, metric, avg(value), max(value) FROM system_metric_sample "
            "WHERE metric = ANY(:metrics) AND subject = '' AND ts >= :start GROUP BY 1, 2 ORDER BY 1"
        ),
        {"metrics": list(LOAD_METRICS), "start": start},
    ).all()
    by_day: dict[date, dict[str, float]] = {}
    for day, metric, avg_value, max_value in rows:
        values = by_day.setdefault(day, {})
        values[f"{metric}.avg"] = round(float(avg_value), 2)
        values[f"{metric}.max"] = round(float(max_value), 2)
    first = db.execute(text("SELECT min(ts) FROM system_metric_sample")).scalar()
    return {
        "series": "load",
        "range": range_,
        "bucket": "day",
        "metrics": list(LOAD_METRICS),
        "collecting_since": first.date() if first else None,
        "points": [{"bucket": day.isoformat(), "values": values} for day, values in sorted(by_day.items())],
    }


def _top_storage_tenants(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT t.public_id, t.name, m.value FROM tenant_metric_daily m JOIN tenant t ON t.id = m.tenant_id "
            "WHERE m.metric = 'storage.bytes' AND m.day = (SELECT max(day) FROM tenant_metric_daily WHERE metric = 'storage.bytes') "
            "ORDER BY m.value DESC LIMIT 10"
        )
    ).all()
    return [{"tenant_id": str(public_id), "name": name, "bytes": int(value)} for public_id, name, value in rows]
