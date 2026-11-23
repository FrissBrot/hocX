"""Abfragen der Ereignisseite im Sicherheitsbereich (1.6, Design «hocX Sicherheit Ereignisse»).

- Zeitraum ist Pflicht (höchstens 14 Tage, ``RANGES``); jede Abfrage nutzt damit den Zeitindex.
- Pseudonym-Filter (Konto, Netz, Gerät) sind Präfixe der gekürzten Anzeige (4-32 Hex-Zeichen). Als
  Bereich ``>= p AND < p || 'g'`` (Pseudonyme bestehen nur aus 0-9a-f, damit unabhängig von der
  Sortierfolge der Datenbank) plus ``left(..) = p`` - Konto und Netz haben je einen Index
  (subject_hash, ts) bzw. (src_net_hash, ts), Gerät nur über den Zeitraum.
- Liste mit Keyset-Pagination (ts, id) statt OFFSET; Histogramm und Gruppen 30 s im Prozess
  zwischengespeichert.
- Ausgaben nur mit gekürzten Pseudonymen, nie Adressen. Gewichte der Risikogründe stehen ab 1.6
  in ``details.weights`` - ältere Ereignisse haben nur die Gründe.

Alle SQL-Teile sind feste Fragmente aus diesem Modul; Werte gehen nur als gebundene Parameter.
"""
from __future__ import annotations

import base64
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_security.events import EVENT_TYPES, OUTCOMES

