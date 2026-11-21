"""Shared aggregation helpers for the statistics dashboard and the PDF chart generator.

Used by both app/api/routes/statistics.py (/statistics/overview API) and
app/documents/providers/statistics.py (Diagramme und Kennzahlen der Dokument-Engine). The two call
sites used to implement the attendance/groups/fines/todo aggregation logic independently
and had already begun to drift (2026-08-12 audit, findings M4/M10/M11/M12) - keep the
logic here instead, so a rule change only has to be made in one place.

The one place this could NOT be de-duplicated is
frontend/components/statistics/statistics-view.tsx, which re-implements the weighted
"Ø Teilnehmer" merge (see aggregate_group_rows below) a third time, in TypeScript, because
the API returns raw per-cycle rows rather than a pre-merged view. See the comment at that
call site - keep it in sync by hand if the merge rule changes here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Row, func, select, text
from sqlalchemy.orm import Session

from app.core.permissions import P
from app.models.entities import (
    ElementType,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolTodo,
    TodoStatus,
)

# Welche Listen die Gruppen liefern, markiert list_definition.is_group_source (Migration 0176,
# vorher fest der Listenname «Gruppen» - eine umbenannte Liste liess den Abschnitt still leer).


def chart_cycle_bounds(db: Session, tenant_id: int, config_id, offset: int = 0):
    """Dieselbe relative Zykluslogik wie bei Abgaben; Bezug ist der heutige Zyklus."""
    from app.core.cycle_utils import cycle_years_for_offsets, reset_boundary
    from app.models.entities import CycleConfig
    from uuid import UUID

    if not config_id:
        return None
    config = db.scalar(select(CycleConfig).where(
        CycleConfig.tenant_id == tenant_id, CycleConfig.public_id == UUID(str(config_id)),
    ))
    if config is None:
        raise ValueError("Zyklus nicht gefunden")
    from app.services.todo_fine_service import today as today_local

    # Schweizer «heute», nicht UTC: sonst kippt der Zyklus am Reset-Tag erst 1-2 Stunden zu spät.
    year = next(iter(cycle_years_for_offsets(today_local(), config.reset_month, config.reset_day, [offset])))
    # cycle_year ist das Startjahr, auch bei Kalenderjahren (Reset am 31.12.).
    boundary_year = year - 1 if config.reset_month == 12 and config.reset_day == 31 else year
    return (reset_boundary(boundary_year, config.reset_month, config.reset_day) + timedelta(days=1),
            reset_boundary(boundary_year + 1, config.reset_month, config.reset_day))


def _todo_period_date():
    """Stichtag einer Pendenz für den Statistik-Zeitraum: Protokolldatum, sonst der Schweizer
    Kalendertag der Erfassung. Nie ``cast(created_at, Date)``: das rechnet in der Zeitzone der
    DB-Session (UTC), eine Pendenz vom 1.1. um 00:30 fiele ins Vorjahr (Nachtlauf 2026-11-20)."""
    from app.services.capture_date import upload_day_sql

    return func.coalesce(Protocol.protocol_date, upload_day_sql(ProtocolTodo.created_at))


def _date_conditions(column, bounds):
    return [] if bounds is None else [column >= bounds[0], column <= bounds[1]]


# Eingeschränkte Leser (nur bestimmten Vorlagen zugeordnet) sehen in der Statistik nur Zahlen aus
# diesen Vorlagen (Audit 07, C9): ``template_ids`` None = alle Vorlagen des Mandanten, sonst die
# lesbaren. Eine leere Menge ergibt keine Zeilen.
def _template_sql(template_ids: set[int] | None, alias: str = "p") -> tuple[str, dict]:
    if template_ids is None:
        return "", {}
    return f" AND {alias}.template_id = ANY(:template_ids)", {"template_ids": sorted(template_ids) or [0]}  # sql-ok: fester Alias aus dem Code


# ── Attendance ────────────────────────────────────────────────────────────────

def fetch_attendance_blocks(
    db: Session, tenant_id: int, bounds: tuple[date, date] | None = None, template_ids: set[int] | None = None,
) -> list[tuple[date, dict]]:
    """Raw (protocol_date, configuration_snapshot_json) rows for every attendance block
    that counts towards statistics/charts.

    Only "durchgeführt"/"abgeschlossen" protocols are included: "vorbereitet" protocols
    haven't happened yet - attendance is still being tracked/editable and only becomes
    final at the vorbereitet -> durchgeführt transition (see
    list_snapshot_service.clear_tracked_changes_for_protocol) - so it must not feed the
    statistics.
    """
    attendance_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "attendance"))
    if not attendance_type_id:
        return []
    rows = db.execute(
        select(Protocol.protocol_date, ProtocolElementBlock.configuration_snapshot_json)
        .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
        .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
        .where(
            Protocol.tenant_id == tenant_id,
            Protocol.status.in_(["durchgeführt", "abgeschlossen"]),
            ProtocolElementBlock.element_type_id == attendance_type_id,
            *_date_conditions(Protocol.protocol_date, bounds),
            *([] if template_ids is None else [Protocol.template_id.in_(template_ids)]),
        )
        .order_by(Protocol.protocol_date)
    ).all()
    return [(r.protocol_date, r.configuration_snapshot_json) for r in rows]


@dataclass
class AttendanceCounts:
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0

    @property
    def total(self) -> int:
        return self.present + self.late + self.absent + self.excused

    def bump(self, status: str) -> None:
        # Four-value status, matching the document engine's attendance block: "late" is its own
        # bucket, not lumped into "absent" (a late arrival is not the same as a no-show).
        if status == "present":
            self.present += 1
        elif status == "late":
            self.late += 1
        elif status == "excused":
            self.excused += 1
        else:
            self.absent += 1


@dataclass
class ParticipantAttendance:
    key: str
    name: str
    counts: AttendanceCounts = field(default_factory=AttendanceCounts)


def aggregate_attendance(
    blocks: list[tuple[date, dict]],
) -> tuple[dict[str, AttendanceCounts], list[ParticipantAttendance]]:
    """Aggregate attendance_entries by month and by participant.

    Grouped by participant_id where available - NOT by participant_name (audit finding
    M4) - so renaming a participant doesn't split their attendance history into two rows.
    Entries without a participant_id (legacy/manually-typed names) fall back to grouping
    by name. `blocks` must be ordered by protocol_date ascending (fetch_attendance_blocks
    already does this) so that the last entry seen for a key wins and each participant's
    row is labelled with their most recent known name.
    """
    monthly: dict[str, AttendanceCounts] = defaultdict(AttendanceCounts)
    per_participant: dict[str, ParticipantAttendance] = {}

    for proto_date, config in blocks:
        entries = (config or {}).get("attendance_entries", []) if config else []
        month_key = proto_date.strftime("%Y-%m") if proto_date else None
        for entry in entries:
            name = entry.get("participant_name") or "Unbekannt"
            pid = entry.get("participant_id")
            key = f"id:{pid}" if pid is not None else f"name:{name}"
            status = entry.get("status") or "absent"

            row = per_participant.get(key)
            if row is None:
                row = ParticipantAttendance(key=key, name=name)
                per_participant[key] = row
            row.name = name  # last-seen name wins -> most recent known name
            row.counts.bump(status)

            if month_key:
                monthly[month_key].bump(status)

    return monthly, list(per_participant.values())


# ── Todos ─────────────────────────────────────────────────────────────────────

def fetch_todo_rows(
    db: Session, tenant_id: int, bounds: tuple[date, date] | None = None, template_ids: set[int] | None = None,
) -> list[Row]:
    """template_ids (eingeschränkte Leser): nur Todos aus Protokollen dieser Vorlagen; freie Todos
    ohne Protokoll zählen dann nicht."""
    return db.execute(
        select(TodoStatus.code, ProtocolTodo.completed_at)
        # LEFT JOINs - protocol_element_block_id is nullable (standalone todos and
        # submission-assignment/Abgabebox-generated todos have no block), an INNER JOIN
        # here silently drops both kinds. Der Mandant steht seit Migration 0131 in jedem Todo;
        # der Protocol-Join liefert nur noch das Protokolldatum.
        .outerjoin(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .outerjoin(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .outerjoin(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .where(ProtocolTodo.tenant_id == tenant_id)
        .where(*_date_conditions(_todo_period_date(), bounds))
        .where(*([] if template_ids is None else [Protocol.template_id.in_(template_ids)]))
    ).all()


def aggregate_todo_counts(rows: list[Row]) -> tuple[int, int]:
    """Return (open, done)."""
    done = sum(1 for t in rows if t.code in ("done", "cancelled") or t.completed_at)
    return len(rows) - done, done


# ── Fines ─────────────────────────────────────────────────────────────────────

def fetch_fines_by_participant(
    db: Session, tenant_id: int, bounds: tuple[date, date] | None = None, template_ids: set[int] | None = None,
) -> list[Row]:
    """SUM() on the DB side over the Numeric(15,2) amount column, instead of repeated
    Python float additions of CHF amounts (audit finding M12) - same pattern already used
    by the finance-by-month report. Returns (name, count, amount) rows with amount as
    Decimal.

    Grouped by participant_id where available (COALESCE'd into the group key as text) - NOT
    by participant_name_snapshot alone (audit D9, 2026-08-16) - so two participants sharing
    a name (e.g. parent/child) aren't merged into one row, and a renamed participant's fines
    aren't split across two rows. Mirrors aggregate_attendance's `id:{pid}`/`name:{name}` key
    convention above. Rows without a participant_id (participant deleted, FK SET NULL) fall
    back to grouping by the frozen name snapshot, same as before this fix.

    Beträge werden je Währung des Kontos getrennt (MAIN-BE-019) - eine Person mit Bussen in
    zwei Währungen ergibt zwei Zeilen. Mit Begründung gelöschte Bussen zählen nicht."""
    template_filter, template_params = _template_sql(template_ids)
    return db.execute(
        text(  # sql-ok: nur feste Teilabfragen/Ausdrücke aus diesem Modul, Werte gebunden
            f"""
            SELECT
                MAX(COALESCE(p2.display_name, af.participant_name_snapshot)) AS name,
                COALESCE('id:' || af.participant_id::text, 'name:' || af.participant_name_snapshot) AS participant_key,
                fa.currency_label AS currency,
                COUNT(*) AS count,
                SUM(af.amount) AS amount,
                -- Aufteilung nach Art für das gestapelte Diagramm «Bussen pro Person» (Dashboard v2)
                COUNT(*) FILTER (WHERE af.fine_type = 'absent') AS absent_count,
                COUNT(*) FILTER (WHERE af.fine_type = 'late') AS late_count,
                COALESCE(SUM(af.amount) FILTER (WHERE af.fine_type = 'absent'), 0) AS absent_amount,
                COALESCE(SUM(af.amount) FILTER (WHERE af.fine_type = 'late'), 0) AS late_amount
            FROM attendance_fine af
            JOIN protocol p ON p.id = af.protocol_id
            JOIN finance_account fa ON fa.id = af.account_id
            LEFT JOIN app_user p2 ON p2.id = af.participant_id
            WHERE p.tenant_id = :tenant_id
              AND af.status <> 'deleted'
              AND (CAST(:date_start AS date) IS NULL OR p.protocol_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR p.protocol_date <= :date_end)
              {template_filter}
            GROUP BY COALESCE('id:' || af.participant_id::text, 'name:' || af.participant_name_snapshot), fa.currency_label
        """),
        {"tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None, **template_params},
    ).all()


def fetch_fines_by_type(
    db: Session, tenant_id: int, bounds: tuple[date, date] | None = None, template_ids: set[int] | None = None,
) -> list[Row]:
    """SUM() on the DB side, see fetch_fines_by_participant. Returns (fine_type, currency,
    count, amount) rows with amount as Decimal, one row per type and currency."""
    template_filter, template_params = _template_sql(template_ids)
    return db.execute(
        text(  # sql-ok: nur feste Teilabfragen/Ausdrücke aus diesem Modul, Werte gebunden
            f"""
            SELECT
                af.fine_type AS fine_type,
                fa.currency_label AS currency,
                COUNT(*) AS count,
                SUM(af.amount) AS amount
            FROM attendance_fine af
            JOIN protocol p ON p.id = af.protocol_id
            JOIN finance_account fa ON fa.id = af.account_id
            WHERE p.tenant_id = :tenant_id
              AND af.status <> 'deleted'
              AND (CAST(:date_start AS date) IS NULL OR p.protocol_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR p.protocol_date <= :date_end)
              {template_filter}
            GROUP BY af.fine_type, fa.currency_label
        """),
        {"tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None, **template_params},
    ).all()


def fetch_fines_status(
    db: Session,
    tenant_id: int,
    bounds: tuple[date, date] | None = None,
    template_ids: set[int] | None = None,
    participant_id: int | None = None,
) -> list[Row]:
    """Bezahlte (eingezogene) und offene Bussen je Währung (Dashboard v2, «Bezahlt / offen").
    ``participant_id`` schränkt auf die Bussen einer Person ein (Sicht ohne reports.personal,
    PRIV-001). Gelöschte Bussen zählen nicht."""
    template_filter, template_params = _template_sql(template_ids)
    person_filter = "" if participant_id is None else " AND af.participant_id = :participant_id"
    return db.execute(
        text(  # sql-ok: nur feste Teilabfragen/Ausdrücke aus diesem Modul, Werte gebunden
            f"""
            SELECT
                fa.currency_label AS currency,
                COUNT(*) FILTER (WHERE af.status = 'collected') AS paid_count,
                COALESCE(SUM(af.amount) FILTER (WHERE af.status = 'collected'), 0) AS paid_amount,
                COUNT(*) FILTER (WHERE af.status = 'pending') AS open_count,
                COALESCE(SUM(af.amount) FILTER (WHERE af.status = 'pending'), 0) AS open_amount
            FROM attendance_fine af
            JOIN protocol p ON p.id = af.protocol_id
            JOIN finance_account fa ON fa.id = af.account_id
            WHERE p.tenant_id = :tenant_id
              AND af.status <> 'deleted'
              AND (CAST(:date_start AS date) IS NULL OR p.protocol_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR p.protocol_date <= :date_end)
              {template_filter}{person_filter}
            GROUP BY fa.currency_label
            ORDER BY fa.currency_label
        """),
        {
            "tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None,
            **template_params, **({} if participant_id is None else {"participant_id": participant_id}),
        },
    ).all()


# ── Todo-Kennzahlen (Dashboard v2) ──────────────────────────────────────────────

# Ab wie vielen Tagen eine überfällige Pendenz als «lange überfällig» gilt.
TODO_LONG_OVERDUE_DAYS = 30


@dataclass
class TodoPersonLoad:
    key: str
    name: str
    open: int = 0
    overdue: int = 0


@dataclass
class TodoInsights:
    overdue: int = 0
    overdue_long: int = 0
    avg_days_to_done: float | None = None
    done_with_duration: int = 0
    open_by_person: list[TodoPersonLoad] = field(default_factory=list)


def fetch_todo_insight_rows(
    db: Session, tenant_id: int, bounds: tuple[date, date] | None = None, template_ids: set[int] | None = None,
) -> list[Row]:
    """Pendenzen des Zeitraums mit aufgelöster Fälligkeit und Verantwortlichen - dieselbe Basis
    wie die Pendenzenliste (ProtocolTodoRepository._base_todo_query), damit «überfällig» hier und
    dort dasselbe bedeutet. Zeitraum und Vorlagen-Filter wie fetch_todo_rows; zum Löschen
    vorgemerkte Pendenzen zählen nicht."""
    from app.repositories.protocol_todo_repository import ProtocolTodoRepository

    query, *_ = ProtocolTodoRepository()._base_todo_query()
    query = query.where(ProtocolTodo.tenant_id == tenant_id, ProtocolTodo.pending_delete.is_(False))
    query = query.where(*_date_conditions(_todo_period_date(), bounds))
    if template_ids is not None:
        query = query.where(Protocol.template_id.in_(template_ids))
    return db.execute(query).all()


def _todo_assignee_ids(row) -> list[int]:
    todo = row[0]
    ids = list(row.assignee_ids or [])
    if not ids and todo.assigned_participant_id:
        ids = [todo.assigned_participant_id]
    return ids


def aggregate_todo_insights(db: Session, tenant_id: int, rows: list[Row], today: date) -> TodoInsights:
    """Überfällige (offen, Fälligkeit vor heute), davon lange überfällige, Ø Tage von der
    Erfassung bis zur Erledigung (nur erledigte, nicht abgebrochene) und offene Pendenzen je
    verantwortlicher Person (Schlüssel ``id:<app_user.id>`` wie bei Anwesenheit und Bussen)."""
    from app.models.entities import Participant
    from app.services.todo_fine_service import local_date

    insights = TodoInsights()
    durations: list[int] = []
    loads: dict[int, TodoPersonLoad] = {}
    for row in rows:
        todo = row[0]
        code = row.todo_status_code
        is_done = code in ("done", "cancelled") or todo.completed_at is not None
        if is_done:
            if code != "cancelled" and todo.completed_at is not None and todo.created_at is not None:
                durations.append(max(0, (local_date(todo.completed_at) - local_date(todo.created_at)).days))
            continue
        due = row.resolved_due_date
        overdue = due is not None and due < today
        if overdue:
            insights.overdue += 1
            if (today - due).days > TODO_LONG_OVERDUE_DAYS:
                insights.overdue_long += 1
        for participant_id in _todo_assignee_ids(row):
            load = loads.setdefault(participant_id, TodoPersonLoad(key=f"id:{participant_id}", name=""))
            load.open += 1
            if overdue:
                load.overdue += 1

    if durations:
        insights.avg_days_to_done = round(sum(durations) / len(durations), 1)
        insights.done_with_duration = len(durations)
    if loads:
        names = dict(
            db.execute(
                select(Participant.id, Participant.display_name).where(
                    Participant.tenant_id == tenant_id, Participant.id.in_(list(loads))
                )
            ).all()
        )
        # Nur Personen des eigenen Mandanten (Namen fremder IDs werden nie geladen).
        insights.open_by_person = sorted(
            (TodoPersonLoad(key=load.key, name=names[pid] or "", open=load.open, overdue=load.overdue)
             for pid, load in loads.items() if pid in names),
            key=lambda item: (-item.open, -item.overdue, item.name),
        )
    return insights


# ── Zeiträume (Kalenderjahr, Vorjahresvergleich) ───────────────────────────────

def calendar_year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def previous_year_bounds(year: int, today: date) -> tuple[date, date]:
    """Gleicher Zeitraum im Vorjahr: für das laufende Jahr 1.1. bis «heute vor einem Jahr»
    (sonst vergliche ein halbes Jahr mit einem ganzen), für vergangene Jahre das ganze Vorjahr."""
    start, end = calendar_year_bounds(year - 1)
    if year == today.year:
        day = 28 if today.month == 2 and today.day == 29 else today.day
        end = date(year - 1, today.month, day)
    return start, end


def fetch_protocol_years(db: Session, tenant_id: int, template_ids: set[int] | None = None) -> list[int]:
    """Jahre mit durchgeführten/abgeschlossenen Protokollen (Auswahl der Statistik)."""
    conditions = [Protocol.tenant_id == tenant_id, Protocol.status.in_(["durchgeführt", "abgeschlossen"]), Protocol.protocol_date.is_not(None)]
    if template_ids is not None:
        conditions.append(Protocol.template_id.in_(template_ids))
    year = func.extract("year", Protocol.protocol_date)
    return sorted({int(value) for value in db.scalars(select(year).where(*conditions).distinct()).all() if value is not None})


# ── Finance ───────────────────────────────────────────────────────────────────

def fetch_finance_by_month(db: Session, tenant_id: int, bounds: tuple[date, date] | None = None) -> list[Row]:
    """Income/expenses per month, combined across all of the tenant's finance accounts -
    used by the document engine's "finance_by_month" chart (one combined bar per month)."""
    return db.execute(
        text("""
            SELECT to_char(ft.transaction_date, 'YYYY-MM') AS month,
                   SUM(CASE WHEN ft.amount > 0 THEN ft.amount ELSE 0 END) AS income,
                   SUM(CASE WHEN ft.amount < 0 THEN ABS(ft.amount) ELSE 0 END) AS expenses
            FROM finance_transaction ft
            JOIN finance_account fa ON fa.id = ft.account_id
            WHERE fa.tenant_id = :tenant_id
              AND (CAST(:date_start AS date) IS NULL OR ft.transaction_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR ft.transaction_date <= :date_end)
            GROUP BY month ORDER BY month
        """),
        {"tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None},
    ).all()


def fetch_finance_by_account_month(db: Session, tenant_id: int, bounds: tuple[date, date] | None = None) -> list[Row]:
    """Same as fetch_finance_by_month but broken down per account - used by the
    /statistics/overview API, which lets the frontend filter/merge by account."""
    return db.execute(
        text("""
            SELECT
                ft.account_id,
                fa.name AS account_name,
                fa.currency_label AS currency,
                to_char(ft.transaction_date, 'YYYY-MM') AS month,
                SUM(CASE WHEN ft.amount > 0 THEN ft.amount ELSE 0 END) AS income,
                SUM(CASE WHEN ft.amount < 0 THEN ABS(ft.amount) ELSE 0 END) AS expenses
            FROM finance_transaction ft
            JOIN finance_account fa ON fa.id = ft.account_id
            WHERE fa.tenant_id = :tenant_id
              AND (CAST(:date_start AS date) IS NULL OR ft.transaction_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR ft.transaction_date <= :date_end)
            GROUP BY ft.account_id, fa.name, fa.currency_label, month
            ORDER BY month
        """),
        {"tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None},
    ).all()


# ── Groups ────────────────────────────────────────────────────────────────────
#
# A tenant's "groups" are event.tag values that match an entry in a list marked as group
# source (list_definition.is_group_source, Migration 0176 - a ListDefinition/ListEntry pair,
# not a dedicated table). Der Gruppenname steht in der Spalte mit der Rolle «Bezeichnung»
# (list_definition.label_column_id, Migration 0186); nur Text-Werte haben text_value, eine
# Personen- oder Termin-Spalte als Bezeichnung ergibt keine Gruppe (audit finding M10).
_GROUP_TAGS_SUBQUERY = """
    SELECT le.values_json -> lc.key ->> 'text_value'
    FROM list_definition ld
    JOIN list_column lc ON lc.id = ld.label_column_id
    JOIN list_entry le ON le.list_definition_id = ld.id
    WHERE ld.tenant_id = :tenant_id AND ld.is_group_source
"""


def fetch_group_tagged_cycles(db: Session, tenant_id: int, bounds: tuple[date, date] | None = None) -> list[Row]:
    """Distinct (cycle_config_id, cycle_year) pairs among events whose tag matches a
    group-source list entry - powers the cycle filter/list in the statistics UI."""
    return db.execute(
        text(  # sql-ok: nur feste Teilabfragen/Ausdrücke aus diesem Modul, Werte gebunden
            f"""
            SELECT DISTINCT ec.cycle_config_id, ec.cycle_year
            FROM event_cycle ec
            JOIN event e ON e.id = ec.event_id
            WHERE e.tenant_id = :tenant_id
              AND (CAST(:date_start AS date) IS NULL OR e.event_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR e.event_date <= :date_end)
              AND e.tag IN ({_GROUP_TAGS_SUBQUERY})
            ORDER BY ec.cycle_config_id, ec.cycle_year
        """),
        {"tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None},
    ).all()


def fetch_group_session_rows(db: Session, tenant_id: int, bounds: tuple[date, date] | None = None) -> list[Row]:
    """Session-count / avg-participant-count stats per (event.tag, cycle_config_id,
    cycle_year), restricted to event tags that match a group-source list entry."""
    return db.execute(
        text(  # sql-ok: nur feste Teilabfragen/Ausdrücke aus diesem Modul, Werte gebunden
            f"""
            SELECT
                e.tag AS group_name,
                ec.cycle_config_id,
                ec.cycle_year,
                COUNT(DISTINCT e.id) AS session_count,
                COUNT(DISTINCT e.id) FILTER (WHERE e.participant_count > 0) AS session_count_with_participants,
                COALESCE(AVG(e.participant_count) FILTER (WHERE e.participant_count > 0), 0) AS avg_participants
            FROM event e
            LEFT JOIN event_cycle ec ON ec.event_id = e.id
            WHERE e.tenant_id = :tenant_id
              AND (CAST(:date_start AS date) IS NULL OR e.event_date >= :date_start)
              AND (CAST(:date_end AS date) IS NULL OR e.event_date <= :date_end)
              AND e.tag IS NOT NULL
              AND e.tag IN ({_GROUP_TAGS_SUBQUERY})
            GROUP BY e.tag, ec.cycle_config_id, ec.cycle_year
            ORDER BY e.tag, ec.cycle_year
        """),
        {"tenant_id": tenant_id, "date_start": bounds[0] if bounds else None, "date_end": bounds[1] if bounds else None},
    ).all()


def aggregate_group_rows(rows: list[Row], cycle_key: str | None = None) -> list[dict]:
    """Merge per-(group, cycle_config_id, cycle_year) rows from fetch_group_session_rows
    into one row per group, weighting the average participant count by
    session_count_with_participants (a plain mean-of-means would skew towards cycles that
    ran a lot of near-empty sessions).

    If cycle_key ("<cycle_config_id>:<cycle_year>", or "all"/None) is given, only rows
    belonging to that cycle are included first - used by the groups_sessions/groups_avg PDF
    charts, which honour a single cycle filter.

    This is the same weighted-average merge as the "Ø Teilnehmer" logic in
    frontend/components/statistics/statistics-view.tsx (groupsFiltered, "all" branch) - that
    one operates on the raw per-cycle rows returned by GET /statistics/overview and can't be
    eliminated without an API change (see the module docstring and the comment at that call
    site). Keep both in sync by hand if the merge rule changes.
    """
    if cycle_key and cycle_key != "all":
        try:
            config_id, year = cycle_key.split(":")
            rows = [r for r in rows if str(r.cycle_config_id) == config_id and str(r.cycle_year) == year]
        except ValueError:
            pass

    merged: dict[str, dict] = {}
    for r in rows:
        n = r.group_name
        if n not in merged:
            merged[n] = {"name": n, "sessions": 0, "sessions_with_p": 0, "weighted": 0.0}
        merged[n]["sessions"] += int(r.session_count)
        merged[n]["sessions_with_p"] += int(r.session_count_with_participants)
        merged[n]["weighted"] += float(r.avg_participants) * int(r.session_count_with_participants)

    result = []
    for v in merged.values():
        v["avg"] = round(v["weighted"] / v["sessions_with_p"], 1) if v["sessions_with_p"] > 0 else 0.0
        result.append(v)
    return sorted(result, key=lambda x: x["sessions"], reverse=True)


# ── Sichtbarkeit je Person (Datenschutz-Audit PRIV-001) ─────────────────────────────────────────

# Bussen und Anwesenheit aller Personen sieht, wer reports.personal hat - dieselbe Regel wie die
# Bussenliste. Alle anderen sehen in Ranglisten je Person nur sich selbst, ausser der Mandant gibt
# sie ausdrücklich frei (tenant.statistics_per_person_public).


def own_person_key(db: Session, user) -> str | None:
    """None: der Aufrufer sieht alle Personen. Sonst der Gruppierungsschlüssel der eigenen Person
    (``id:<app_user.id>``, siehe aggregate_attendance/fetch_fines_by_participant) - Teilnehmer und
    Konto sind seit 0108 dieselbe Identität. Ohne Benutzer (interne Aufrufe) sind alle sichtbar."""
    if user is None or user.can(P.REPORTS_PERSONAL):
        return None
    from app.models.entities import Tenant

    if db.scalar(select(Tenant.statistics_per_person_public).where(Tenant.id == user.current_tenant_id)):
        return None
    return f"id:{user.user_id}"

