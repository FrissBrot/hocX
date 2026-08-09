from app.schemas.word_import import TablePreview, WordImportAnalysis, WordImportAttendanceMapping
from app.services.word_import_queue_service import (
    _BATCH_CONSENSUS_MIN_DOCS,
    _build_batch_consensus_hint,
    _needs_consensus_rerun,
)


def _analysis(*, attendance=(), tables=()) -> WordImportAnalysis:
    return WordImportAnalysis(attendance_mappings=list(attendance), tables=list(tables))


def _attendance(raw_name: str, participant_id: int | None) -> WordImportAttendanceMapping:
    return WordImportAttendanceMapping(raw_name=raw_name, suggested_participant_id=participant_id)


def _table(index: int, header_cells: list[str], role: str, role_is_explicit: bool) -> TablePreview:
    return TablePreview(index=index, header_cells=header_cells, role=role, role_is_explicit=role_is_explicit)


def test_name_hint_requires_min_docs_agreeing():
    assert _BATCH_CONSENSUS_MIN_DOCS == 3
    analyses = [
        _analysis(attendance=[_attendance("Nevio", 42)]),
        _analysis(attendance=[_attendance("Nevio", 42)]),
        # Only 2 of 3 agree on participant 42 - below the minimum, no hint yet.
    ]
    hint = _build_batch_consensus_hint(analyses)
    assert hint == {}


def test_name_hint_emitted_once_min_docs_agree():
    analyses = [_analysis(attendance=[_attendance("Nevio", 42)]) for _ in range(3)]
    hint = _build_batch_consensus_hint(analyses)
    assert hint["participant_name_overrides"]["nevio"] == 42


def test_table_role_hint_requires_explicit_role():
    # Same role guessed 3 times, but never from an explicit source - must not count.
    analyses = [
        _analysis(tables=[_table(0, ["Name", "Anwesend"], "attendance", role_is_explicit=False)]) for _ in range(3)
    ]
    hint = _build_batch_consensus_hint(analyses)
    assert hint == {}


def test_table_role_hint_from_explicit_agreement():
    analyses = [
        _analysis(tables=[_table(0, ["Name", "Anwesend"], "attendance", role_is_explicit=True)]) for _ in range(3)
    ]
    hint = _build_batch_consensus_hint(analyses)
    assert hint["table_roles_by_signature"]["name | anwesend"]["role"] == "attendance"


def test_needs_rerun_only_when_document_has_a_gap_the_hint_can_fill():
    hint = {"participant_name_overrides": {"nevio": 42}, "table_roles_by_signature": {}}
    resolved = _analysis(attendance=[_attendance("Nevio", 42)])
    unresolved = _analysis(attendance=[_attendance("Nevio", None)])
    unrelated_unresolved = _analysis(attendance=[_attendance("Gian", None)])
    assert _needs_consensus_rerun(resolved, hint) is False
    assert _needs_consensus_rerun(unresolved, hint) is True
    assert _needs_consensus_rerun(unrelated_unresolved, hint) is False
