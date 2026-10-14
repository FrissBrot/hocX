"""Zentrales Wartungssystem (Migration 0114, docs/storage/WARTUNG.md).

Ein Wartungsfenster (maintenance_window) ist genau ein Grund, den Betrieb ganz (kind="full")
oder teilweise (kind="partial", block_scope="writes"/"uploads") zu sperren. Mehrere Fenster
können gleichzeitig blockieren; die Sperre endet erst, wenn kein blockierendes Fenster mehr
besteht. Die Freigabe eines Fensters hängt ausschliesslich an technisch geprüften
Freigabebedingungen (evaluate_release_conditions) - nie an einem Timer oder daran, dass ein Job
"fertig" meldet, und ein fehlgeschlagenes Fenster (state="failed") blockiert weiter.

Durchgesetzt wird die Sperre serverseitig in app/core/maintenance_middleware.py (Backend) bzw.
abgabebox-backend/app/maintenance.py (Abgabebox) und in run_advisory_locked_loop.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import engine
from app.models import MaintenanceEvent, MaintenanceWindow, StorageMigration, StorageState

_logger = logging.getLogger(__name__)

STATES = ("scheduled", "preparing", "active", "verifying", "completed", "failed", "overdue", "cancelled")
BLOCKING_STATES = ("preparing", "active", "verifying", "failed", "overdue")
TERMINAL_STATES = ("completed", "cancelled")
KINDS = ("full", "partial")
BLOCK_SCOPES = ("all", "writes", "uploads")
FEATURES = ("all", "login", "app", "writes", "uploads", "downloads", "abgabebox", "background_jobs")

# Erlaubte Zustandsübergänge - alles andere ist ein Programmierfehler bzw. ein Doppelklick.
TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"preparing", "cancelled"},
    "preparing": {"active", "failed"},
    "active": {"verifying", "overdue", "failed", "completed"},
    "overdue": {"verifying", "active", "failed", "completed"},
    "verifying": {"active", "overdue", "failed", "completed"},
    # Ein fehlgeschlagenes Fenster wird nur über eine erfolgreiche Wiederaufnahme (active) oder
    # eine geprüfte Freigabe (completed) verlassen.
    "failed": {"active", "verifying", "completed"},
    "completed": set(),
    "cancelled": set(),
}

# Bedingungen, die ein Fenster zur Freigabe erfüllen muss. Die Schlüssel sind fest - ein Job
# kann keine eigene, "immer erfüllte" Bedingung erfinden.
CONDITION_KEYS = ("storage_migration_settled", "storage_not_fenced", "no_open_storage_migration_cutover")


class MaintenanceError(ValueError):
    """Erwarteter, kuratierter Fehler (ValueError-Konvention: nicht im Fehlerlog)."""


@dataclass(frozen=True)
class EffectiveState:
    full_active: bool = False
    writes_blocked: bool = False
    uploads_blocked: bool = False
    estimated_end_at: datetime | None = None
    loaded_at: float = field(default_factory=time.monotonic)

    @property
    def any_blocking(self) -> bool:
        return self.full_active or self.writes_blocked or self.uploads_blocked

    def retry_after_seconds(self) -> int:
        """Retry-After: bis zur geschätzten Fertigstellung, mindestens 30 s, höchstens 15 min -
        der Header ist ein Hinweis für Clients, nie eine Zusage."""
        if self.estimated_end_at is None:
            return 120
        remaining = int((self.estimated_end_at - datetime.now(UTC)).total_seconds())
        return max(30, min(remaining, 900))


# --- Prozess-Cache für Middleware und Hintergrundjobs ------------------------------------------

_cache_lock = threading.Lock()
_cached_state: EffectiveState | None = None


def load_effective_state() -> EffectiveState:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM maintenance_effective_state()")).one()._mapping
    return EffectiveState(
        full_active=bool(row["full_active"]),
        writes_blocked=bool(row["writes_blocked"]),
        uploads_blocked=bool(row["uploads_blocked"]),
        estimated_end_at=row["estimated_end_at"],
    )


def current_effective_state(*, force: bool = False) -> EffectiveState:
    """Kurz gecachter Wartungszustand. Ist die Datenbank nicht erreichbar, gilt der zuletzt
    bekannte Zustand weiter (eine aktive Sperre fällt dadurch nie stillschweigend weg)."""
    global _cached_state
    with _cache_lock:
        cached = _cached_state
    if cached is not None and not force and time.monotonic() - cached.loaded_at < settings.maintenance_cache_seconds:
        return cached
    try:
        state = load_effective_state()
    except Exception:
        _logger.warning("Wartungszustand konnte nicht geladen werden - letzter Stand gilt weiter", exc_info=True)
        return cached or EffectiveState()
    with _cache_lock:
        _cached_state = state
    return state


def invalidate_cache() -> None:
    global _cached_state
    with _cache_lock:
        _cached_state = None


# --- Fenster anlegen und Zustände ändern -------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _event(db: Session, window: MaintenanceWindow, kind: str, *, actor_email: str | None = None,
           from_state: str | None = None, to_state: str | None = None, details: dict | None = None) -> None:
    db.add(MaintenanceEvent(window_id=window.id, kind=kind, actor_email=actor_email, from_state=from_state, to_state=to_state, details=details or {}))


def create_window(
    db: Session,
    *,
    kind: str,
    reason_code: str,
    block_scope: str = "all",
    state: str = "scheduled",
    affected_features: list[str] | None = None,
    public_message: dict[str, str] | None = None,
    internal_note: str | None = None,
    source_job_type: str | None = None,
    source_job_id: str | None = None,
    scheduled_start_at: datetime | None = None,
    scheduled_end_at: datetime | None = None,
    release_conditions: list[dict[str, Any]] | None = None,
    estimate: dict[str, Any] | None = None,
    actor_email: str | None = None,
) -> MaintenanceWindow:
    if kind not in KINDS:
        raise MaintenanceError("Ungültige Wartungsart")
    if block_scope not in BLOCK_SCOPES or (kind == "full" and block_scope != "all"):
        raise MaintenanceError("Ungültiger Sperrumfang")
    if state not in ("scheduled", "preparing"):
        raise MaintenanceError("Neue Wartungsfenster beginnen geplant oder in Vorbereitung")
    for feature in affected_features or []:
        if feature not in FEATURES:
            raise MaintenanceError(f"Unbekannter Funktionsbereich: {feature}")
    for condition in release_conditions or []:
        if condition.get("key") not in CONDITION_KEYS:
            raise MaintenanceError(f"Unbekannte Freigabebedingung: {condition.get('key')}")
    if scheduled_start_at and scheduled_end_at and scheduled_end_at <= scheduled_start_at:
        raise MaintenanceError("Das geplante Ende muss nach dem Beginn liegen")
    window = MaintenanceWindow(
        kind=kind,
        block_scope=block_scope,
        state=state,
        reason_code=reason_code,
        affected_features=affected_features or (["all"] if kind == "full" else []),
        public_message=_clean_messages(public_message),
        internal_note=internal_note,
        source_job_type=source_job_type,
        source_job_id=source_job_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        release_conditions=release_conditions or [],
        created_by_email=actor_email,
        started_at=_now() if state == "preparing" else None,
    )
    db.add(window)
    db.flush()
    if estimate is not None:
        apply_estimate(db, window, estimate)
    _event(db, window, "created", actor_email=actor_email, to_state=state, details={"reason_code": reason_code, "kind": kind})
    db.flush()
    invalidate_cache()
    return window


def _clean_messages(messages: dict[str, str] | None) -> dict[str, str]:
    from app.core.locale_config_generated import SUPPORTED_LOCALES

    cleaned: dict[str, str] = {}
    for locale, message in (messages or {}).items():
        if locale not in SUPPORTED_LOCALES:
            raise MaintenanceError(f"Nicht unterstützte Sprache: {locale}")
        message = (message or "").strip()
        if len(message) > 2000:
            raise MaintenanceError("Wartungsmeldung zu lang (maximal 2000 Zeichen)")
        if message:
            cleaned[locale] = message
    return cleaned


def lock_window(db: Session, window_id: uuid.UUID) -> MaintenanceWindow:
    window = db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.id == window_id).with_for_update()).first()
    if window is None:
        raise MaintenanceError("Wartungsfenster nicht gefunden")
    return window


def transition(db: Session, window: MaintenanceWindow, to_state: str, *, actor_email: str | None = None,
               details: dict | None = None, error: str | None = None) -> MaintenanceWindow:
    """Prüft den Übergang gegen TRANSITIONS. Der Aufrufer hält die Zeile per lock_window()."""
    from_state = window.state
    if to_state == from_state:
        return window
    if to_state not in TRANSITIONS.get(from_state, set()):
        raise MaintenanceError(f"Wartungsfenster kann nicht von '{from_state}' nach '{to_state}' wechseln")
    window.state = to_state
    window.updated_at = _now()
    if to_state == "preparing" and window.started_at is None:
        window.started_at = _now()
    if to_state in TERMINAL_STATES:
        window.ended_at = _now()
    if error is not None:
        window.last_error = error[:4000]
    _event(db, window, "transition", actor_email=actor_email, from_state=from_state, to_state=to_state, details=details)
    db.flush()
    invalidate_cache()
    return window


def apply_estimate(db: Session, window: MaintenanceWindow, estimate: dict[str, Any]) -> None:
    """Übernimmt eine Schätzung des MaintenanceEstimator. Das geschätzte Ende darf sich bei
    Verzögerungen nach hinten verschieben; die ursprüngliche Schätzung bleibt zum Vergleich."""
    window.estimate = estimate
    window.estimate_updated_at = _now()
    remaining_high = estimate.get("remaining_high_seconds")
    if remaining_high is not None:
        window.estimated_end_at = _now() + timedelta(seconds=int(remaining_high))
        if window.original_estimated_end_at is None:
            window.original_estimated_end_at = window.estimated_end_at
    else:
        window.estimated_end_at = None
    window.safety_margin_seconds = estimate.get("safety_margin_seconds")
    db.flush()


def update_progress(db: Session, window_id: uuid.UUID, *, progress: dict[str, Any], estimate: dict[str, Any] | None = None) -> None:
    window = db.get(MaintenanceWindow, window_id)
    if window is None or window.state in TERMINAL_STATES:
        return
    window.progress = progress
    window.updated_at = _now()
    if estimate is not None:
        apply_estimate(db, window, estimate)
    db.flush()


# --- Freigabebedingungen -----------------------------------------------------------------------


@dataclass
class ConditionResult:
    key: str
    satisfied: bool
    reason: str
    params: dict[str, Any] = field(default_factory=dict)


def _evaluate(db: Session, condition: dict[str, Any]) -> ConditionResult:
    key = condition.get("key", "")
    params = condition.get("params") or {}
    storage_state = db.get(StorageState, 1)
    if key == "storage_not_fenced":
        fenced = bool(storage_state and storage_state.write_fenced)
        return ConditionResult(key, not fenced, "fenced" if fenced else "ok", params)
    if key == "no_open_storage_migration_cutover":
        busy = db.scalar(select(StorageMigration.id).where(StorageMigration.state.in_(("cutting_over", "rollback_required"))).limit(1))
        return ConditionResult(key, busy is None, "cutover_open" if busy else "ok", params)
    if key == "storage_migration_settled":
        migration = db.get(StorageMigration, uuid.UUID(str(params.get("migration_id"))))
        if migration is None:
            return ConditionResult(key, False, "migration_missing", params)
        fenced = bool(storage_state and storage_state.write_fenced)
        if migration.state in ("completed", "observing"):
            # Erfolgreicher Wechsel: aktiv ist nachweislich das Ziel, die abschliessende
            # Integritätsprüfung ist bestanden, es gibt kein Fence mehr.
            report = migration.report or {}
            ok = (
                migration.cutover_committed_at is not None
                and bool(report.get("final_integrity_ok"))
                and storage_state is not None
                and storage_state.active_profile_id == migration.target_profile_id
                and storage_state.active_generation == migration.target_generation
                and not fenced
            )
            return ConditionResult(key, ok, "ok" if ok else "integrity_not_confirmed", params)
        if migration.state in ("failed", "cancelled"):
            # Abbruch vor dem Cutover: die Quelle ist weiterhin aktiv und unverändert.
            ok = (
                migration.cutover_committed_at is None
                and storage_state is not None
                and storage_state.active_profile_id == migration.source_profile_id
                and storage_state.active_generation == migration.source_generation
                and not fenced
            )
            return ConditionResult(key, ok, "source_consistent" if ok else "inconsistent", params)
        return ConditionResult(key, False, f"migration_{migration.state}", params)
    return ConditionResult(key, False, "unknown_condition", params)


def evaluate_release_conditions(db: Session, window: MaintenanceWindow) -> list[ConditionResult]:
    conditions = list(window.release_conditions or [])
    # Jede Freigabe setzt zusätzlich voraus, dass kein Cutover offen ist - auch bei manueller
    # Wartung kann ein Administrator so kein Sicherheits-Fence umgehen.
    if not any(condition.get("key") == "no_open_storage_migration_cutover" for condition in conditions):
        conditions.append({"key": "no_open_storage_migration_cutover"})
    return [_evaluate(db, condition) for condition in conditions]


def release(db: Session, window_id: uuid.UUID, *, actor_email: str | None, source: str) -> MaintenanceWindow:
    """Beendet ein Fenster - nur wenn alle Freigabebedingungen erfüllt sind. source: "admin" oder
    "job" (nur für den Verlauf). Der Aufrufer committet."""
    window = lock_window(db, window_id)
    if window.state in TERMINAL_STATES:
        raise MaintenanceError("Wartungsfenster ist bereits beendet")
    if window.state == "scheduled":
        raise MaintenanceError("Ein geplantes Wartungsfenster wird abgesagt, nicht freigegeben")
    results = evaluate_release_conditions(db, window)
    unmet = [result for result in results if not result.satisfied]
    if unmet:
        _event(db, window, "release_rejected", actor_email=actor_email, details={
            "source": source, "unmet": [{"key": r.key, "reason": r.reason} for r in unmet],
        })
        db.flush()
        raise MaintenanceError("Freigabebedingungen nicht erfüllt: " + ", ".join(f"{r.key} ({r.reason})" for r in unmet))
    transition(db, window, "completed", actor_email=actor_email, details={"source": source})
    return window


def cancel_scheduled(db: Session, window_id: uuid.UUID, *, actor_email: str | None) -> MaintenanceWindow:
    window = lock_window(db, window_id)
    if window.state != "scheduled":
        raise MaintenanceError("Nur geplante Wartungsfenster können abgesagt werden")
    return transition(db, window, "cancelled", actor_email=actor_email)


def start_window(db: Session, window_id: uuid.UUID, *, actor_email: str | None) -> MaintenanceWindow:
    """Manuelle Wartung kontrolliert starten: preparing -> (Wartezeit für laufende Anfragen) ->
    active. Jobgebundene Fenster startet ihr Job selbst."""
    window = lock_window(db, window_id)
    if window.source_job_type is not None:
        raise MaintenanceError("Dieses Wartungsfenster wird von seinem Job gesteuert")
    if window.state == "scheduled":
        transition(db, window, "preparing", actor_email=actor_email)
    if window.state != "preparing":
        raise MaintenanceError("Wartungsfenster kann nicht gestartet werden")
    return window


def update_message(db: Session, window_id: uuid.UUID, *, public_message: dict[str, str] | None,
                   scheduled_start_at: datetime | None = None, scheduled_end_at: datetime | None = None,
                   internal_note: str | None = None, actor_email: str | None) -> MaintenanceWindow:
    window = lock_window(db, window_id)
    if window.state in TERMINAL_STATES:
        raise MaintenanceError("Beendete Wartungsfenster können nicht mehr bearbeitet werden")
    if public_message is not None:
        window.public_message = _clean_messages(public_message)
    if window.state == "scheduled":
        if scheduled_start_at is not None:
            window.scheduled_start_at = scheduled_start_at
        if scheduled_end_at is not None:
            window.scheduled_end_at = scheduled_end_at
        if window.scheduled_start_at and window.scheduled_end_at and window.scheduled_end_at <= window.scheduled_start_at:
            raise MaintenanceError("Das geplante Ende muss nach dem Beginn liegen")
    if internal_note is not None:
        window.internal_note = internal_note[:4000]
    window.updated_at = _now()
    _event(db, window, "updated", actor_email=actor_email)
    db.flush()
    return window


# --- Überwachung (Hintergrundloop maintenance_supervisor) --------------------------------------


# Wie lange preparing bei manueller Wartung mindestens dauert: neue Anfragen sind ab dem
# nächsten Cache-Ablauf gesperrt, laufende bekommen diese Zeit zum Abschliessen.
PREPARE_GRACE_SECONDS = 20


def supervise(db: Session) -> dict[str, int]:
    """Ein Tick: geplante manuelle Wartung starten, vorbereitete manuelle Wartung aktivieren,
    Überschreitungen markieren und Schätzungen jobgebundener Fenster nachführen. Beendet nie ein
    Fenster - die Freigabe bleibt an die Bedingungen gebunden."""
    from app.services.maintenance_estimator import estimate_for_window

    now = _now()
    counts = {"started": 0, "activated": 0, "overdue": 0, "estimated": 0}
    for window in db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.state.in_(("scheduled", "preparing", "active", "verifying", "overdue")))).all():
        if window.source_job_type is None and window.state == "scheduled" and window.scheduled_start_at and window.scheduled_start_at <= now:
            transition(db, window, "preparing", details={"source": "schedule"})
            counts["started"] += 1
        elif window.source_job_type is None and window.state == "preparing" and window.started_at and (now - window.started_at).total_seconds() >= PREPARE_GRACE_SECONDS:
            transition(db, window, "active", details={"source": "supervisor"})
            counts["activated"] += 1
        if window.source_job_type is not None and window.state in ("active", "verifying", "overdue"):
            estimate = estimate_for_window(db, window)
            if estimate is not None:
                apply_estimate(db, window, estimate)
                counts["estimated"] += 1
        if window.state in ("active", "verifying") and window.estimated_end_at and window.estimated_end_at < now:
            transition(db, window, "overdue", details={"source": "supervisor"})
            counts["overdue"] += 1
        elif window.state == "overdue" and window.estimated_end_at and window.estimated_end_at > now:
            # Neue (spätere) Schätzung liegt vor: zurück in den Normalzustand, die
            # Überschreitung bleibt im Verlauf und über original_estimated_end_at sichtbar.
            transition(db, window, "active", details={"source": "supervisor", "reason": "re_estimated"})
    db.commit()
    return counts


# --- Öffentliche Sicht -------------------------------------------------------------------------


def _round_up(seconds: float, step: int) -> int:
    return int(-(-seconds // step) * step)


def public_status(db: Session) -> dict[str, Any]:
    """Nur unkritische Angaben: keine Job-IDs, keine Profil-/Bucket-Namen, keine Fehlertexte.
    Restdauer als gerundete Spanne (keine Scheingenauigkeit), nie als Countdown auf null."""
    now = _now()
    blocking = db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.state.in_(BLOCKING_STATES)).order_by(MaintenanceWindow.created_at)).all()
    upcoming = db.scalars(
        select(MaintenanceWindow).where(MaintenanceWindow.state == "scheduled", MaintenanceWindow.scheduled_start_at.is_not(None))
        .order_by(MaintenanceWindow.scheduled_start_at).limit(3)
    ).all()
    full = [window for window in blocking if window.kind == "full"]
    relevant = full or blocking
    status: dict[str, Any] = {
        "active": bool(full),
        "partial": bool(blocking) and not full,
        "block_scope": "all" if full else ("writes" if any(w.block_scope == "writes" for w in blocking) else ("uploads" if blocking else None)),
        "reason_code": relevant[0].reason_code if relevant else None,
        "messages": relevant[0].public_message if relevant else {},
        "affected_features": sorted({feature for window in relevant for feature in (window.affected_features or [])}),
        "started_at": min((w.started_at for w in relevant if w.started_at), default=None),
        "estimate_state": None,
        "estimated_end_at": None,
        "remaining_low_seconds": None,
        "remaining_high_seconds": None,
        "upcoming": [
            {"starts_at": w.scheduled_start_at, "ends_at": w.scheduled_end_at, "kind": w.kind, "messages": w.public_message, "reason_code": w.reason_code}
            for w in upcoming
        ],
        "updated_at": now,
    }
    if relevant:
        ends = [w.estimated_end_at for w in relevant]
        if any(end is None for end in ends):
            status["estimate_state"] = "estimating"
        else:
            latest_end = max(ends)  # type: ignore[type-var]
            overdue = any(w.state == "overdue" for w in relevant) or latest_end <= now
            if overdue:
                status["estimate_state"] = "overdue"
            else:
                lows = [((w.estimate or {}).get("remaining_low_seconds"), w.estimate_updated_at) for w in relevant]
                remaining_high = (latest_end - now).total_seconds()
                remaining_low = max(
                    (max(0.0, low - (now - updated).total_seconds()) for low, updated in lows if low is not None and updated is not None),
                    default=remaining_high * 0.7,
                )
                step = 300 if remaining_high > 900 else 60
                high = max(_round_up(remaining_high, step), step)
                low = min(_round_up(remaining_low, step), high)
                status.update({
                    "estimate_state": "estimated",
                    "estimated_end_at": latest_end,
                    "remaining_low_seconds": low,
                    "remaining_high_seconds": high,
                })
    return status
