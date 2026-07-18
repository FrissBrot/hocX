"""Server-side chart generation using matplotlib for PDF embedding."""
from __future__ import annotations

import io
import textwrap
from collections import defaultdict
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import rcParams
from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.models.entities import (
    ElementType,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    AttendanceFine,
    FinanceTransaction,
    FinanceAccount,
    ProtocolTodo,
    TodoStatus,
)

# ── Print-tuned defaults ──────────────────────────────────────────────────────

DPI = 300          # crisp at print resolution
A4_W = 6.3         # A4 text width in inches (~160 mm)
CHART_H = 3.4
CHART_H_TALL = 5.0

rcParams["font.family"] = "DejaVu Sans"

# Semantic fixed colors (these convey meaning and don't change with template)
C_PRESENT  = "#16a34a"   # green  – anwesend
C_EXCUSED  = "#f59e0b"   # amber  – entschuldigt
C_ABSENT   = "#dc2626"   # red    – abwesend
C_INCOME   = "#16a34a"   # green  – einnahmen
C_EXPENSES = "#dc2626"   # red    – ausgaben
C_DONE     = "#16a34a"   # green  – erledigt
C_OPEN     = "#94a3b8"   # gray   – offen

# Template-derived defaults (overridden at render time from document template colors)
_DEFAULT_PRIMARY   = "#2563eb"
_DEFAULT_SECONDARY = "#6366f1"

_LABEL_COLOR = "#374151"
_AXIS_COLOR  = "#d1d5db"
_TICK_COLOR  = "#6b7280"


def _resolve_colors(opts: dict) -> tuple[str, str, list[str]]:
    """Return (primary, secondary, pie_palette) from options or defaults."""
    primary   = opts.get("primary_color")   or _DEFAULT_PRIMARY
    secondary = opts.get("secondary_color") or _DEFAULT_SECONDARY
    # Build a pie palette: primary, secondary, then fixed fallbacks
    pie_palette = [primary, secondary, "#f59e0b", "#dc2626", "#0891b2", "#a855f7", "#ec4899", "#84cc16"]
    return primary, secondary, pie_palette


# ── Axes style ────────────────────────────────────────────────────────────────

def _setup_ax(ax: plt.Axes, *, xlabel: str | None = None, ylabel: str | None = None) -> None:
    ax.set_facecolor("white")
    for spine in ax.spines.values():
        spine.set_visible(False)
    # keep only bottom axis line for bar charts
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color(_AXIS_COLOR)
    ax.spines["bottom"].set_linewidth(0.6)
    ax.tick_params(axis="both", length=0, labelsize=6.5, labelcolor=_TICK_COLOR, pad=4)
    ax.grid(False)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=7, color=_LABEL_COLOR, labelpad=6)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=7, color=_LABEL_COLOR, labelpad=6)


def _setup_ax_horizontal(ax: plt.Axes) -> None:
    """For horizontal bar charts: thin left spine instead of bottom."""
    ax.set_facecolor("white")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(_AXIS_COLOR)
    ax.spines["left"].set_linewidth(0.6)
    ax.tick_params(axis="both", length=0, labelsize=6.5, labelcolor=_TICK_COLOR, pad=4)
    ax.grid(False)


def _legend(ax: plt.Axes, handles=None, ncol: int | None = None) -> None:
    """Place a frameless horizontal legend below the axes."""
    entries = handles if handles else ax.get_legend_handles_labels()[0]
    n = ncol or len(entries) or 1
    kw = dict(
        fontsize=7,
        frameon=False,
        labelcolor=_LABEL_COLOR,
        handlelength=1.0,
        handletextpad=0.5,
        columnspacing=1.2,
        borderpad=0,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.06),
        ncol=n,
    )
    if handles:
        ax.legend(handles=handles, **kw)
    else:
        ax.legend(**kw)


def _fig_to_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _fmt_month(m: str) -> str:
    try:
        y, mo = m.split("-")
        import calendar
        return f"{calendar.month_abbr[int(mo)]} {y[2:]}"
    except Exception:
        return m


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _get_attendance_type_id(db: Session) -> int | None:
    row = db.execute(select(ElementType.id).where(ElementType.code == "attendance")).first()
    return row[0] if row else None