RANGES: dict[str, timedelta] = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "14d": timedelta(days=14)}
HISTOGRAM_BUCKETS = 48
GROUP_LIMIT = 50
SHORT = 12
_CACHE_SECONDS = 30
_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class EventFilter:
    range: str = "24h"
    subject: str | None = None
    net: str | None = None
    device: str | None = None
    country: str | None = None
    event_type: str | None = None
    outcome: str | None = None
    tenant_id: int | None = None   # intern, aus der öffentlichen ID aufgelöst

    def key(self) -> tuple:
        return (self.range, self.subject, self.net, self.device, self.country, self.event_type, self.outcome, self.tenant_id)

    def window(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        end = now or datetime.now(UTC)
        return end - RANGES[self.range], end


def validate(event_filter: EventFilter) -> None:
    """ValueError bei ungültigen Werten (die Route gibt 422)."""
    if event_filter.range not in RANGES:
        raise ValueError("Zeitraum ungültig")
    for value in (event_filter.subject, event_filter.net, event_filter.device):
        if value is not None and not (4 <= len(value) <= 32 and all(ch in "0123456789abcdef" for ch in value)):
            raise ValueError("Pseudonym ungültig")
    if event_filter.country is not None and not (len(event_filter.country) == 2 and event_filter.country.isalpha() and event_filter.country.isupper()):
        raise ValueError("Land ungültig")
    if event_filter.event_type is not None and event_filter.event_type not in EVENT_TYPES:
        raise ValueError("Ereignistyp ungültig")
    if event_filter.outcome is not None and event_filter.outcome not in OUTCOMES:
        raise ValueError("Ergebnis ungültig")


_PREFIX_SQL = {
    # feste Spaltennamen je Filter
    "subject": "e.subject_hash >= :subject AND e.subject_hash < :subject_hi AND left(e.subject_hash, :subject_len) = :subject",
    "net": "e.src_net_hash >= :net AND e.src_net_hash < :net_hi AND left(e.src_net_hash, :net_len) = :net",
    "device": "e.device_hash >= :device AND e.device_hash < :device_hi AND left(e.device_hash, :device_len) = :device",
}


def _where(event_filter: EventFilter, start: datetime, end: datetime, *, with_outcome: bool = True) -> tuple[str, dict]:
    conditions = ["e.ts >= :start", "e.ts < :end"]
    params: dict = {"start": start, "end": end}
    for name in ("subject", "net", "device"):
        value = getattr(event_filter, name)
        if value:
            conditions.append(_PREFIX_SQL[name])
            params.update({name: value, f"{name}_hi": value + "g", f"{name}_len": len(value)})
    if event_filter.country:
        conditions.append("e.src_country = :country")
        params["country"] = event_filter.country
    if event_filter.event_type:
        conditions.append("e.event_type = :event_type")
        params["event_type"] = event_filter.event_type
    if event_filter.tenant_id is not None:
        conditions.append("e.tenant_id = :tenant_id")
        params["tenant_id"] = event_filter.tenant_id
    if with_outcome and event_filter.outcome:
        conditions.append("e.outcome = :outcome")
        params["outcome"] = event_filter.outcome
    return " WHERE " + " AND ".join(conditions), params


def _cached(key: tuple, compute):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_SECONDS:
            return hit[1]
    value = compute()
    with _cache_lock:
        if len(_cache) > 256:
            _cache.clear()
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _short(value: str | None) -> str | None:
    return value[:SHORT] if value else None


# ── Liste (Keyset) ──────────────────────────────────────────────────────────────────────────


def encode_cursor(ts: datetime, row_id: int) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{row_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, row_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts), int(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Cursor ungültig") from exc


_LIST_SELECT = (
    "SELECT e.id, e.event_id, e.ts, e.event_type, e.outcome, e.actor_kind, e.platform_admin_id, t.public_id AS tenant_id, "
    "t.name AS tenant_name, e.subject_hash, e.src_net_hash, e.device_hash, e.src_country, e.risk_score, e.risk_reasons, "
    "e.enforcement, e.user_agent_family FROM auth_event e LEFT JOIN tenant t ON t.id = e.tenant_id"
)


def _row(row) -> dict:
    return {
        "event_id": row["event_id"], "ts": row["ts"], "event_type": row["event_type"], "outcome": row["outcome"],
        "actor_kind": row["actor_kind"], "platform_admin_id": row["platform_admin_id"], "tenant_id": row["tenant_id"],
        "tenant_name": row["tenant_name"], "subject_hash": _short(row["subject_hash"]), "src_net_hash": _short(row["src_net_hash"]),
        "device_hash": _short(row["device_hash"]), "src_country": row["src_country"], "risk_score": row["risk_score"],
        "risk_reasons": list(row["risk_reasons"] or []), "enforcement": row["enforcement"], "user_agent_family": row["user_agent_family"],
    }


def list_events(db: Session, event_filter: EventFilter, *, cursor: str | None = None, limit: int = 50) -> dict:
    start, end = event_filter.window()
    where, params = _where(event_filter, start, end)
    if cursor:
        cursor_ts, cursor_id = decode_cursor(cursor)
        where += " AND (e.ts, e.id) < (:cursor_ts, :cursor_id)"
        params.update(cursor_ts=cursor_ts, cursor_id=cursor_id)
    params["limit"] = limit + 1
    rows = db.execute(text(_LIST_SELECT + where + " ORDER BY e.ts DESC, e.id DESC LIMIT :limit"), params).mappings().all()  # sql-ok: feste Fragmente, Werte gebunden
    items = [_row(row) for row in rows[:limit]]
    next_cursor = encode_cursor(rows[limit - 1]["ts"], rows[limit - 1]["id"]) if len(rows) > limit else None
    return {"items": items, "next_cursor": next_cursor, "start": start, "end": end}


# ── Histogramm und Ergebnis-Zähler ─────────────────────────────────────────────────────────


def histogram(db: Session, event_filter: EventFilter) -> dict:
    """48 Abschnitte über den Zeitraum, je Ergebnis; ``outcome_counts`` ohne den Ergebnis-Filter
    (Zähler der Ergebnis-Reiter)."""

    def compute() -> dict:
        start, end = event_filter.window()
        where, params = _where(event_filter, start, end, with_outcome=False)
        width = (end - start).total_seconds() / HISTOGRAM_BUCKETS
        params.update(bucket_start=start, width=width, buckets=HISTOGRAM_BUCKETS)
        buckets = [
            {"start": start + timedelta(seconds=width * index), "success": 0, "failure": 0, "blocked": 0, "challenged": 0, "info": 0}
            for index in range(HISTOGRAM_BUCKETS)
        ]
        counts = dict.fromkeys(OUTCOMES, 0)
        for index, outcome, count in db.execute(
            text(  # sql-ok: feste Fragmente, Werte gebunden
                "SELECT LEAST(:buckets - 1, floor(extract(epoch FROM (e.ts - CAST(:bucket_start AS timestamptz))) / :width))::int, e.outcome, count(*) "
                "FROM auth_event e" + where + " GROUP BY 1, 2"
            ),
            params,
        ):
            counts[outcome] = counts.get(outcome, 0) + int(count)
            if event_filter.outcome and outcome != event_filter.outcome:
                continue
            if 0 <= index < HISTOGRAM_BUCKETS:
                buckets[index][outcome] += int(count)
        return {"start": start, "end": end, "bucket_seconds": int(width), "buckets": buckets, "outcome_counts": counts, "total": sum(counts.values())}

    return _cached(("histogram", *event_filter.key()), compute)


# ── Gruppen (Nach Netz / Nach Konto) ───────────────────────────────────────────────────────

_GROUP_SQL = {
    "net": ("e.src_net_hash", "e.subject_hash"),
    "subject": ("e.subject_hash", "e.src_net_hash"),
}


def groups(db: Session, event_filter: EventFilter, by: str) -> list[dict]:
    if by not in _GROUP_SQL:
        raise ValueError("Gruppierung ungültig")
    key_column, other_column = _GROUP_SQL[by]

    def compute() -> list[dict]:
        start, end = event_filter.window()
        where, params = _where(event_filter, start, end)
        params["limit"] = GROUP_LIMIT
        rows = db.execute(
            text(  # sql-ok: Spaltennamen aus _GROUP_SQL (fest), Werte gebunden
                f"SELECT {key_column} AS key, count(*) AS events, "
                "count(*) FILTER (WHERE e.outcome = 'failure') AS failure, count(*) FILTER (WHERE e.outcome = 'blocked') AS blocked, "
                "count(*) FILTER (WHERE e.outcome = 'challenged') AS challenged, count(*) FILTER (WHERE e.outcome = 'success') AS success, "
                f"count(DISTINCT {other_column}) AS distinct_other, count(DISTINCT e.tenant_id) AS tenants, max(e.risk_score) AS max_risk, "
                "max(e.ts) AS last_at, mode() WITHIN GROUP (ORDER BY e.src_country) AS country, "
                "(SELECT t.name FROM tenant t WHERE t.id = min(e.tenant_id)) AS tenant_name "
                f"FROM auth_event e{where} AND {key_column} IS NOT NULL GROUP BY {key_column} ORDER BY events DESC, last_at DESC LIMIT :limit"
            ),
            params,
        ).mappings()
        return [{**dict(row), "key": _short(row["key"])} for row in rows]

    return _cached(("groups", by, *event_filter.key()), compute)


# ── Einzelnes Ereignis ─────────────────────────────────────────────────────────────────────

RELATED_WINDOW = timedelta(hours=24)


def event_detail(db: Session, event_id: uuid.UUID) -> dict | None:
    row = db.execute(
        text(
            "SELECT e.id, e.event_id, e.ts, e.event_type, e.outcome, e.actor_kind, e.platform_admin_id, t.public_id AS tenant_id, "
            "t.name AS tenant_name, e.subject_hash, e.src_net_hash, e.device_hash, e.src_country, e.risk_score, e.risk_reasons, "
            "e.enforcement, e.policy_version, e.endpoint, e.host_kind, e.user_agent_family, e.details "
            "FROM auth_event e LEFT JOIN tenant t ON t.id = e.tenant_id WHERE e.event_id = :id"
        ),
        {"id": event_id},
    ).mappings().first()
    if row is None:
        return None
    details = dict(row["details"] or {})
    weights = details.pop("weights", None) if isinstance(details.get("weights"), dict) else None
    details.pop("weights", None)
    related = {}
    window = {"start": row["ts"] - RELATED_WINDOW, "end": row["ts"] + RELATED_WINDOW}
    for name, column, value in (
        ("net", "src_net_hash", row["src_net_hash"]),
        ("subject", "subject_hash", row["subject_hash"]),
        ("country", "src_country", row["src_country"]),
    ):
        if value:
            related[name] = int(db.execute(
                text(f"SELECT count(*) FROM auth_event WHERE {column} = :value AND ts BETWEEN :start AND :end"),  # sql-ok: Spaltenname aus fester Liste
                {**window, "value": value},
            ).scalar() or 0)
    return {
        **_row(row),
        "policy_version": row["policy_version"], "endpoint": row["endpoint"], "host_kind": row["host_kind"],
        "reasons": [{"code": code, "weight": (weights or {}).get(code)} for code in (row["risk_reasons"] or [])],
        "has_weights": weights is not None,
        "details": details,
        "related": related,
        "related_hours": int(RELATED_WINDOW.total_seconds() // 3600),
        "can_block": bool(row["src_net_hash"]) and row["actor_kind"] != "admin",
    }


def block_subject(db: Session, event_id: uuid.UUID) -> tuple[str | None, str | None]:
    """(voller Netz-Fingerprint, Art des Akteurs) eines Ereignisses für «Quelle sperren»."""
    row = db.execute(text("SELECT src_net_hash, actor_kind FROM auth_event WHERE event_id = :id"), {"id": event_id}).first()
    if row is None:
        raise LookupError(event_id)
    return row.src_net_hash, row.actor_kind
