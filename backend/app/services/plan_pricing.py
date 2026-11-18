"""Monats- und Jahrespreis von Plänen und Speicherpaketen gehören zusammen.

Fehlt einer der beiden, wird er aus dem anderen berechnet - dieselbe Regel wie der Vorschlag im
Admin-Formular (frontend/components/admin/admin-plan-pricing.tsx): Monatspreis = Jahrespreis / 12
plus 20 % Aufschlag, auf 5 Rappen gerundet; umgekehrt Jahrespreis = Monatspreis × 12 / 1.2.
Sonst fehlt auf der Website bei «Jährlich» der Preis und ein Jahresabo liesse sich nicht abrechnen.
"""
from __future__ import annotations

import math

YEARLY_MARKUP = 1.2  # Monatsabo kostet aufs Jahr gerechnet 20 % mehr


def _round_5(rp: float) -> int:
    # Kaufmännisch (.5 aufwärts) wie Math.round im Formular und round() in der Migration
    return int(math.floor(rp / 5 + 0.5) * 5)


def monthly_from_yearly(yearly_rp: int) -> int:
    return _round_5(yearly_rp / 12 * YEARLY_MARKUP)


def yearly_from_monthly(monthly_rp: int) -> int:
    return _round_5(monthly_rp * 12 / YEARLY_MARKUP)


def complete(monthly_rp: int | None, yearly_rp: int | None) -> tuple[int | None, int | None]:
    """(Monat, Jahr) mit ergänztem fehlendem Wert; beide leer bleibt beide leer."""
    if monthly_rp is None and yearly_rp is not None:
        return monthly_from_yearly(yearly_rp), yearly_rp
    if yearly_rp is None and monthly_rp is not None:
        return monthly_rp, yearly_from_monthly(monthly_rp)
    return monthly_rp, yearly_rp
