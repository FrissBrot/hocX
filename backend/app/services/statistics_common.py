"""Shared aggregation helpers for the statistics dashboard and the PDF chart generator.

Used by both app/api/routes/statistics.py (/statistics/overview API) and
app/services/chart_service.py (matplotlib PNGs embedded in exported PDFs). The two call
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
from datetime import date
from decimal import Decimal

from sqlalchemy import Row, or_, select, text
from sqlalchemy.orm import Session

from app.models.entities import (
    ElementType,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolTodo,
    TodoStatus,
)

# Name of the list_definition that holds the tenant's group tags (event.tag values that
# count as "groups" for stats/charts).
GROUPS_LIST_NAME = "Gruppen"


# ── Attendance ────────────────────────────────────────────────────────────────

def fetch_attendance_blocks(db: Session, tenant_id: int) -> list[tuple[date, dict]]:
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
        # Four-value status, matching export_service's counting: "late" is its own
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

def fetch_todo_rows(db: Session, tenant_id: int) -> list[Row]:
    return db.execute(
        select(TodoStatus.code, ProtocolTodo.completed_at)
        # LEFT JOINs - protocol_element_block_id is nullable (standalone todos and
        # submission-assignment/Abgabebox-generated todos have no block), an INNER JOIN
        # here silently drops both kinds. Those todos carry their own ProtocolTodo.tenant_id
        # instead, checked in the WHERE below.
        .outerjoin(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .outerjoin(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .outerjoin(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .where(or_(Protocol.tenant_id == tenant_id, ProtocolTodo.tenant_id == tenant_id))
    ).all()


def aggregate_todo_counts(rows: list[Row]) -> tuple[int, int]:
    """Return (open, done)."""
    done = sum(1 for t in rows if t.code in ("done", "cancelled") or t.completed_at)
    return len(rows) - done, done


# ── Fines ─────────────────────────────────────────────────────────────────────

def fetch_fines_by_participant(db: Session, tenant_id: int) -> list[Row]:
    """SUM() on the DB side over the Numeric(15,2) amount column, instead of repeated
    Python float additions of CHF amounts (audit finding M12) - same pattern already used
    by the finance-by-month report. Returns (name, count, amount) rows with amount as
    Decimal.

    Grouped by participant_id where available (COALESCE'd into the group key as text) - NOT
    by participant_name_snapshot alone (audit D9, 2026-08-16) - so two participants sharing
    a name (e.g. parent/child) aren't merged into one row, and a renamed participant's fines
    aren't split across two rows. Mirrors aggregate_attendance's `id:{pid}`/`name:{name}` key
    convention above. Rows without a participant_id (participant deleted, FK SET NULL) fall
    back to grouping by the frozen name snapshot, same as before this fix."""
    return db.execute(
        text("""
            SELECT
                MAX(COALESCE(p2.display_name, af.participant_name_snapshot)) AS name,
                COUNT(*) AS count,
                SUM(af.amount) AS amount
            FROM attendance_fine af
            JOIN protocol p ON p.id = af.protocol_id
            LEFT JOIN participant p2 ON p2.id = af.participant_id
            WHERE p.tenant_id = :tenant_id
            GROUP BY COALESCE(af.participant_id::text, af.participant_name_snapshot)
        """),
        {"tenant_id": tenant_id},
    ).all()


def fetch_fines_by_type(db: Session, tenant_id: int) -> list[Row]:
    """SUM() on the DB side, see fetch_fines_by_participant. Returns (fine_type, count,
    amount) rows with amount as Decimal."""
    return db.execute(
        text("""
            SELECT
                af.fine_type AS fine_type,
                COUNT(*) AS count,
                SUM(af.amount) AS amount
            FROM attendance_fine af
            JOIN protocol p ON p.id = af.protocol_id
            WHERE p.tenant_id = :tenant_id
            GROUP BY af.fine_type
        """),
        {"tenant_id": tenant_id},
    ).all()


# ── Finance ───────────────────────────────────────────────────────────────────

def fetch_finance_by_month(db: Session, tenant_id: int) -> list[Row]:
    """Income/expenses per month, combined across all of the tenant's finance accounts -
    used by chart_service's "finance_by_month" PNG (one combined bar per month)."""
    return db.execute(
        text("""
            SELECT to_char(ft.transaction_date, 'YYYY-MM') AS month,
                   SUM(CASE WHEN ft.amount > 0 THEN ft.amount ELSE 0 END) AS income,
                   SUM(CASE WHEN ft.amount < 0 THEN ABS(ft.amount) ELSE 0 END) AS expenses
            FROM finance_transaction ft
            JOIN finance_account fa ON fa.id = ft.account_id
            WHERE fa.tenant_id = :tenant_id
            GROUP BY month ORDER BY month
        """),
        {"tenant_id": tenant_id},
    ).all()


def fetch_finance_by_account_month(db: Session, tenant_id: int) -> list[Row]:
    """Same as fetch_finance_by_month but broken down per account - used by the
    /statistics/overview API, which lets the frontend filter/merge by account."""
    return db.execute(
        text("""
            SELECT
                ft.account_id,
                fa.name AS account_name,
                to_char(ft.transaction_date, 'YYYY-MM') AS month,
                SUM(CASE WHEN ft.amount > 0 THEN ft.amount ELSE 0 END) AS income,
                SUM(CASE WHEN ft.amount < 0 THEN ABS(ft.amount) ELSE 0 END) AS expenses
            FROM finance_transaction ft
            JOIN finance_account fa ON fa.id = ft.account_id
            WHERE fa.tenant_id = :tenant_id
            GROUP BY ft.account_id, fa.name, month
            ORDER BY month
        """),
        {"tenant_id": tenant_id},
    ).all()


# ── Groups ────────────────────────────────────────────────────────────────────
#
# A tenant's "groups" are event.tag values that match an entry in their "Gruppen" list
# (a ListDefinition/ListEntry pair, not a dedicated table). The list has two generic
# columns and nothing forces the group name text into column one specifically - a tenant
# is free to set it up with the text in column two. Entries of value_type "text" are the
# only ones that ever populate a "text_value" key (participant/participants/event-typed
# entries store participant_id/participant_ids/event_id instead, see
# word_import_service._resolved_value_json) - so COALESCE-ing column_one and column_two's
# text_value safely finds the group name regardless of which column it lives in, without
# risk of accidentally picking up an unrelated id (audit finding M10).
_GROUP_TAGS_SUBQUERY = """
    SELECT COALESCE(le.column_one_value_json->>'text_value', le.column_two_value_json->>'text_value')
    FROM list_definition ld
    JOIN list_entry le ON le.list_definition_id = ld.id
    WHERE ld.tenant_id = :tenant_id AND ld.name = :groups_list_name
"""


def fetch_group_tagged_cycles(db: Session, tenant_id: int) -> list[Row]:
    """Distinct (cycle_config_id, cycle_year) pairs among events whose tag matches a
    'Gruppen' list entry - powers the cycle filter/list in the statistics UI."""
    return db.execute(
        text(f"""
            SELECT DISTINCT ec.cycle_config_id, ec.cycle_year
            FROM event_cycle ec
            JOIN event e ON e.id = ec.event_id
            WHERE e.tenant_id = :tenant_id
              AND e.tag IN ({_GROUP_TAGS_SUBQUERY})
            ORDER BY ec.cycle_config_id, ec.cycle_year
        """),
        {"tenant_id": tenant_id, "groups_list_name": GROUPS_LIST_NAME},
    ).all()


def fetch_group_session_rows(db: Session, tenant_id: int) -> list[Row]:
    """Session-count / avg-participant-count stats per (event.tag, cycle_config_id,
    cycle_year), restricted to event tags that match a 'Gruppen' list entry."""
    return db.execute(
        text(f"""
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
              AND e.tag IS NOT NULL
              AND e.tag IN ({_GROUP_TAGS_SUBQUERY})
            GROUP BY e.tag, ec.cycle_config_id, ec.cycle_year
            ORDER BY e.tag, ec.cycle_year
        """),
        {"tenant_id": tenant_id, "groups_list_name": GROUPS_LIST_NAME},
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
