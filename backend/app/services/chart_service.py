"""Server-side chart generation using matplotlib for PDF embedding."""
from __future__ import annotations

import io
import textwrap
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import rcParams
from sqlalchemy.orm import Session

from app.services.statistics_common import (
    GROUPS_LIST_NAME,
    aggregate_attendance,
    aggregate_group_rows,
    aggregate_todo_counts,
    fetch_attendance_blocks,
    fetch_finance_by_month,
    fetch_fines_by_participant,
    fetch_fines_by_type,
    fetch_group_session_rows,
    fetch_todo_rows,
)

# GROUPS_LIST_NAME now lives in statistics_common.py (imported above) - that's the single
# shared source for both this module and app/api/routes/statistics.py (2026-08-13 audit,
# M10/M11). Kept importable from here too since chart_service historically was the source.

# ── Print-tuned defaults ──────────────────────────────────────────────────────

DPI = 300          # crisp at print resolution
A4_W = 6.3         # A4 text width in inches (~160 mm)
CHART_H = 3.4
CHART_H_TALL = 5.0

rcParams["font.family"] = "DejaVu Sans"

# Semantic fixed colors (these convey meaning and don't change with template)
C_PRESENT  = "#16a34a"   # green  – anwesend
C_LATE     = "#0ea5e9"   # blue   – verspätet
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
#
# All the actual DB reads/aggregation live in app/services/statistics_common.py, shared
# with app/api/routes/statistics.py's /statistics/overview endpoint - these functions just
# adapt the shared shapes to what the matplotlib renderers below expect (dicts instead of
# dataclasses/Rows, sorted+truncated to the top N for the chart). See statistics_common's
# module docstring (2026-08-12/13 audit, M4/M10/M11/M12).

def _fetch_attendance_data(db: Session, tenant_id: int) -> tuple[list[dict], list[dict]]:
    blocks = fetch_attendance_blocks(db, tenant_id)
    monthly, per_participant = aggregate_attendance(blocks)

    by_time = [
        {"month": m, "present": c.present, "late": c.late, "absent": c.absent, "excused": c.excused}
        for m, c in sorted(monthly.items())
    ]
    by_participant = sorted(
        [
            {
                "name": p.name,
                "present": p.counts.present,
                "late": p.counts.late,
                "absent": p.counts.absent,
                "excused": p.counts.excused,
                "total": p.counts.total,
            }
            for p in per_participant
        ],
        key=lambda x: x["total"],
        reverse=True,
    )[:15]
    return by_time, by_participant


def _fetch_finance_data(db: Session, tenant_id: int) -> list[dict]:
    rows = fetch_finance_by_month(db, tenant_id)
    return [{"month": r.month, "income": float(r.income or 0), "expenses": float(r.expenses or 0)} for r in rows]


def _fetch_fines_data(db: Session, tenant_id: int) -> tuple[list[dict], list[dict]]:
    participant_rows = fetch_fines_by_participant(db, tenant_id)
    type_rows = fetch_fines_by_type(db, tenant_id)

    by_participant = sorted(
        [{"name": r.name, "amount": float(r.amount or 0)} for r in participant_rows],
        key=lambda x: x["amount"],
        reverse=True,
    )[:10]
    fine_labels = {"absent": "Unentschuldigt", "late": "Verspätet"}
    by_type = [{"label": fine_labels.get(r.fine_type, r.fine_type), "count": r.count} for r in type_rows]
    return by_participant, by_type


def _fetch_todo_data(db: Session, tenant_id: int) -> dict:
    rows = fetch_todo_rows(db, tenant_id)
    open_, done = aggregate_todo_counts(rows)
    return {"done": done, "open": open_}


def _fetch_groups_data(db: Session, tenant_id: int, cycle_key: str | None = None) -> list[dict]:
    rows = fetch_group_session_rows(db, tenant_id)
    return aggregate_group_rows(rows, cycle_key)


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
        late    = [d["late"]    for d in by_time]
        excused = [d["excused"] for d in by_time]
        absent  = [d["absent"]  for d in by_time]
        bottom_late    = present
        bottom_excused = [p + l for p, l in zip(present, late)]
        bottom_absent  = [p + l + e for p, l, e in zip(present, late, excused)]
        xs = range(len(labels))
        fig, ax = plt.subplots(figsize=(A4_W, CHART_H))
        bar_w = 0.6
        b1 = ax.bar(xs, present, bar_w, color=C_PRESENT, label="Anwesend")
        b2 = ax.bar(xs, late,    bar_w, bottom=bottom_late,    color=C_LATE,    label="Verspätet")
        b3 = ax.bar(xs, excused, bar_w, bottom=bottom_excused, color=C_EXCUSED, label="Entschuldigt")
        b4 = ax.bar(xs, absent,  bar_w, bottom=bottom_absent,  color=C_ABSENT,  label="Abwesend")
        ax.set_xticks(list(xs))
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=6.5)
        ax.set_xlim(-0.6, len(xs) - 0.4)
        _setup_ax(ax)
        _legend(ax, handles=[b1, b2, b3, b4], ncol=4)
        fig.tight_layout(pad=0.4)
        return _fig_to_bytes(fig)

    if chart_type == "attendance_by_participant":
        _, by_participant = _fetch_attendance_data(db, tenant_id)
        if not by_participant:
            return _empty_chart("Keine Anwesenheitsdaten")
        names   = [textwrap.shorten(d["name"], 22) for d in by_participant]
        present = [d["present"] for d in by_participant]
        late    = [d["late"]    for d in by_participant]
        excused = [d["excused"] for d in by_participant]
        absent  = [d["absent"]  for d in by_participant]
        left_late    = present
        left_excused = [p + l for p, l in zip(present, late)]
        left_absent  = [p + l + e for p, l, e in zip(present, late, excused)]
        ys = range(len(names))
        h = max(CHART_H, len(names) * 0.32)
        fig, ax = plt.subplots(figsize=(A4_W, h))
        bar_h = 0.55
        b1 = ax.barh(list(ys), present, bar_h, color=C_PRESENT, label="Anwesend")
        b2 = ax.barh(list(ys), late,    bar_h, left=left_late,    color=C_LATE,    label="Verspätet")
        b3 = ax.barh(list(ys), excused, bar_h, left=left_excused, color=C_EXCUSED, label="Entschuldigt")
        b4 = ax.barh(list(ys), absent,  bar_h, left=left_absent,  color=C_ABSENT,  label="Abwesend")
        ax.set_yticks(list(ys))
        ax.set_yticklabels(names, fontsize=6.5)
        ax.invert_yaxis()
        ax.set_ylim(len(ys) - 0.5, -0.5)
        _setup_ax_horizontal(ax)
        _legend(ax, handles=[b1, b2, b3, b4], ncol=4)
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
