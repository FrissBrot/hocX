from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.cycle_utils import format_cycle_name
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader
from app.models.entities import CycleConfig, Participant, Protocol
from app.services.statistics_common import (
    aggregate_attendance,
    aggregate_todo_counts,
    fetch_attendance_blocks,
    fetch_finance_by_account_month,
    fetch_fines_by_participant,
    fetch_fines_by_type,
    fetch_group_session_rows,
    fetch_group_tagged_cycles,
    fetch_todo_rows,
)

router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────────


class AttendanceStat(BaseModel):
    name: str
    present: int
    late: int
    absent: int
    excused: int
    total: int


class AttendanceMonth(BaseModel):
    month: str
    present: int
    late: int
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
    event_cycles_rows = fetch_group_tagged_cycles(db, tenant_id)
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
    group_rows = fetch_group_session_rows(db, tenant_id)

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
    attendance_blocks = fetch_attendance_blocks(db, tenant_id)
    monthly_att, per_participant_att = aggregate_attendance(attendance_blocks)

    attendance_by_participant = sorted(
        [
            AttendanceStat(
                name=p.name,
                present=p.counts.present,
                late=p.counts.late,
                absent=p.counts.absent,
                excused=p.counts.excused,
                total=p.counts.total,
            )
            for p in per_participant_att
        ],
        key=lambda x: x.name,
    )

    attendance_over_time = [
        AttendanceMonth(
            month=m,
            present=c.present,
            late=c.late,
            absent=c.absent,
            excused=c.excused,
            total=c.total,
        )
        for m, c in sorted(monthly_att.items())
    ]

    # ── Todos ────────────────────────────────────────────────────────────────
    todos = fetch_todo_rows(db, tenant_id)
    todo_open, todo_done = aggregate_todo_counts(todos)
    todos_summary = TodoSummary(open=todo_open, done=todo_done, total=len(todos))

    # ── Fines ────────────────────────────────────────────────────────────────
    fine_type_labels = {"absent": "Unentschuldigt", "late": "Verspätet"}
    fines_by_participant = sorted(
        [
            FineByStat(name=r.name, count=int(r.count), amount=float(r.amount or 0))
            for r in fetch_fines_by_participant(db, tenant_id)
        ],
        key=lambda x: x.count,
        reverse=True,
    )
    fines_by_type = [
        FineTypeStat(
            fine_type=r.fine_type,
            label=fine_type_labels.get(r.fine_type, r.fine_type),
            count=int(r.count),
            amount=float(r.amount or 0),
        )
        for r in fetch_fines_by_type(db, tenant_id)
    ]

    # ── Finance by month ─────────────────────────────────────────────────────
    finance_rows = fetch_finance_by_account_month(db, tenant_id)

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
