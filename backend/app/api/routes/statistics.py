import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cycle_utils import format_cycle_name
from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models.entities import CycleConfig, FinanceAccount, ListDefinition, Participant, Protocol
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.statistics_common import (
    chart_cycle_bounds,
    aggregate_attendance,
    aggregate_todo_counts,
    aggregate_todo_insights,
    calendar_year_bounds,
    fetch_attendance_blocks,
    fetch_finance_by_account_month,
    fetch_fines_by_participant,
    fetch_fines_by_type,
    fetch_fines_status,
    fetch_group_session_rows,
    fetch_group_tagged_cycles,
    fetch_protocol_years,
    fetch_todo_insight_rows,
    fetch_todo_rows,
    own_person_key,
    previous_year_bounds,
)
from app.services.todo_fine_service import today as today_local

router = APIRouter()
access_service = AccessService()


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
    # Währung des Kontos (MAIN-BE-019): pro Person und Währung eine Zeile; participant_key
    # fasst die Zeilen einer Person wieder zusammen (Namen sind nicht eindeutig).
    currency: str = ""
    participant_key: str = ""
    # Aufteilung nach Art (Dashboard v2: gestapelte Balken, «Meine Bussen» nach Art).
    absent_count: int = 0
    late_count: int = 0
    absent_amount: float = 0
    late_amount: float = 0


class FineTypeStat(BaseModel):
    fine_type: str
    label: str
    count: int
    amount: float
    currency: str = ""


class TodoSummary(BaseModel):
    open: int
    done: int
    total: int


class FinanceMonthStat(BaseModel):
    month: str
    account_id: uuid.UUID
    account_name: str
    # Währung des Kontos (Audit 07, C8: das Diagramm zeigte fest «CHF»).
    currency: str = ""
    income: float
    expenses: float
    net: float


class CycleInfo(BaseModel):
    cycle_config_id: uuid.UUID
    cycle_config_name: str
    cycle_year: int
    label: str


class GroupStat(BaseModel):
    group_name: str
    cycle_config_id: uuid.UUID | None
    cycle_year: int | None
    session_count: int
    session_count_with_participants: int
    avg_participants: float


class FineStatusStat(BaseModel):
    """Bezahlte (eingezogene) und offene Bussen je Währung."""
    currency: str = ""
    paid_count: int
    paid_amount: float
    open_count: int
    open_amount: float


class TodoPersonStat(BaseModel):
    name: str
    participant_key: str
    open: int
    overdue: int


class TodoInsightStat(BaseModel):
    overdue: int = 0
    # davon seit über TODO_LONG_OVERDUE_DAYS (30) Tagen überfällig
    overdue_long: int = 0
    avg_days_to_done: float | None = None
    open_by_person: list[TodoPersonStat] = []


class FinanceAccountTotal(BaseModel):
    account_id: uuid.UUID
    account_name: str
    currency: str = ""
    income: float
    expenses: float


class StatisticsComparison(BaseModel):
    """Kennzahlen desselben Zeitraums im Vorjahr («Mit Vorjahr vergleichen»). Es gelten dieselben
    Sichtbarkeitsregeln wie für den gewählten Zeitraum."""
    period_start: date
    period_end: date
    protocols_total: int
    attendance_over_time: list[AttendanceMonth]
    todos: TodoSummary
    todo_avg_days_to_done: float | None = None
    fines_by_type: list[FineTypeStat] = []
    # Nur die eigene Person, wenn per_person_scope == "own" («Meine Bussen» im Vorjahr).
    own_fines: list[FineByStat] = []
    finance_by_account: list[FinanceAccountTotal] = []


class StatisticsOverview(BaseModel):
    # "own": Bussen/Anwesenheit je Person enthalten nur die eigene Zeile (Datenschutz-Audit PRIV-001).
    per_person_scope: Literal["all", "own"] = "all"
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
    # Ob eine Liste als Gruppenquelle markiert ist - für den erklärenden Leerzustand (U5).
    groups_source_configured: bool = False
    # ── Dashboard v2 ──
    # Gewählter Zeitraum (year=...), sonst None (alle Daten bzw. Zyklus).
    period_start: date | None = None
    period_end: date | None = None
    # Jahre mit durchgeführten Protokollen plus das laufende Jahr (Jahresauswahl).
    available_years: list[int] = []
    # Bussen nur mit gebuchtem Finanzmodul (wie GET /fines); sonst sind alle Bussenfelder leer.
    fines_visible: bool = True
    fines_status: list[FineStatusStat] = []
    todo_insights: TodoInsightStat = TodoInsightStat()
    comparison: StatisticsComparison | None = None


# ── Endpoint ─────────────────────────────────────────────────────────────────


