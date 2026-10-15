"""Retention der Wiederherstellungspunkte - reine Funktion, ohne Repository-Zugriff.

Regeln (Default 14 Tage / 14 täglich / 8 wöchentlich / 12 monatlich, alle UTC):
- keep_within_days: jeder vollständige Punkt der letzten N Tage (also alle 6-stündlichen).
- keep_daily/weekly/monthly: wie `borg prune` - je Periode (Tag, ISO-Woche, Monat) der
  jüngste vollständige Punkt, für die jüngsten N Perioden, die überhaupt einen Punkt haben.
- Regeln werden VEREINIGT: ein Punkt bleibt, sobald irgendeine Regel ihn hält.
- Immer behalten: geschützte Punkte (Rettungspunkt vor Restore, vor Deploy), der jüngste
  vollständige Punkt und der jüngste verwertbare Punkt (vollständig oder "partial") - auch wenn
  die Uhr falsch steht, lange kein Backup lief oder es nur noch teilweise erfolgreiche Punkte
  gibt. Die Retention entfernt also nie alle Wiederherstellungspunkte.
- Teilweise erfolgreiche ("partial") Punkte zählen für keine Periodenregel; sonst bleiben sie nur
  im keep_within-Fenster erhalten (sie können einzelne Dateien enthalten, die sonst fehlen).
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RetentionPolicy:
    keep_within_days: int = 14
    keep_daily: int = 14
    keep_weekly: int = 8
    keep_monthly: int = 12


@dataclass(frozen=True)
class RestorePoint:
    id: Hashable
    at: datetime
    state: str  # completed | partial
    protected: bool = False


def _periodic(points: list[RestorePoint], count: int, period: Callable[[datetime], Hashable]) -> set[Hashable]:
    kept: set[Hashable] = set()
    if count <= 0:
        return kept
    seen: set[Hashable] = set()
    for point in points:  # absteigend sortiert
        key = period(point.at)
        if key in seen:
            continue
        seen.add(key)
        kept.add(point.id)
        if len(seen) >= count:
            break
    return kept


def select_retained(points: Iterable[RestorePoint], policy: RetentionPolicy, now: datetime) -> dict[Hashable, list[str]]:
    """Liefert {id: [Gründe]} für alle zu behaltenden Punkte; alles andere darf entfernt werden."""
    ordered = sorted(points, key=lambda p: p.at, reverse=True)
    complete = [p for p in ordered if p.state == "completed"]
    reasons: dict[Hashable, list[str]] = {}

    def keep(point_id: Hashable, reason: str) -> None:
        reasons.setdefault(point_id, []).append(reason)

    for point in ordered:
        if point.protected:
            keep(point.id, "protected")
    if complete:
        keep(complete[0].id, "latest")
    usable = [p for p in ordered if p.state in ("completed", "partial")]
    if usable:
        # Auch wenn jede Sicherung nur teilweise gelang (z. B. ein dauerhaft fehlendes Objekt):
        # der jüngste verwertbare Punkt bleibt, sonst gingen alle Punkte verloren.
        keep(usable[0].id, "latest_usable")
    if policy.keep_within_days > 0:
        cutoff = now - timedelta(days=policy.keep_within_days)
        for point in ordered:
            if point.at >= cutoff and point.state in ("completed", "partial"):
                keep(point.id, "within")
    for point_id in _periodic(complete, policy.keep_daily, lambda at: at.date()):
        keep(point_id, "daily")
    for point_id in _periodic(complete, policy.keep_weekly, lambda at: tuple(at.isocalendar())[:2]):
        keep(point_id, "weekly")
    for point_id in _periodic(complete, policy.keep_monthly, lambda at: (at.year, at.month)):
        keep(point_id, "monthly")
    return reasons
