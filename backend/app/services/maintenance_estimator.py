"""MaintenanceEstimator: konservative Dauerabschätzung für Wartungsfenster.

Grundformel für Storage-Migrationen:

    Kopierdauer = verbleibende Bytes / konservative effektive Rate
                  + verbleibende Objekte × Overhead pro Objekt / Parallelität
    Basis       = Initialisierung + Kopierdauer + Verifikation + Cutover + Healthchecks
    Spanne      = [Basis, Basis + Sicherheitsreserve]

Die Rate ist das Minimum aus aktueller Messung, Durchschnitt seit Beginn und - bei mindestens
drei Vergleichsläufen - dem 10.-Perzentil historischer Raten, zusätzlich abgewertet
(estimator_rate_derating). Die Reserve ergibt sich bei ausreichender Historie aus dem
90.-Perzentil des Verhältnisses tatsächliche/geschätzte Dauer früherer Wartungen, sonst aus einem
festen Faktor und einer Mindestreserve. Ohne seriöse Grundlage (z. B. vor der Inventur) liefert
die Schätzung None - die Oberfläche zeigt dann "Die voraussichtliche Dauer wird ermittelt".

Die Schätzung entscheidet nie über die Freigabe; die hängt allein an den Bedingungen im
maintenance_service.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MaintenanceWindow, StorageChangeOutbox, StorageMigration, StorageProfile

MIN_HISTORY_SAMPLES = 3


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("leere Liste")
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _is_local(profile: StorageProfile | None) -> bool:
    return profile is None or profile.provider in ("filesystem", "garage_local")


def measured_rates(migration: StorageMigration) -> tuple[float | None, float | None]:
    """(aktuelle Rate der letzten ~5 Minuten, Durchschnitt seit Kopierbeginn) in Bytes/s."""
    samples = [sample for sample in (migration.throughput or []) if "t" in sample and "bytes" in sample]
    if len(samples) < 2:
        return None, None
    first, last = samples[0], samples[-1]
    elapsed = float(last["t"]) - float(first["t"])
    average = (float(last["bytes"]) - float(first["bytes"])) / elapsed if elapsed > 0 else None
    window_start = next((sample for sample in samples if float(last["t"]) - float(sample["t"]) <= 300), samples[-2])
    recent_elapsed = float(last["t"]) - float(window_start["t"])
    current = (float(last["bytes"]) - float(window_start["bytes"])) / recent_elapsed if recent_elapsed > 0 else None
    return current, average


def historical_rates(db: Session, *, local: bool) -> list[float]:
    """Effektive Raten abgeschlossener Migrationen gleicher Art (lokal/extern)."""
    rows = db.scalars(
        select(StorageMigration).where(StorageMigration.state == "completed").order_by(StorageMigration.finished_at.desc()).limit(20)
    ).all()
    rates: list[float] = []
    for row in rows:
        target = db.get(StorageProfile, row.target_profile_id)
        if _is_local(target) != local:
            continue
        copy_seconds = (row.checkpoint or {}).get("copy_seconds")
        if copy_seconds and row.copied_bytes and copy_seconds > 0:
            rates.append(row.copied_bytes / copy_seconds)
    return rates


def historical_overrun_ratios(db: Session, reason_code: str | None = None) -> list[float]:
    """Verhältnis tatsächliche/ursprünglich geschätzte Dauer abgeschlossener Wartungen."""
    query = select(MaintenanceWindow).where(
        MaintenanceWindow.state == "completed",
        MaintenanceWindow.started_at.is_not(None),
        MaintenanceWindow.ended_at.is_not(None),
        MaintenanceWindow.original_estimated_end_at.is_not(None),
    )
    if reason_code is not None:
        query = query.where(MaintenanceWindow.reason_code == reason_code)
    ratios: list[float] = []
    for window in db.scalars(query.order_by(MaintenanceWindow.ended_at.desc()).limit(30)).all():
        estimated = (window.original_estimated_end_at - window.started_at).total_seconds()
        actual = (window.ended_at - window.started_at).total_seconds()
        if estimated > 0 and actual > 0:
            ratios.append(actual / estimated)
    return ratios


def conservative_rate(db: Session, migration: StorageMigration, target: StorageProfile | None) -> tuple[float, str]:
    local = _is_local(target)
    candidates: list[tuple[float, str]] = []
    current, average = measured_rates(migration)
    if current:
        candidates.append((current, "current"))
    if average:
        candidates.append((average, "average"))
    history = historical_rates(db, local=local)
    if len(history) >= MIN_HISTORY_SAMPLES:
        candidates.append((_percentile(history, 0.1), "history_p10"))
    if not candidates:
        default = settings.estimator_default_rate_local_bps if local else settings.estimator_default_rate_external_bps
        candidates.append((float(default), "default"))
    rate, basis = min(candidates, key=lambda item: item[0])
    return max(rate * settings.estimator_rate_derating, 64 * 1024.0), basis


def _reserve(db: Session, base_seconds: float, *, reason_code: str, min_reserve: int) -> tuple[int, str]:
    ratios = historical_overrun_ratios(db, reason_code)
    if len(ratios) >= MIN_HISTORY_SAMPLES:
        factor = max(_percentile(ratios, 0.9) - 1.0, 0.1)
        return int(max(min_reserve, base_seconds * factor)), "history_p90"
    return int(max(min_reserve, base_seconds * settings.estimator_safety_factor)), "factor"


def estimate_storage_migration(db: Session, migration: StorageMigration, *, scope: str = "full") -> dict[str, Any] | None:
    """scope="full": verbleibende Gesamtdauer (Erstmigration in voller Wartung).
    scope="cutover": nur die tatsächliche Unterbrechung beim Cutover (Journal nachziehen,
    Endprüfung, Umschalten) - nicht die vorausgehende Kopierdauer."""
    target = db.get(StorageProfile, migration.target_profile_id)
    rate, rate_basis = conservative_rate(db, migration, target)
    per_object = settings.estimator_per_object_seconds_local if _is_local(target) else settings.estimator_per_object_seconds_external
    parallelism = max(1, int((migration.options or {}).get("parallelism", 4)))
    full_verify = (migration.options or {}).get("verify_mode", "full") == "full"

    if scope == "cutover":
        pending_changes = db.scalar(
            select(StorageChangeOutbox.seq).order_by(StorageChangeOutbox.seq.desc()).limit(1)
        ) or 0
        lag = max(0, pending_changes - (migration.applied_outbox_seq or 0))
        # Pro nachzuziehender Änderung grosszügig 5 MB plus Objekt-Overhead (Kopie + Prüfung).
        changes_seconds = lag * (per_object * 2 + (5 * 1024 * 1024) / rate)
        components = {
            "changes": int(changes_seconds),
            "cutover": settings.estimator_cutover_seconds,
            "healthcheck": settings.estimator_healthcheck_seconds,
        }
        base = sum(components.values())
        reserve, reserve_basis = _reserve(db, base, reason_code="storage_cutover", min_reserve=settings.estimator_cutover_min_reserve_seconds)
        return _result(base, reserve, components, rate, rate_basis, reserve_basis, scope)

    preflight = (migration.checkpoint or {}).get("preflight_inventory") or {}
    total_objects = migration.total_objects or int(preflight.get("objects") or 0)
    total_bytes = migration.total_bytes or int(preflight.get("bytes") or 0)
    if total_objects == 0 and not preflight:
        return None  # keine seriöse Grundlage - "wird ermittelt"
    remaining_bytes = max(0, total_bytes - (migration.copied_bytes or 0))
    remaining_objects = max(0, total_objects - (migration.copied_objects or 0))
    unverified_objects = max(0, total_objects - (migration.verified_objects or 0))
    verify_bytes = (total_bytes * unverified_objects / total_objects) if total_objects else 0
    components = {
        "init": settings.estimator_init_seconds if migration.state in ("pending", "preflight", "awaiting_confirmation", "inventory") else 0,
        "copy": int(remaining_bytes / rate + remaining_objects * per_object / parallelism),
        "verify": int((verify_bytes / rate if full_verify else 0) + unverified_objects * per_object / parallelism),
        "cutover": settings.estimator_cutover_seconds,
        "healthcheck": settings.estimator_healthcheck_seconds,
    }
    base = sum(components.values())
    reserve, reserve_basis = _reserve(db, base, reason_code=f"storage_{migration.kind}_migration", min_reserve=settings.estimator_min_reserve_seconds)
    return _result(base, reserve, components, rate, rate_basis, reserve_basis, scope)


def _result(base: float, reserve: int, components: dict[str, int], rate: float, rate_basis: str, reserve_basis: str, scope: str) -> dict[str, Any]:
    confidence = "high" if rate_basis.startswith("history") and reserve_basis == "history_p90" else ("medium" if rate_basis in ("current", "average") else "low")
    return {
        "scope": scope,
        "remaining_low_seconds": int(base),
        "remaining_high_seconds": int(base + reserve),
        "safety_margin_seconds": int(reserve),
        "components": components,
        "rate_bytes_per_second": int(rate),
        "rate_basis": rate_basis,
        "reserve_basis": reserve_basis,
        "confidence": confidence,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def estimate_for_window(db: Session, window: MaintenanceWindow) -> dict[str, Any] | None:
    """Laufende Neuschätzung für jobgebundene Fenster (vom maintenance_supervisor aufgerufen)."""
    if window.source_job_type in ("storage_initial_migration", "storage_cutover") and window.source_job_id:
        import uuid

        migration = db.get(StorageMigration, uuid.UUID(window.source_job_id))
        if migration is None:
            return None
        scope = "cutover" if window.source_job_type == "storage_cutover" else "full"
        return estimate_storage_migration(db, migration, scope=scope)
    return None