# Hintergrund-Abfragen offener Diagramme (cached=1) teilen sich das Ergebnis je Mandant und
# Auswahl für STATS_CACHE_SECONDS (Concurrency-Audit CONC-016: jede offene Protokollseite rechnete
# alle 15 s alle Anwesenheitsblöcke des Zyklus neu). Explizite Aktualisierungen rechnen frisch.
STATS_CACHE_SECONDS = 30


def _stats_cache_key(
    user: CurrentUser, cycle_config_id: uuid.UUID | None, cycle_offset: int, own_key: str | None, restricted: bool = False,
    year: int | None = None, compare: bool = False,
) -> str:
    # Der Schlüssel enthält die Sicht des Aufrufers (alle Personen oder nur die eigene, PRIV-001):
    # sonst bekäme ein Leser das von einem Admin berechnete Ergebnis mit allen Personen aus dem
    # Cache (und umgekehrt ein Admin das gefilterte eines Lesers).
    finance = user.can(P.FINANCES_READ)
    fines = user.has_feature("finance", write=False)
    scope = own_key or "all"
    if restricted:
        # Eingeschränkte Leser sehen nur Zahlen ihrer Vorlagen - eigener Eintrag je Konto.
        scope = f"{scope}:tpl{user.user_id}"
    period = f"y{year}:{int(compare)}" if year is not None else "-"
    return f"hocx:stats:{user.current_tenant_id}:{cycle_config_id or '-'}:{cycle_offset}:{period}:{int(finance)}{int(fines)}:{scope}"


