"""Zustandsmaschine der Storage-Migration: explizite, vollständige Übergänge."""

from __future__ import annotations

import pytest

from app.services import storage_migration_service as sms


def test_transition_table_is_complete_and_terminal_states_are_final():
    assert set(sms.MIGRATION_TRANSITIONS) == set(sms.STATES)
    assert all(target in sms.STATES for targets in sms.MIGRATION_TRANSITIONS.values() for target in targets)
    for state in sms.TERMINAL_STATES:
        assert sms.MIGRATION_TRANSITIONS[state] == set()


@pytest.mark.parametrize("from_state,to_state", [
    ("cutting_over", "cancelled"),  # nach Beginn des Umschaltens kein Abbruch
    ("observing", "cancelled"),
    ("observing", "ready_for_cutover"),  # nach dem Commit kein stilles Zurück
    ("rollback_required", "completed"),
    ("awaiting_confirmation", "copying"),  # Start nur über die Inventur
    ("completed", "copying"),
])
def test_forbidden_transitions_are_rejected(from_state, to_state):
    with pytest.raises(sms.MigrationError):
        sms.check_transition(from_state, to_state)


def test_every_working_state_can_fail_safely_or_retry():
    for state in ("preflight", "inventory", "copying", "catching_up", "verifying", "ready_for_cutover", "cutting_over"):
        assert {"retrying", "failed"} & sms.MIGRATION_TRANSITIONS[state]


def test_initial_migration_excludes_temporary_files_and_caches_only():
    excluded = ["uploads/_staging/gallery/x.zip", "uploads/_multipart/y", "exports/protocol-1/main.tex", "document_templates/t/main.tex", "latex_templates/x.tex", "uploads/a/.hocx-upload-123"]
    kept = ["uploads/tenant-1/gallery/a.jpg", "exports/generated/a.pdf", "document_template_parts/tenant-1/x/v1.tex", "document_template_snapshots/tenant-1/p/main.tex", "demo-seed/x.png", "unbekannt/datei.bin"]
    assert all(sms.is_excluded_initial_key("main", key) for key in excluded)
    assert not any(sms.is_excluded_initial_key("main", key) for key in kept)
    assert not sms.is_excluded_initial_key("abgabebox", "quarantine/tenant-1/x.pdf")
