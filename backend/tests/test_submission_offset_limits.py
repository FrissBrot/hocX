"""Abgabe-Zeitfenster ohne Obergrenze (Nachtlauf 2026-11-19): offset_days_before/after waren nur
`ge=0`; Datum ± riesiger Offset lief beim Abgleich in einen OverflowError (pro Abgabe abgefangen,
die Abgabe glich danach nie mehr ab)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.submission import MAX_FILES_PER_ELEMENT, OFFSET_DAYS_MAX, SubmissionAssignmentCreate, SubmissionAssignmentUpdate
from app.services.submission_service import _shift_date


def _create(**overrides):
    values = {"title": "Fotos", "source_type": "events", "tag_filter": "hock", "public_slug": "fotos"}
    values.update(overrides)
    return SubmissionAssignmentCreate(**values)


@pytest.mark.parametrize("field", ["offset_days_before", "offset_days_after"])
def test_offsets_above_the_limit_are_rejected(field):
    assert getattr(_create(**{field: OFFSET_DAYS_MAX}), field) == OFFSET_DAYS_MAX
    with pytest.raises(ValidationError):
        _create(**{field: OFFSET_DAYS_MAX + 1})
    with pytest.raises(ValidationError):
        _create(**{field: 10**9})
    with pytest.raises(ValidationError):
        SubmissionAssignmentUpdate(**{field: OFFSET_DAYS_MAX + 1})
    assert getattr(SubmissionAssignmentUpdate(**{field: 0}), field) == 0


def test_existing_huge_offsets_no_longer_overflow():
    assert _shift_date(date(2026, 11, 19), 7) == date(2026, 11, 26)
    assert _shift_date(date(2026, 11, 19), 10**9) == date.max
    assert _shift_date(date(2026, 11, 19), -(10**9)) == date.min
    assert _shift_date(date(9999, 12, 1), 3650) == date.max


def test_max_files_per_element_has_an_upper_limit():
    """Höchstzahl Dateien je Feld: 1–MAX_FILES_PER_ELEMENT oder unbegrenzt (None)."""
    assert _create(max_files_per_element=MAX_FILES_PER_ELEMENT).max_files_per_element == MAX_FILES_PER_ELEMENT
    assert _create(max_files_per_element=None).max_files_per_element is None
    with pytest.raises(ValidationError):
        _create(max_files_per_element=MAX_FILES_PER_ELEMENT + 1)
    with pytest.raises(ValidationError):
        _create(max_files_per_element=0)
    with pytest.raises(ValidationError):
        SubmissionAssignmentUpdate(max_files_per_element=10**10)
    assert SubmissionAssignmentUpdate(max_files_per_element=1).max_files_per_element == 1