def _fetch_attendance_data(db: Session, tenant_id: int) -> tuple[list[dict], list[dict]]:
    attendance_type_id = _get_attendance_type_id(db)
    if not attendance_type_id:
        return [], []

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

    participant_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "absent": 0, "excused": 0})
    monthly_att: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "absent": 0, "excused": 0})

    for proto_date, config in rows:
        entries = (config or {}).get("attendance_entries", [])
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
                if status == "present":
                    monthly_att[month_key]["present"] += 1
                elif status == "excused":
                    monthly_att[month_key]["excused"] += 1
                else:
                    monthly_att[month_key]["absent"] += 1

    by_time = [{"month": m, **v} for m, v in sorted(monthly_att.items())]
    by_participant = sorted(
        [{"name": n, **v, "total": v["present"] + v["absent"] + v["excused"]} for n, v in participant_stats.items()],
        key=lambda x: x["total"],
        reverse=True,
    )[:15]
    return by_time, by_participant


def _fetch_finance_data(db: Session, tenant_id: int) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT to_char(ft.transaction_date,'YYYY-MM') AS month,
                   SUM(CASE WHEN ft.amount > 0 THEN ft.amount ELSE 0 END) AS income,
                   SUM(CASE WHEN ft.amount < 0 THEN ABS(ft.amount) ELSE 0 END) AS expenses
            FROM finance_transaction ft
            JOIN finance_account fa ON fa.id = ft.account_id
            WHERE fa.tenant_id = :tid
            GROUP BY month ORDER BY month
        """),
        {"tid": tenant_id},
    ).all()
    return [{"month": r.month, "income": float(r.income or 0), "expenses": float(r.expenses or 0)} for r in rows]


def _fetch_fines_data(db: Session, tenant_id: int) -> tuple[list[dict], list[dict]]:
    fines = db.execute(
        select(AttendanceFine.participant_name_snapshot, AttendanceFine.fine_type, AttendanceFine.amount)
        .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
        .where(Protocol.tenant_id == tenant_id)
    ).all()

    per_participant: dict[str, float] = defaultdict(float)
    per_type: dict[str, int] = defaultdict(int)
    for f in fines:
        per_participant[f.participant_name_snapshot] += float(f.amount)
        per_type[f.fine_type] += 1

    by_participant = sorted(
        [{"name": n, "amount": v} for n, v in per_participant.items()],
        key=lambda x: x["amount"],
        reverse=True,
    )[:10]
    fine_labels = {"absent": "Unentschuldigt", "late": "Verspätet"}
    by_type = [{"label": fine_labels.get(t, t), "count": c} for t, c in per_type.items()]
    return by_participant, by_type


def _fetch_todo_data(db: Session, tenant_id: int) -> dict:
    todos = db.execute(
        select(TodoStatus.code, ProtocolTodo.completed_at)
        .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .where(Protocol.tenant_id == tenant_id)
    ).all()
    done = sum(1 for t in todos if t.code in ("done", "cancelled") or t.completed_at)
    open_ = len(todos) - done
    return {"done": done, "open": open_}


def _fetch_groups_data(db: Session, tenant_id: int, cycle_key: str | None = None) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT e.tag AS group_name,
                   ec.cycle_config_id, ec.cycle_year,
                   COUNT(DISTINCT e.id) AS session_count,
                   COUNT(DISTINCT e.id) FILTER (WHERE e.participant_count > 0) AS session_count_with_participants,
                   COALESCE(AVG(e.participant_count) FILTER (WHERE e.participant_count > 0), 0) AS avg_participants
            FROM event e
            LEFT JOIN event_cycle ec ON ec.event_id = e.id
            WHERE e.tenant_id = :tid AND e.tag IS NOT NULL
              AND e.tag IN (
                  SELECT le.column_one_value_json->>'text_value'
                  FROM list_definition ld
                  JOIN list_entry le ON le.list_definition_id = ld.id
                  WHERE ld.tenant_id = :tid AND ld.name = 'Gruppen'
              )
            GROUP BY e.tag, ec.cycle_config_id, ec.cycle_year
        """),
        {"tid": tenant_id},
    ).all()

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
        s = int(r.session_count_with_participants)
        merged[n]["weighted"] += float(r.avg_participants) * s

    result = []
    for v in merged.values():
        v["avg"] = round(v["weighted"] / v["sessions_with_p"], 1) if v["sessions_with_p"] > 0 else 0.0
        result.append(v)
    return sorted(result, key=lambda x: x["sessions"], reverse=True)


# ── Chart renderers ───────────────────────────────────────────────────────────

