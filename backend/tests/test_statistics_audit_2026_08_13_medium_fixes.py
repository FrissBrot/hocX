"""Regression tests for the 4 "Mittel" findings from the 2026-08-13 statistics audit
(M4/M10/M11/M12 - all in the statistics dashboard / PDF chart export area).

M4  - attendance was aggregated by participant_name instead of participant_id, so
      renaming a participant split their history into two rows.
M10 - the "Gruppen" list lookup only ever read column_one_value_json, silently returning
      nothing for tenants who put the group name text in column two.
M11 - the attendance/todo/fines/groups aggregation logic was implemented independently in
      app/api/routes/statistics.py and app/services/chart_service.py; both now delegate to
      app/services/statistics_common.py.
M12 - fine amounts were summed as repeated Python float additions instead of a DB-side
      Decimal SUM().

Each test below exercises the shared statistics_common.py helpers directly, and - where
practical - the two call sites (the /statistics/overview route function and
chart_service's PDF-chart data fetchers) to prove they now agree (M11).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.api.routes.statistics import get_statistics_overview
from app.services.chart_service import _fetch_attendance_data, _fetch_fines_data, _fetch_groups_data
from app.services.statistics_common import (
    aggregate_attendance,
    aggregate_group_rows,
    fetch_attendance_blocks,
    fetch_fines_by_participant,
    fetch_fines_by_type,
    fetch_group_session_rows,
)

from tests.factories import (
    make_current_user,
    make_event,
    make_finance_account,
    make_fine,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


# --- M4: attendance grouped by participant_id, not participant_name ------------------------

def test_m4_attendance_survives_participant_rename(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)

    protocol_early = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 1, 1), status="durchgeführt")
    element_early = make_protocol_element(db, protocol_early.id)
    make_protocol_element_block(
        db, element_early.id,
        configuration_snapshot_json={
            "attendance_entries": [{"participant_id": 42, "participant_name": "Anna Müller", "status": "present"}]
        },
        element_type_code="attendance",
    )

    # Same person, renamed before the second (later) protocol.
    protocol_late = make_protocol(db, tenant.id, template.id, protocol_number="P-2", protocol_date=date(2026, 2, 1), status="durchgeführt")
    element_late = make_protocol_element(db, protocol_late.id)
    make_protocol_element_block(
        db, element_late.id,
        configuration_snapshot_json={
            "attendance_entries": [{"participant_id": 42, "participant_name": "Anna Meier", "status": "absent"}]
        },
        element_type_code="attendance",
    )

    # 1. Shared helper: must merge into a single row, labelled with the most recent name.
    blocks = fetch_attendance_blocks(db, tenant.id)
    _, per_participant = aggregate_attendance(blocks)
    assert len(per_participant) == 1, "renamed participant must not split into two rows"
    row = per_participant[0]
    assert row.name == "Anna Meier"
    assert row.counts.present == 1
    assert row.counts.absent == 1
    assert row.counts.total == 2

    # 2. Route-level: /statistics/overview must show the same merged row (M11: same helper).
    overview = get_statistics_overview(db=db, user=make_current_user(tenant.id))
    assert len(overview.attendance_by_participant) == 1
    stat = overview.attendance_by_participant[0]
    assert stat.name == "Anna Meier"
    assert stat.total == 2

    # 3. chart_service (PDF export data): same merge, same single row.
    _, by_participant = _fetch_attendance_data(db, tenant.id)
    assert len(by_participant) == 1
    assert by_participant[0]["name"] == "Anna Meier"
    assert by_participant[0]["total"] == 2


# --- M10: "Gruppen" list works regardless of which column holds the text -------------------

def test_m10_groups_list_reads_column_two(db):
    tenant = make_tenant(db)
    list_def = make_list_definition(db, tenant.id, name="Gruppen")
    # Tenant put the group-name text in column TWO, not column one.
    make_list_entry(db, list_def.id, column_one_value={}, column_two_value={"text_value": "Adler"})
    # Control: a second group with the text in the "normal" column one, to make sure that
    # path still works too.
    make_list_entry(db, list_def.id, sort_index=1, column_one_value={"text_value": "Falken"}, column_two_value={})

    event_col2 = make_event(db, tenant.id, title="Adler-Treffen", event_date=date(2026, 3, 1))
    event_col2.tag = "Adler"
    event_col2.participant_count = 7
    event_col1 = make_event(db, tenant.id, title="Falken-Treffen", event_date=date(2026, 3, 2))
    event_col1.tag = "Falken"
    event_col1.participant_count = 3
    db.flush()

    rows = fetch_group_session_rows(db, tenant.id)
    names = {r.group_name for r in rows}
    assert "Adler" in names, "group whose name lives in column_two_value_json must be found (M10)"
    assert "Falken" in names, "column_one_value_json path must still work"

    # chart_service wiring (M11): same result via the shared fetch + merge.
    merged = _fetch_groups_data(db, tenant.id)
    merged_names = {m["name"] for m in merged}
    assert {"Adler", "Falken"} <= merged_names

    # Route wiring: /statistics/overview must list both groups too.
    overview = get_statistics_overview(db=db, user=make_current_user(tenant.id))
    overview_names = {g.group_name for g in overview.groups_stats}
    assert {"Adler", "Falken"} <= overview_names


# --- M11: aggregate_group_rows (weighted "Ø Teilnehmer" merge) --------------------------

def test_m11_aggregate_group_rows_weights_by_sessions_with_participants():
    """Pure unit test of the merge extracted out of chart_service._fetch_groups_data (now
    also the logic the frontend's groupsFiltered "all" branch has to mirror by hand - see
    the comment there and in aggregate_group_rows' docstring).

    Two per-cycle rows for the same group: one cycle with an avg of 10 participants over a
    single session, another with an avg of 2 over nine sessions. A plain mean-of-means would
    give (10+2)/2 = 6.0; weighting by session_count_with_participants must instead give
    (10*1 + 2*9) / (1+9) = 2.8 - pulled towards the cycle that actually ran more sessions.
    """
    rows = [
        SimpleNamespace(group_name="Wölfe", cycle_config_id=1, cycle_year=2025,
                         session_count=1, session_count_with_participants=1, avg_participants=10),
        SimpleNamespace(group_name="Wölfe", cycle_config_id=1, cycle_year=2026,
                         session_count=9, session_count_with_participants=9, avg_participants=2),
    ]

    merged = aggregate_group_rows(rows)
    assert len(merged) == 1
    assert merged[0]["name"] == "Wölfe"
    assert merged[0]["sessions"] == 10
    assert merged[0]["sessions_with_p"] == 10
    assert merged[0]["avg"] == 2.8


# --- M12: fine amounts summed via DB-side Decimal SUM(), not Python float addition ---------

def test_m12_fine_amounts_summed_as_exact_decimal(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    account = make_finance_account(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)

    # Classic float trap: 1.1 + 2.2 as repeated Python float addition != the correctly
    # rounded float for the exact decimal sum 3.30.
    make_fine(db, protocol.id, account.id, amount=1.1, fine_type="late", participant_name_snapshot="Bob")
    make_fine(db, protocol.id, account.id, amount=2.2, fine_type="late", participant_name_snapshot="Bob")

    naive_float_sum = 0.0
    for v in (1.1, 2.2):
        naive_float_sum += v
    exact = float(Decimal("1.10") + Decimal("2.20"))
    assert naive_float_sum != exact, "sanity check: the float trap this fix avoids must be real"

    participant_rows = fetch_fines_by_participant(db, tenant.id)
    assert len(participant_rows) == 1
    assert isinstance(participant_rows[0].amount, Decimal)
    assert participant_rows[0].amount == Decimal("3.30")

    type_rows = fetch_fines_by_type(db, tenant.id)
    assert len(type_rows) == 1
    assert type_rows[0].amount == Decimal("3.30")

    # Both call sites must report the exact value, not the float-drifted one.
    overview = get_statistics_overview(db=db, user=make_current_user(tenant.id))
    assert overview.fines_by_participant[0].amount == exact

    by_participant, by_type = _fetch_fines_data(db, tenant.id)
    assert by_participant[0]["amount"] == exact
