"""Dashboard v2 / Statistik: neue Kennzahlen in GET /statistics/overview (year=, compare=).

Geprüft werden überfällige Pendenzen, Ø Tage bis erledigt, offene Pendenzen je Person, Bussen
bezahlt/offen und nach Art je Person, Jahresauswahl und Vorjahresvergleich - jeweils mit den
Sichtbarkeitsregeln der bestehenden Statistik (Mandant, reports.personal/PRIV-001, Finanzmodul,
finances.read)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.api.routes.statistics import get_statistics_overview
from app.models import FinanceTransaction, TodoStatus
from app.services.statistics_common import previous_year_bounds
from app.services.todo_fine_service import today as today_local
from tests.factories import (
    make_app_user,
    make_current_user,
    make_finance_account,
    make_fine,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)


def _attendance_protocol(db, tenant_id, template_id, number, when, entries):
    protocol = make_protocol(db, tenant_id, template_id, protocol_number=number, protocol_date=when, status="durchgeführt")
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, configuration_snapshot_json={"attendance_entries": entries}, element_type_code="attendance")
    return protocol


def _todo(db, tenant_id, task, *, assignee=None, due=None, done_after_days=None):
    todo = make_protocol_todo(db, None, task=task, tenant_id=tenant_id)
    todo.assigned_participant_id = assignee.id if assignee else None
    todo.due_date = due
    if done_after_days is not None:
        created = datetime.now(timezone.utc) - timedelta(days=done_after_days + 1)
        todo.created_at = created
        todo.completed_at = created + timedelta(days=done_after_days)
        todo.todo_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "done"))
    db.flush()
    return todo


def _setup(db, name="Dashboard v2"):
    today = today_local()
    tenant = make_tenant(db, name)
    reader = make_app_user(db, email=f"leser-{tenant.id}@example.com", first_name="Lea", last_name="Leser", tenant_id=tenant.id)
    other = make_app_user(db, email=f"andere-{tenant.id}@example.com", first_name="Otto", last_name="Andere", tenant_id=tenant.id)
    template = make_template(db, tenant.id)
    entries = [
        {"participant_id": reader.id, "participant_name": "Lea Leser", "status": "present"},
        {"participant_id": other.id, "participant_name": "Otto Andere", "status": "absent"},
    ]
    current = _attendance_protocol(db, tenant.id, template.id, "P-1", date(today.year, 1, 2), entries)
    _attendance_protocol(db, tenant.id, template.id, "P-0", date(today.year - 1, 1, 2), entries[:1])

    account = make_finance_account(db, tenant.id)
    paid = make_fine(db, protocol_id=current.id, account_id=account.id, amount=Decimal("50.00"), participant_name_snapshot="Otto Andere", fine_type="absent")
    paid.participant_id = other.id
    paid.status = "collected"
    late = make_fine(db, protocol_id=current.id, account_id=account.id, amount=Decimal("10.00"), participant_name_snapshot="Otto Andere", fine_type="late")
    late.participant_id = other.id
    own = make_fine(db, protocol_id=current.id, account_id=account.id, amount=Decimal("10.00"), participant_name_snapshot="Lea Leser", fine_type="late")
    own.participant_id = reader.id
    db.add(FinanceTransaction(account_id=account.id, transaction_date=date(today.year - 1, 1, 2), amount=Decimal("100.00"), description="Beitrag"))
    db.flush()

    _todo(db, tenant.id, "Lange überfällig", assignee=other, due=today - timedelta(days=40))
    _todo(db, tenant.id, "Kurz überfällig", assignee=other, due=today - timedelta(days=2))
    _todo(db, tenant.id, "Im Plan", assignee=reader, due=today + timedelta(days=5))
    _todo(db, tenant.id, "Erledigt", assignee=reader, done_after_days=4)
    return tenant, reader, other, today


def _overview(db, tenant_id, role, user_id, **kwargs):
    features = kwargs.pop("features", None)
    return get_statistics_overview(db=db, user=make_current_user(tenant_id, role=role, user_id=user_id, features=features), **kwargs)


def test_todo_insights_overdue_duration_and_load_per_person(db):
    tenant, reader, other, today = _setup(db)

    overview = _overview(db, tenant.id, "admin", reader.id, year=today.year)

    insights = overview.todo_insights
    assert insights.overdue == 2
    assert insights.overdue_long == 1
    assert insights.avg_days_to_done == 4.0
    loads = {row.name: (row.open, row.overdue) for row in insights.open_by_person}
    assert loads == {"Otto Andere": (2, 2), "Lea Leser": (1, 0)}
    assert overview.period_start == date(today.year, 1, 1)
    assert overview.period_end == date(today.year, 12, 31)
    assert overview.available_years == [today.year - 1, today.year]


def test_fines_paid_open_and_types_per_person(db):
    tenant, reader, _, today = _setup(db)

    overview = _overview(db, tenant.id, "admin", reader.id, year=today.year)

    assert overview.fines_visible is True
    [status] = overview.fines_status
    assert (status.paid_count, status.paid_amount, status.open_count, status.open_amount) == (1, 50.0, 2, 20.0)
    otto = next(row for row in overview.fines_by_participant if row.name == "Otto Andere")
    assert (otto.absent_count, otto.late_count, otto.absent_amount, otto.late_amount) == (1, 1, 50.0, 10.0)


def test_reader_sees_only_own_person_figures(db):
    tenant, reader, _, today = _setup(db)

    overview = _overview(db, tenant.id, "reader", reader.id, year=today.year, compare=True)

    assert overview.per_person_scope == "own"
    assert [row.name for row in overview.todo_insights.open_by_person] == ["Lea Leser"]
    # Aggregierte Pendenzen-Kennzahlen bleiben vollständig (keine Personen darin).
    assert overview.todo_insights.overdue == 2
    [status] = overview.fines_status
    assert (status.paid_amount, status.open_amount) == (0.0, 10.0)
    assert [row.name for row in overview.fines_by_participant] == ["Lea Leser"]
    assert overview.comparison is not None
    assert [row.name for row in overview.comparison.own_fines] == []  # Vorjahr ohne eigene Bussen


def test_finance_figures_need_finances_read(db):
    tenant, reader, _, today = _setup(db)
    user = make_current_user(tenant.id, role="reader", user_id=reader.id, permissions=frozenset({"meetings.read"}))

    overview = get_statistics_overview(db=db, user=user, year=today.year, compare=True)

    assert overview.finance_by_month == []
    assert overview.comparison is not None
    assert overview.comparison.finance_by_account == []


def test_fines_need_the_finance_module(db):
    tenant, reader, _, today = _setup(db)

    overview = _overview(db, tenant.id, "admin", reader.id, year=today.year, compare=True, features=frozenset({"abgabebox"}))

    assert overview.fines_visible is False
    assert overview.fines_status == []
    assert overview.fines_by_type == []
    assert overview.fines_by_participant == []
    assert overview.comparison is not None
    assert overview.comparison.fines_by_type == []
    assert overview.comparison.finance_by_account == []


def test_comparison_uses_the_same_period_of_the_previous_year(db):
    tenant, reader, _, today = _setup(db)

    overview = _overview(db, tenant.id, "admin", reader.id, year=today.year, compare=True)

    comparison = overview.comparison
    assert comparison is not None
    assert (comparison.period_start, comparison.period_end) == previous_year_bounds(today.year, today)
    assert comparison.protocols_total == 1
    assert [month.month for month in comparison.attendance_over_time] == [f"{today.year - 1}-01"]
    assert [(row.income, row.expenses) for row in comparison.finance_by_account] == [(100.0, 0.0)]
    # Ohne compare kein Vergleich.
    assert _overview(db, tenant.id, "admin", reader.id, year=today.year).comparison is None


def test_previous_year_bounds_for_running_and_past_years():
    assert previous_year_bounds(2026, date(2026, 11, 18)) == (date(2025, 1, 1), date(2025, 11, 18))
    assert previous_year_bounds(2025, date(2026, 11, 18)) == (date(2024, 1, 1), date(2024, 12, 31))
    assert previous_year_bounds(2028, date(2028, 2, 29)) == (date(2027, 1, 1), date(2027, 2, 28))


def test_other_tenants_never_count(db):
    tenant, reader, _, today = _setup(db, "Mandant A")
    foreign, foreign_reader, _, _ = _setup(db, "Mandant B")

    overview = _overview(db, tenant.id, "admin", reader.id, year=today.year, compare=True)

    # Nur die Zahlen des eigenen Mandanten, obwohl Mandant B identische Daten hat.
    assert overview.todo_insights.overdue == 2
    assert {row.name for row in overview.todo_insights.open_by_person} == {"Otto Andere", "Lea Leser"}
    assert all(row.participant_key != f"id:{foreign_reader.id}" for row in overview.todo_insights.open_by_person)
    [status] = overview.fines_status
    assert status.open_count == 2
    assert overview.comparison is not None
    assert overview.comparison.protocols_total == 1
    assert len(overview.comparison.finance_by_account) == 1
    # Und umgekehrt: Mandant B sieht ebenfalls nur seine eigenen Zahlen.
    foreign_overview = _overview(db, foreign.id, "admin", foreign_reader.id, year=today.year)
    assert foreign_overview.todo_insights.overdue == 2


def test_todo_period_counts_by_swiss_day_not_utc(db):
    """Eine freie Pendenz vom 1.1. um 00:30 Schweizer Zeit (31.12. 23:30 UTC) gehört ins neue Jahr,
    eine vom 31.12. um 23:30 Schweizer Zeit (22:30 UTC) ins alte (Nachtlauf 2026-11-20)."""
    from app.services.statistics_common import calendar_year_bounds, fetch_todo_insight_rows, fetch_todo_rows

    tenant = make_tenant(db, "Statistik Tagesgrenze")
    new_year = make_protocol_todo(db, None, task="Neujahr 00:30", tenant_id=tenant.id)
    new_year.created_at = datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc)
    old_year = make_protocol_todo(db, None, task="Silvester 23:30", tenant_id=tenant.id)
    old_year.created_at = datetime(2025, 12, 31, 22, 30, tzinfo=timezone.utc)
    late_utc = make_protocol_todo(db, None, task="Silvester 00:30 (nächstes Jahr)", tenant_id=tenant.id)
    late_utc.created_at = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)
    db.flush()

    tasks = {row[0].task for row in fetch_todo_insight_rows(db, tenant.id, calendar_year_bounds(2025))}
    assert tasks == {"Neujahr 00:30", "Silvester 23:30"}
    assert len(fetch_todo_rows(db, tenant.id, calendar_year_bounds(2025))) == 2
    assert {row[0].task for row in fetch_todo_insight_rows(db, tenant.id, calendar_year_bounds(2024))} == set()
    assert {row[0].task for row in fetch_todo_insight_rows(db, tenant.id, calendar_year_bounds(2026))} == {
        "Silvester 00:30 (nächstes Jahr)",
    }


def test_active_members_exclude_former_members(db):
    """«Ø anwesend … von {count} Mitgliedern»: Ausgetretene (Austrittsdatum vor heute, Schweizer
    Zeit) zählen nicht mehr als aktive Mitglieder; am Austrittstag selbst noch."""
    tenant, reader, other, today = _setup(db, "Aktive Mitglieder")
    other.left_at = today - timedelta(days=1)
    leaving_today = make_app_user(db, email=f"heute-{tenant.id}@example.com", tenant_id=tenant.id)
    leaving_today.left_at = today
    db.flush()
    overview = _overview(db, tenant.id, "admin", reader.id, year=today.year)
    assert overview.participants_active == 2