def generate_chart_png(
    db: Session,
    tenant_id: int,
    chart_type: str,
    options: dict[str, Any] | None = None,
) -> bytes:
    opts = options or {}
    primary, secondary, pie_palette = _resolve_colors(opts)

    if chart_type == "attendance_over_time":
        by_time, _ = _fetch_attendance_data(db, tenant_id)
        if not by_time:
            return _empty_chart("Keine Anwesenheitsdaten")
        labels  = [_fmt_month(d["month"]) for d in by_time]
        present = [d["present"] for d in by_time]
        excused = [d["excused"] for d in by_time]
        absent  = [d["absent"]  for d in by_time]
        xs = range(len(labels))
        fig, ax = plt.subplots(figsize=(A4_W, CHART_H))
        bar_w = 0.6
        b1 = ax.bar(xs, present, bar_w, color=C_PRESENT, label="Anwesend")
        b2 = ax.bar(xs, excused, bar_w, bottom=present, color=C_EXCUSED, label="Entschuldigt")
        b3 = ax.bar(xs, absent,  bar_w, bottom=[p + e for p, e in zip(present, excused)], color=C_ABSENT, label="Abwesend")
        ax.set_xticks(list(xs))
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=6.5)
        ax.set_xlim(-0.6, len(xs) - 0.4)
        _setup_ax(ax)
        _legend(ax, handles=[b1, b2, b3], ncol=3)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "attendance_by_participant":
        _, by_participant = _fetch_attendance_data(db, tenant_id)
        if not by_participant:
            return _empty_chart("Keine Anwesenheitsdaten")
        names   = [textwrap.shorten(d["name"], 22) for d in by_participant]
        present = [d["present"] for d in by_participant]
        excused = [d["excused"] for d in by_participant]
        absent  = [d["absent"]  for d in by_participant]
        ys = range(len(names))
        h = max(CHART_H, len(names) * 0.32)
        fig, ax = plt.subplots(figsize=(A4_W, h))
        bar_h = 0.55
        b1 = ax.barh(list(ys), present, bar_h, color=C_PRESENT, label="Anwesend")
        b2 = ax.barh(list(ys), excused, bar_h, left=present, color=C_EXCUSED, label="Entschuldigt")
        b3 = ax.barh(list(ys), absent,  bar_h, left=[p + e for p, e in zip(present, excused)], color=C_ABSENT, label="Abwesend")
        ax.set_yticks(list(ys))
        ax.set_yticklabels(names, fontsize=6.5)
        ax.invert_yaxis()
        ax.set_ylim(len(ys) - 0.5, -0.5)
        _setup_ax_horizontal(ax)
        _legend(ax, handles=[b1, b2, b3], ncol=3)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "finance_by_month":
        data = _fetch_finance_data(db, tenant_id)
        if not data:
            return _empty_chart("Keine Finanzdaten")
        labels   = [_fmt_month(d["month"]) for d in data]
        income   = [d["income"]   for d in data]
        expenses = [d["expenses"] for d in data]
        xs = range(len(labels))
        w = 0.38
        fig, ax = plt.subplots(figsize=(A4_W, CHART_H))
        b1 = ax.bar([x - w / 2 for x in xs], income,   w, color=C_INCOME,   label="Einnahmen")
        b2 = ax.bar([x + w / 2 for x in xs], expenses, w, color=C_EXPENSES, label="Ausgaben")
        ax.set_xticks(list(xs))
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=6.5)
        ax.set_xlim(-0.6, len(xs) - 0.4)
        _setup_ax(ax)
        _legend(ax, handles=[b1, b2], ncol=2)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "fines_by_participant":
        by_participant, _ = _fetch_fines_data(db, tenant_id)
        if not by_participant:
            return _empty_chart("Keine Bussendaten")
        names   = [textwrap.shorten(d["name"], 22) for d in by_participant]
        amounts = [d["amount"] for d in by_participant]
        h = max(CHART_H, len(names) * 0.32)
        fig, ax = plt.subplots(figsize=(A4_W, h))
        ax.barh(names[::-1], amounts[::-1], 0.55, color=secondary)
        _setup_ax_horizontal(ax)
        ax.set_xlabel("Betrag (CHF)", fontsize=6.5, color=_LABEL_COLOR)
        for i, v in enumerate(amounts[::-1]):
            ax.text(v + max(amounts) * 0.01, i, f"{v:.2f}", va="center", fontsize=6, color=_TICK_COLOR)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "fines_by_type":
        _, by_type = _fetch_fines_data(db, tenant_id)
        if not by_type:
            return _empty_chart("Keine Bussendaten")
        labels = [d["label"] for d in by_type]
        counts = [d["count"] for d in by_type]
        colors = pie_palette[:len(counts)]
        fig, ax = plt.subplots(figsize=(A4_W * 0.65, CHART_H))
        _, _, autotexts = ax.pie(
            counts, colors=colors,
            autopct="%1.0f%%", pctdistance=0.72, startangle=90,
            wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
            textprops={"fontsize": 0},  # hide default labels; legend below carries them
        )
        for at in autotexts:
            at.set_fontsize(7)
            at.set_color("white")
            at.set_fontweight("bold")
        handles = [mpatches.Patch(color=c, label=l) for c, l in zip(colors, labels)]
        _legend(ax, handles=handles, ncol=len(labels))
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "todos":
        data = _fetch_todo_data(db, tenant_id)
        done, open_ = data["done"], data["open"]
        if done + open_ == 0:
            return _empty_chart("Keine Todos")
        fig, ax = plt.subplots(figsize=(A4_W * 0.55, CHART_H))
        colors = [C_DONE, C_OPEN]
        labels = [f"Erledigt ({done})", f"Offen ({open_})"]
        _, _, autotexts = ax.pie(
            [done, open_], colors=colors,
            autopct="%1.0f%%", pctdistance=0.72, startangle=90,
            wedgeprops={"width": 0.52, "linewidth": 1.5, "edgecolor": "white"},
            textprops={"fontsize": 0},
        )
        for at in autotexts:
            at.set_fontsize(7)
            at.set_color("white")
            at.set_fontweight("bold")
        handles = [mpatches.Patch(color=c, label=l) for c, l in zip(colors, labels)]
        _legend(ax, handles=handles, ncol=2)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "groups_sessions":
        cycle_key = opts.get("cycle_key")
        data = _fetch_groups_data(db, tenant_id, cycle_key)
        if not data:
            return _empty_chart("Keine Gruppendata")
        names           = [textwrap.shorten(d["name"], 22) for d in data]
        sessions        = [d["sessions"]        for d in data]
        sessions_with_p = [d["sessions_with_p"] for d in data]
        h = max(CHART_H, len(names) * 0.38)
        fig, ax = plt.subplots(figsize=(A4_W, h))
        ys, bh = range(len(names)), 0.32
        b1 = ax.barh([y + bh / 2 for y in ys], sessions,        bh, color=primary, alpha=0.35, label="Alle Termine")
        b2 = ax.barh([y - bh / 2 for y in ys], sessions_with_p, bh, color=primary, label="Mit Teilnehmern")
        ax.set_yticks(list(ys))
        ax.set_yticklabels(names, fontsize=6.5)
        ax.invert_yaxis()
        _setup_ax_horizontal(ax)
        _legend(ax, handles=[b1, b2], ncol=2)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "groups_avg":
        cycle_key = opts.get("cycle_key")
        data = _fetch_groups_data(db, tenant_id, cycle_key)
        if not data:
            return _empty_chart("Keine Gruppendata")
        names = [textwrap.shorten(d["name"], 22) for d in data]
        avgs  = [d["avg"] for d in data]
        h = max(CHART_H, len(names) * 0.32)
        fig, ax = plt.subplots(figsize=(A4_W, h))
        ax.barh(names[::-1], avgs[::-1], 0.55, color=secondary)
        _setup_ax_horizontal(ax)
        ax.set_xlabel("Ø Teilnehmer", fontsize=6.5, color=_LABEL_COLOR)
        max_v = max(avgs) if avgs else 1
        for i, v in enumerate(avgs[::-1]):
            ax.text(v + max_v * 0.01, i, f"{v:.1f}", va="center", fontsize=6, color=_TICK_COLOR)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    return _empty_chart(f"Unbekannter Diagrammtyp: {chart_type}")


def _empty_chart(msg: str) -> bytes:
    fig, ax = plt.subplots(figsize=(A4_W, 1.2))
    ax.text(0.5, 0.5, msg, ha="center", va="center",
            fontsize=8, color="#9ca3af", transform=ax.transAxes)
    ax.axis("off")
    return _fig_to_bytes(fig)
