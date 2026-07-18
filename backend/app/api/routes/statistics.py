from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.cycle_utils import format_cycle_name
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader
from app.models.entities import (
    AttendanceFine,
    CycleConfig,
    ElementType,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolTodo,
    TodoStatus,
)

router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────────


class AttendanceStat(BaseModel):
    name: str
    present: int
    absent: int
    excused: int
    total: int


class AttendanceMonth(BaseModel):
    month: str
    present: int
    absent: int
    excused: int
    total: int


class MonthCount(BaseModel):
    month: str
    count: int


class FineByStat(BaseModel):
    name: str
    count: int
    amount: float


class FineTypeStat(BaseModel):
    fine_type: str
    label: str
    count: int
    amount: float


class TodoSummary(BaseModel):
    open: int
    done: int
    total: int


class FinanceMonthStat(BaseModel):
    month: str
    account_id: int
    account_name: str
    income: float
    expenses: float
    net: float


class CycleInfo(BaseModel):
    cycle_config_id: int
    cycle_config_name: str
    cycle_year: int
    label: str


class GroupStat(BaseModel):
    group_name: str
    group_id: int
    cycle_config_id: int | None
    cycle_year: int | None
    session_count: int
    session_count_with_participants: int
    avg_participants: float


class StatisticsOverview(BaseModel):
    attendance_by_participant: list[AttendanceStat]
    attendance_over_time: list[AttendanceMonth]
    todos: TodoSummary
    fines_by_participant: list[FineByStat]
    fines_by_type: list[FineTypeStat]
    finance_by_month: list[FinanceMonthStat]
    participants_total: int
    participants_active: int
    protocols_total: int
    cycles: list[CycleInfo]
    groups_stats: list[GroupStat]


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("/statistics/overview", response_model=StatisticsOverview)
def get_statistics_overview(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    tenant_id = user.current_tenant_id

    # ── Protocols total ──────────────────────────────────────────────────────
    protocols_total = db.scalar(
        select(Protocol.id).where(Protocol.tenant_id == tenant_id).with_only_columns(
            text("COUNT(*)")
        )
    ) or 0

    # ── Cycles ───────────────────────────────────────────────────────────────
    cycle_configs = {
        cc.id: cc
        for cc in db.scalars(
            select(CycleConfig).where(CycleConfig.tenant_id == tenant_id)
        ).all()
    }
    event_cycles_rows = db.execute(
        text("""
            SELECT DISTINCT ec.cycle_config_id, ec.cycle_year
            FROM event_cycle ec
            JOIN event e ON e.id = ec.event_id
            WHERE e.tenant_id = :tenant_id
              AND e.tag IN (
                  SELECT le.column_one_value_json->>'text_value'
                  FROM list_definition ld
                  JOIN list_entry le ON le.list_definition_id = ld.id
                  WHERE ld.tenant_id = :tenant_id AND ld.name = 'Gruppen'
              )
            ORDER BY ec.cycle_config_id, ec.cycle_year
        """),
        {"tenant_id": tenant_id},
    ).all()
    cycles: list[CycleInfo] = []
    seen_cycles: set[tuple[int, int]] = set()
    for ec in event_cycles_rows:
        key = (ec.cycle_config_id, ec.cycle_year)
        if key not in seen_cycles:
            seen_cycles.add(key)
            cc = cycle_configs.get(ec.cycle_config_id)
            if cc:
                cycles.append(CycleInfo(
                    cycle_config_id=ec.cycle_config_id,
                    cycle_config_name=cc.name,
                    cycle_year=ec.cycle_year,
                    label=format_cycle_name(cc.name_pattern or cc.name, ec.cycle_year),
                ))

    # ── Groups stats (groups identified by event.tag matching Gruppen list) ──
    group_rows = db.execute(
        text("""
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
              AND e.tag IN (
                  SELECT le.column_one_value_json->>'text_value'
                  FROM list_definition ld
                  JOIN list_entry le ON le.list_definition_id = ld.id
                  WHERE ld.tenant_id = :tenant_id
                    AND ld.name = 'Gruppen'
              )
            GROUP BY e.tag, ec.cycle_config_id, ec.cycle_year
            ORDER BY e.tag, ec.cycle_year
        """),
        {"tenant_id": tenant_id},
    ).all()

    groups_stats = [
        GroupStat(
            group_id=0,
            group_name=r.group_name,
            cycle_config_id=r.cycle_config_id,
            cycle_year=r.cycle_year,
            session_count=int(r.session_count),
            session_count_with_participants=int(r.session_count_with_participants),
            avg_participants=float(r.avg_participants),
        )
        for r in group_rows
    ]

    # ── Attendance ───────────────────────────────────────────────────────────
    attendance_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "attendance"))

    attendance_blocks: list[tuple[date, dict]] = []
    if attendance_type_id:
        rows = db.execute(
            select(Protocol.protocol_date, ProtocolElementBlock.configuration_snapshot_json)
            .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(
                Protocol.tenant_id == tenant_id,
                Protocol.status.in_(["vorbereitet", "durchgeführt", "abgeschlossen"]),
                ProtocolElementBlock.element_type_id == attendance_type_id,
            )
            .order_by(Protocol.protocol_date)
        ).all()
        attendance_blocks = [(r.protocol_date, r.configuration_snapshot_json) for r in rows]

    # Per-participant aggregation
    participant_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "absent": 0, "excused": 0})
    # Per-month aggregation
    monthly_att: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "absent": 0, "excused": 0, "total": 0})

    for proto_date, config in attendance_blocks:
        entries = config.get("attendance_entries", []) if config else []
        month_key = proto_date.strftime("%Y-%m") if proto_date else None
        for entry in entries:
            name = entry.get("participant_name") or "Unbekannt"
            status = entry.get("status") or "absent"
            if status == "present":
                participant_stats[name]["present"] += 1
            elif status == "excused":
                participant_stats[name]["excused"] += 1
            else:
                participant_stats[name]["absent"] += 1
            if month_key:
                monthly_att[month_key]["total"] += 1
                if status == "present":
                    monthly_att[month_key]["present"] += 1
                elif status == "excused":
                    monthly_att[month_key]["excused"] += 1
                else:
                    monthly_att[month_key]["absent"] += 1

    attendance_by_participant = sorted(
        [
            AttendanceStat(
                name=name,
                present=s["present"],
                absent=s["absent"],
                excused=s["excused"],
                total=s["present"] + s["absent"] + s["excused"],
            )
            for name, s in participant_stats.items()
        ],
        key=lambda x: x.name,
    )

    attendance_over_time = [
        AttendanceMonth(
            month=m,
            present=v["present"],
            absent=v["absent"],
            excused=v["excused"],
            total=v["total"],
        )
        for m, v in sorted(monthly_att.items())
    ]

    # ── Todos ────────────────────────────────────────────────────────────────
    todos = db.execute(
        select(TodoStatus.code, ProtocolTodo.completed_at)
        .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .where(Protocol.tenant_id == tenant_id)
    ).all()

    todo_open = sum(1 for t in todos if t.code not in ("done", "cancelled") and not t.completed_at)
    todo_done = sum(1 for t in todos if t.code in ("done", "cancelled") or t.completed_at)
    todos_summary = TodoSummary(open=todo_open, done=todo_done, total=len(todos))

    # ── Fines ────────────────────────────────────────────────────────────────
    fines = db.execute(
        select(
            AttendanceFine.participant_name_snapshot,
            AttendanceFine.fine_type,
            AttendanceFine.amount,
            AttendanceFine.status,
        )
        .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
        .where(Protocol.tenant_id == tenant_id)
    ).all()

    per_participant: dict[str, dict[str, float | int]] = defaultdict(lambda: {"count": 0, "amount": 0.0})
    per_type: dict[str, dict[str, float | int]] = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for fine in fines:
        per_participant[fine.participant_name_snapshot]["count"] = int(per_participant[fine.participant_name_snapshot]["count"]) + 1
        per_participant[fine.participant_name_snapshot]["amount"] = float(per_participant[fine.participant_name_snapshot]["amount"]) + float(fine.amount)
        per_type[fine.fine_type]["count"] = int(per_type[fine.fine_type]["count"]) + 1
        per_type[fine.fine_type]["amount"] = float(per_type[fine.fine_type]["amount"]) + float(fine.amount)

    fine_type_labels = {"absent": "Unentschuldigt", "late": "Verspätet"}
    fines_by_participant = sorted(
        [FineByStat(name=n, count=int(v["count"]), amount=float(v["amount"])) for n, v in per_participant.items()],
        key=lambda x: x.count,
        reverse=True,
    )
    fines_by_type = [
        FineTypeStat(fine_type=t, label=fine_type_labels.get(t, t), count=int(v["count"]), amount=float(v["amount"]))
        for t, v in per_type.items()
    ]

    # ── Finance by month ─────────────────────────────────────────────────────
    finance_rows = db.execute(
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

    finance_by_month = [
        FinanceMonthStat(
            month=r.month,
            account_id=r.account_id,
            account_name=r.account_name,
            income=float(r.income or 0),
            expenses=float(r.expenses or 0),
            net=float(r.income or 0) - float(r.expenses or 0),
        )
        for r in finance_rows
    ]

    # ── Participants ─────────────────────────────────────────────────────────
    participants = db.execute(
        select(Participant.is_active).where(Participant.tenant_id == tenant_id)
    ).all()
    participants_total = len(participants)
    participants_active = sum(1 for p in participants if p.is_active)

    return StatisticsOverview(
        attendance_by_participant=attendance_by_participant,
        attendance_over_time=attendance_over_time,
        todos=todos_summary,
        fines_by_participant=fines_by_participant,
        fines_by_type=fines_by_type,
        finance_by_month=finance_by_month,
        participants_total=participants_total,
        participants_active=participants_active,
        protocols_total=protocols_total,
        cycles=cycles,
        groups_stats=groups_stats,
    )
