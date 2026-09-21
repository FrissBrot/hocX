"""element_resolver._cycle_years dupliziert bewusst backend/app/core/cycle_utils.py
(get_cycle_year/cycle_years_for_offsets) - siehe Modul-Docstring von element_resolver. Diese
Tests halten die Faelle fest, an denen beide Implementierungen uebereinstimmen muessen.
"""
from __future__ import annotations

from datetime import date

from app.element_resolver import _cycle_years


def test_default_reset_dec_31_current_and_previous():
    assert _cycle_years(date(2026, 3, 1), 12, 31, [0, -1]) == {2026, 2025}


def test_reset_on_the_boundary_day_still_belongs_to_the_ending_cycle():
    # Zyklus 01.08.-31.07.: der 31.07.2026 gehoert noch zu 2025, der 01.08.2026 zu 2026.
    assert _cycle_years(date(2026, 7, 31), 7, 31, [0]) == {2025}
    assert _cycle_years(date(2026, 8, 1), 7, 31, [0]) == {2026}


def test_reset_day_clamped_to_last_day_of_month():
    # 30. Februar existiert nicht -> letzter Februartag; 01.03. beginnt der neue Zyklus.
    assert _cycle_years(date(2026, 3, 1), 2, 30, [0]) == {2026}
    assert _cycle_years(date(2026, 2, 28), 2, 30, [0]) == {2025}


def test_offsets_are_relative_to_current_cycle():
    assert _cycle_years(date(2026, 9, 20), 7, 31, [0, -1, -2]) == {2026, 2025, 2024}
