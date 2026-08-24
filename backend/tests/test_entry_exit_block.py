"""Tests for the "Ein-/Austritte" (entry/exit) protocol block: ProtocolService._entry_exit_entries
computes, for a template's entry/exit block, the participant joins/leaves (Participant.joined_at/
left_at) since the block's prior use in an earlier protocol of the same template, up to and
including the current protocol's date - so consecutive protocols each report a disjoint date
window and no join/leave is ever listed twice.
"""
from __future__ import annotations

from datetime import date

from app.services.protocol_service import ProtocolService

from tests.factories import make_participant, make_protocol, make_template, make_template_participant, make_tenant


def _entries(db, *, template_id, tenant_id, protocol_date, current_protocol_id=0, block_config=None):
    return ProtocolService()._entry_exit_entries(
        db,
        tenant_id=tenant_id,
        template_id=template_id,
        protocol_date=protocol_date,
        current_protocol_id=current_protocol_id,
        block_config=block_config or {},
    )


def test_first_use_default_mode_reports_all_history(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    leaver = make_participant(db, tenant.id, "Alt Leaver")
    leaver.left_at = date(2020, 1, 1)
    joiner = make_participant(db, tenant.id, "New Joiner")
    joiner.joined_at = date(2026, 1, 10)
    db.flush()
    make_template_participant(db, template.id, leaver.id)
    make_template_participant(db, template.id, joiner.id)

    entries = _entries(db, template_id=template.id, tenant_id=tenant.id, protocol_date=date(2026, 2, 1))

    kinds = {(e["participant_name"], e["type"]) for e in entries}
    assert kinds == {("Alt Leaver", "leave"), ("New Joiner", "join")}


def test_first_use_since_date_mode_excludes_history_before_cutoff(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    old_leaver = make_participant(db, tenant.id, "Old Leaver")
    old_leaver.left_at = date(2020, 1, 1)
    recent_leaver = make_participant(db, tenant.id, "Recent Leaver")
    recent_leaver.left_at = date(2026, 1, 15)
    db.flush()
    make_template_participant(db, template.id, old_leaver.id)
    make_template_participant(db, template.id, recent_leaver.id)

    entries = _entries(
        db,
        template_id=template.id,
        tenant_id=tenant.id,
        protocol_date=date(2026, 2, 1),
        block_config={"entry_exit_first_use_mode": "since_date", "entry_exit_first_use_date": "2026-01-01"},
    )

    names = {e["participant_name"] for e in entries}
    assert names == {"Recent Leaver"}


def test_second_use_only_reports_changes_since_prior_protocol_no_duplicates(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    early_leaver = make_participant(db, tenant.id, "Early Leaver")
    early_leaver.left_at = date(2026, 1, 5)
    late_leaver = make_participant(db, tenant.id, "Late Leaver")
    late_leaver.left_at = date(2026, 2, 20)
    db.flush()
    make_template_participant(db, template.id, early_leaver.id)
    make_template_participant(db, template.id, late_leaver.id)

    prior_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 1, 10))
    current_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-2", protocol_date=date(2026, 3, 1))

    # First use (as of the prior protocol): Early Leaver is reported.
    first_entries = _entries(
        db,
        template_id=template.id,
        tenant_id=tenant.id,
        protocol_date=prior_protocol.protocol_date,
        current_protocol_id=prior_protocol.id,
    )
    assert {e["participant_name"] for e in first_entries} == {"Early Leaver"}

    # Second use: Early Leaver must NOT reappear, only Late Leaver (new since the prior protocol).
    second_entries = _entries(
        db,
        template_id=template.id,
        tenant_id=tenant.id,
        protocol_date=current_protocol.protocol_date,
        current_protocol_id=current_protocol.id,
    )
    assert {e["participant_name"] for e in second_entries} == {"Late Leaver"}


def test_exit_on_protocol_date_itself_is_included(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    leaver = make_participant(db, tenant.id, "Same Day Leaver")
    leaver.left_at = date(2026, 2, 1)
    db.flush()
    make_template_participant(db, template.id, leaver.id)

    entries = _entries(db, template_id=template.id, tenant_id=tenant.id, protocol_date=date(2026, 2, 1))

    assert {e["participant_name"] for e in entries} == {"Same Day Leaver"}


def test_exit_exactly_on_prior_protocol_date_is_not_repeated(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    leaver = make_participant(db, tenant.id, "Boundary Leaver")
    leaver.left_at = date(2026, 1, 10)
    db.flush()
    make_template_participant(db, template.id, leaver.id)

    prior_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 1, 10))
    current_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-2", protocol_date=date(2026, 2, 1))

    # Reported once, in the protocol whose date matches the exit date exactly...
    first_entries = _entries(
        db,
        template_id=template.id,
        tenant_id=tenant.id,
        protocol_date=prior_protocol.protocol_date,
        current_protocol_id=prior_protocol.id,
    )
    assert {e["participant_name"] for e in first_entries} == {"Boundary Leaver"}

    # ...and must not reappear in the next protocol.
    second_entries = _entries(
        db,
        template_id=template.id,
        tenant_id=tenant.id,
        protocol_date=current_protocol.protocol_date,
        current_protocol_id=current_protocol.id,
    )
    assert second_entries == []


def test_excluded_from_attendance_participant_is_skipped(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    leaver = make_participant(db, tenant.id, "Excluded Leaver")
    leaver.left_at = date(2026, 1, 1)
    db.flush()
    make_template_participant(db, template.id, leaver.id, exclude_from_attendance=True)

    entries = _entries(db, template_id=template.id, tenant_id=tenant.id, protocol_date=date(2026, 2, 1))

    assert entries == []


def test_join_and_leave_for_same_participant_both_listed(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    person = make_participant(db, tenant.id, "In And Out")
    person.joined_at = date(2026, 1, 5)
    person.left_at = date(2026, 1, 20)
    db.flush()
    make_template_participant(db, template.id, person.id)

    entries = _entries(db, template_id=template.id, tenant_id=tenant.id, protocol_date=date(2026, 2, 1))

    types = {e["type"] for e in entries}
    assert types == {"join", "leave"}
    assert len(entries) == 2
