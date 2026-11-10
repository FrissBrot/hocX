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