@router.get("/statistics/overview", response_model=StatisticsOverview)
def get_statistics_overview(
    cycle_config_id: uuid.UUID | None = None,
    cycle_offset: Annotated[int, Query(ge=-3, le=0)] = 0,
    cached: bool = False,
    # Kalenderjahr (Dashboard v2); hat Vorrang vor cycle_config_id/cycle_offset.
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    # Vorjahresvergleich (nur zusammen mit year).
    compare: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    key = _stats_cache_key(
        user, cycle_config_id, cycle_offset, own_person_key(db, user), access_service.is_restricted_reader(db, user),
        year, compare,
    )
    if cached:
        try:
            raw = get_redis_sync().get(key)
        except RedisError:
            raw = None
        if raw:
            return StatisticsOverview.model_validate_json(raw)
    result = _compute_statistics_overview(db, user, cycle_config_id, cycle_offset, year=year, compare=compare)
    try:
        get_redis_sync().set(key, result.model_dump_json(), ex=STATS_CACHE_SECONDS)
    except RedisError:
        pass  # Cache ist best effort
    return result


def _compute_statistics_overview(
    db: Session, user: CurrentUser, cycle_config_id: uuid.UUID | None, cycle_offset: int,
    *, year: int | None = None, compare: bool = False,
) -> StatisticsOverview:
    tenant_id = user.current_tenant_id
    today = today_local()
    if year is not None:
        bounds = calendar_year_bounds(year)
    else:
        try:
            bounds = chart_cycle_bounds(db, tenant_id, cycle_config_id, cycle_offset)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Eingeschränkte Leser (nur bestimmten Vorlagen zugeordnet) sehen nur Zahlen aus diesen
    # Vorlagen (Audit 07, C9); None = alle Vorlagen des Mandanten.
    template_ids = access_service.readable_template_ids(db, user)

    # ── Protocols total ──────────────────────────────────────────────────────
    protocols_total = _protocols_total(db, tenant_id, bounds, template_ids)

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
                    cycle_config_id=cc.public_id,
                    cycle_config_name=cc.name,
                    cycle_year=ec.cycle_year,
                    label=format_cycle_name(cc.name_pattern or cc.name, ec.cycle_year),
                ))

    # ── Groups stats (event.tag matching an entry of a group-source list) ──
    group_rows = fetch_group_session_rows(db, tenant_id, bounds)
    groups_source_configured = db.scalar(
        select(ListDefinition.id).where(ListDefinition.tenant_id == tenant_id, ListDefinition.is_group_source.is_(True)).limit(1)
    ) is not None

    groups_stats = [
        GroupStat(
            group_name=r.group_name,
            cycle_config_id=cycle_configs[r.cycle_config_id].public_id if r.cycle_config_id in cycle_configs else None,
            cycle_year=r.cycle_year,
            session_count=int(r.session_count),
            session_count_with_participants=int(r.session_count_with_participants),
            avg_participants=float(r.avg_participants),
        )
        for r in group_rows
    ]

    # ── Attendance ───────────────────────────────────────────────────────────
    attendance_blocks = fetch_attendance_blocks(db, tenant_id, bounds, template_ids)
    monthly_att, per_participant_att = aggregate_attendance(attendance_blocks)
    # Leser sehen je Person nur sich selbst (PRIV-001), siehe statistics_common.own_person_key.
    own_key = own_person_key(db, user)
    sees_everyone = own_key is None

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
            if sees_everyone or p.key == own_key
        ],
        key=lambda x: x.name,
    )

    attendance_over_time = _attendance_months(monthly_att)

    # ── Todos ────────────────────────────────────────────────────────────────
    todos_summary = _todo_summary(db, tenant_id, bounds, template_ids)
    insights = aggregate_todo_insights(db, tenant_id, fetch_todo_insight_rows(db, tenant_id, bounds, template_ids), today)
    todo_insights = TodoInsightStat(
        overdue=insights.overdue,
        overdue_long=insights.overdue_long,
        avg_days_to_done=insights.avg_days_to_done,
        # Offene Pendenzen je Person: dieselbe Regel wie Anwesenheit/Bussen je Person (PRIV-001).
        open_by_person=[
            TodoPersonStat(name=item.name, participant_key=item.key, open=item.open, overdue=item.overdue)
            for item in insights.open_by_person
            if sees_everyone or item.key == own_key
        ],
    )

    # ── Fines ────────────────────────────────────────────────────────────────
    # Bussen nur mit gebuchtem Finanzmodul (lesend genügt), dieselbe Bedingung wie GET /fines.
    fines_visible = user.has_feature("finance", write=False)
    fines_by_participant = _fines_by_participant(db, tenant_id, bounds, template_ids, sees_everyone, own_key) if fines_visible else []
    fines_by_type = _fines_by_type(db, tenant_id, bounds, template_ids) if fines_visible else []
    # Bezahlt/offen: ohne Sicht auf alle Personen nur die eigenen Bussen.
    fines_status = [
        FineStatusStat(
            currency=r.currency or "",
            paid_count=int(r.paid_count), paid_amount=float(r.paid_amount or 0),
            open_count=int(r.open_count), open_amount=float(r.open_amount or 0),
        )
        for r in fetch_fines_status(db, tenant_id, bounds, template_ids, participant_id=None if sees_everyone else user.user_id)
    ] if fines_visible else []

    # ── Finance by month ─────────────────────────────────────────────────────
    # Finanzzahlen nur mit finances.read (inkl. gebuchtem Feature), wie die Finanzseite.
    can_read_finance = user.can(P.FINANCES_READ)
    finance_rows = fetch_finance_by_account_month(db, tenant_id, bounds) if can_read_finance else []
    account_public_ids = public_id_service.resolve_public_ids(db, FinanceAccount, [r.account_id for r in finance_rows])

    finance_by_month = [
        FinanceMonthStat(
            month=r.month,
            account_id=account_public_ids[r.account_id],
            account_name=r.account_name,
            currency=r.currency or "",
            income=float(r.income or 0),
            expenses=float(r.expenses or 0),
            net=float(r.income or 0) - float(r.expenses or 0),
        )
        for r in finance_rows
    ]

    # ── Participants ─────────────────────────────────────────────────────────
    participants = db.execute(
        select(Participant.is_active, Participant.left_at).where(Participant.tenant_id == tenant_id)
    ).all()
    participants_total = len(participants)
    # Aktiv = nicht deaktiviert und nicht ausgetreten (Austrittsdatum vor heute, wie has_left)
    participants_active = sum(1 for p in participants if p.is_active and (p.left_at is None or p.left_at >= today))

    # ── Jahre und Vorjahresvergleich (Dashboard v2) ─────────────────────────
    available_years = sorted({y for y in fetch_protocol_years(db, tenant_id, template_ids) if y <= today.year} | {today.year})
    comparison = None
    if year is not None and compare:
        comparison = _comparison(
            db, user, previous_year_bounds(year, today), template_ids,
            sees_everyone=sees_everyone, own_key=own_key, fines_visible=fines_visible, can_read_finance=can_read_finance,
        )

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
        groups_source_configured=groups_source_configured,
        per_person_scope="all" if sees_everyone else "own",
        period_start=bounds[0] if bounds else None,
        period_end=bounds[1] if bounds else None,
        available_years=available_years,
        fines_visible=fines_visible,
        fines_status=fines_status,
        todo_insights=todo_insights,
        comparison=comparison,
    )


# ── Bausteine, die aktueller Zeitraum und Vorjahr gemeinsam nutzen ─────────────────────────────

# label bleibt für ältere Clients; die Oberfläche übersetzt fine_type selbst (Audit 07, C8).
_FINE_TYPE_LABELS = {"absent": "Unentschuldigt", "late": "Verspätet"}


def _protocols_total(db: Session, tenant_id: int, bounds, template_ids) -> int:
    # Durchgeführte/abgeschlossene Protokolle im gewählten Zeitraum, wie die Anwesenheit (U6).
    conditions = [Protocol.tenant_id == tenant_id, Protocol.status.in_(["durchgeführt", "abgeschlossen"])]
    if bounds is not None:
        conditions += [Protocol.protocol_date >= bounds[0], Protocol.protocol_date <= bounds[1]]
    if template_ids is not None:
        conditions.append(Protocol.template_id.in_(template_ids))
    return db.scalar(select(func.count()).select_from(Protocol).where(*conditions)) or 0


def _attendance_months(monthly_att) -> list[AttendanceMonth]:
    return [
        AttendanceMonth(month=m, present=c.present, late=c.late, absent=c.absent, excused=c.excused, total=c.total)
        for m, c in sorted(monthly_att.items())
    ]


def _todo_summary(db: Session, tenant_id: int, bounds, template_ids) -> TodoSummary:
    todos = fetch_todo_rows(db, tenant_id, bounds, template_ids)
    todo_open, todo_done = aggregate_todo_counts(todos)
    return TodoSummary(open=todo_open, done=todo_done, total=len(todos))


def _fines_by_participant(db: Session, tenant_id: int, bounds, template_ids, sees_everyone: bool, own_key: str | None) -> list[FineByStat]:
    return sorted(
        [
            FineByStat(
                name=r.name, count=int(r.count), amount=float(r.amount or 0),
                currency=r.currency or "", participant_key=r.participant_key,
                absent_count=int(r.absent_count or 0), late_count=int(r.late_count or 0),
                absent_amount=float(r.absent_amount or 0), late_amount=float(r.late_amount or 0),
            )
            for r in fetch_fines_by_participant(db, tenant_id, bounds, template_ids)
            if sees_everyone or r.participant_key == own_key
        ],
        key=lambda x: x.count,
        reverse=True,
    )


def _fines_by_type(db: Session, tenant_id: int, bounds, template_ids) -> list[FineTypeStat]:
    return [
        FineTypeStat(
            fine_type=r.fine_type,
            label=_FINE_TYPE_LABELS.get(r.fine_type, r.fine_type),
            count=int(r.count),
            amount=float(r.amount or 0),
            currency=r.currency or "",
        )
        for r in fetch_fines_by_type(db, tenant_id, bounds, template_ids)
    ]


def _comparison(
    db: Session, user: CurrentUser, bounds: tuple[date, date], template_ids, *,
    sees_everyone: bool, own_key: str | None, fines_visible: bool, can_read_finance: bool,
) -> StatisticsComparison:
    """Vorjahr mit denselben Regeln wie der gewählte Zeitraum: Vorlagen-Filter für eingeschränkte
    Leser, Bussen nur mit Finanzmodul, Finanzen nur mit finances.read, je Person nur sich selbst
    ohne reports.personal."""
    tenant_id = user.current_tenant_id
    monthly_att, _ = aggregate_attendance(fetch_attendance_blocks(db, tenant_id, bounds, template_ids))
    insights = aggregate_todo_insights(db, tenant_id, fetch_todo_insight_rows(db, tenant_id, bounds, template_ids), today_local())
    finance_by_account: list[FinanceAccountTotal] = []
    if can_read_finance:
        totals: dict[int, dict] = {}
        for r in fetch_finance_by_account_month(db, tenant_id, bounds):
            item = totals.setdefault(r.account_id, {"name": r.account_name, "currency": r.currency or "", "income": 0.0, "expenses": 0.0})
            item["income"] += float(r.income or 0)
            item["expenses"] += float(r.expenses or 0)
        public_ids = public_id_service.resolve_public_ids(db, FinanceAccount, list(totals))
        finance_by_account = [
            FinanceAccountTotal(account_id=public_ids[account_id], account_name=v["name"], currency=v["currency"], income=v["income"], expenses=v["expenses"])
            for account_id, v in totals.items()
        ]
    return StatisticsComparison(
        period_start=bounds[0],
        period_end=bounds[1],
        protocols_total=_protocols_total(db, tenant_id, bounds, template_ids),
        attendance_over_time=_attendance_months(monthly_att),
        todos=_todo_summary(db, tenant_id, bounds, template_ids),
        todo_avg_days_to_done=insights.avg_days_to_done,
        fines_by_type=_fines_by_type(db, tenant_id, bounds, template_ids) if fines_visible else [],
        own_fines=_fines_by_participant(db, tenant_id, bounds, template_ids, False, own_key) if fines_visible and not sees_everyone else [],
        finance_by_account=finance_by_account,
    )
