"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { StatisticsOverview } from "@/types/api";

type Props = { data: StatisticsOverview | null };

const FullscreenCtx = createContext(false);
function useChartHeight(normal: number, fs = 480) {
  return useContext(FullscreenCtx) ? fs : normal;
}

const COLORS = {
  present: "#22c55e",
  absent: "#ef4444",
  excused: "#f59e0b",
  income: "#22c55e",
  expenses: "#ef4444",
  done: "#22c55e",
  open: "#94a3b8",
  fines: "#f59e0b",
  sessions: "#6366f1",
  participants: "#06b6d4",
};

const PIE_PALETTE = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7", "#ec4899", "#84cc16"];

function fmtMonth(m: string): string {
  const [y, mo] = m.split("-");
  return new Date(Number(y), Number(mo) - 1, 1).toLocaleDateString("de-CH", { month: "short", year: "2-digit" });
}

function fmtAmount(n: number): string {
  return n.toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

type Period = "all" | "12m" | "6m" | "3m";

function filterByPeriod<T extends { month: string }>(items: T[], period: Period): T[] {
  if (period === "all" || items.length === 0) return items;
  const months = period === "12m" ? 12 : period === "6m" ? 6 : 3;
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - months);
  return items.filter((i) => i.month >= cutoff.toISOString().slice(0, 7));
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="stats-card">
      <div className="stats-card-label">{label}</div>
      <div className="stats-card-value">{value}</div>
      {sub && <div className="stats-card-sub">{sub}</div>}
    </div>
  );
}

function ExpandIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <polyline points="10,2 14,2 14,6" />
      <polyline points="6,14 2,14 2,10" />
      <line x1="14" y1="2" x2="9" y2="7" />
      <line x1="2" y1="14" x2="7" y2="9" />
    </svg>
  );
}

type CycleOption = { value: string; label: string };
function CycleDropdown({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: CycleOption[] }) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!(e.target as Element).closest(".stats-cycle-dd")) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className="stats-cycle-dd">
      <button
        type="button"
        className={`stats-cycle-btn${open ? " stats-cycle-btn-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
      >
        <span>{current?.label}</span>
        <svg className={`stats-cycle-chevron${open ? " open" : ""}`} width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="2,4 6,8 10,4" />
        </svg>
      </button>
      {open && (
        <div className="stats-cycle-menu">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              className={`stats-cycle-item${o.value === value ? " active" : ""}`}
              onClick={() => { onChange(o.value); setOpen(false); }}
            >
              {o.value !== "all" && <span className="stats-cycle-dot" />}
              {o.label}
              {o.value === value && (
                <svg className="stats-cycle-check" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="2,6 5,9 10,3" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ChartCard({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (!fullscreen) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setFullscreen(false); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const overlay = fullscreen && typeof document !== "undefined" ? createPortal(
    <div className="stats-fs-backdrop" onClick={() => setFullscreen(false)}>
      <div className="stats-fs-card" onClick={(e) => e.stopPropagation()}>
        <div className="stats-fs-header">
          <span className="stats-chart-title">{title}</span>
          <button type="button" className="stats-fs-close" onClick={() => setFullscreen(false)} aria-label="Schliessen">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="3" x2="13" y2="13" /><line x1="13" y1="3" x2="3" y2="13" />
            </svg>
          </button>
        </div>
        <div className="stats-fs-content">
          <FullscreenCtx.Provider value={true}>{children}</FullscreenCtx.Provider>
        </div>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <div className={`stats-chart-card ${className}`}>
      <div className="stats-chart-header">
        <span className="stats-chart-title">{title}</span>
        <button type="button" className="stats-expand-btn" onClick={() => setFullscreen(true)} title="Vollbild">
          <ExpandIcon />
        </button>
      </div>
      {children}
      {overlay}
    </div>
  );
}

function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const options: { label: string; value: Period }[] = [
    { label: "3 Mo.", value: "3m" },
    { label: "6 Mo.", value: "6m" },
    { label: "12 Mo.", value: "12m" },
    { label: "Alles", value: "all" },
  ];
  return (
    <div className="stats-period-picker">
      {options.map((o) => (
        <button key={o.value} type="button" className={`stats-period-btn${value === o.value ? " stats-period-btn-active" : ""}`} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ChartTooltip({ active, payload, label, formatter }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  formatter?: (val: number, name: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="stats-tooltip">
      {label && <div className="stats-tooltip-label">{label}</div>}
      {payload.map((p) => (
        <div key={p.name} className="stats-tooltip-row">
          <span className="stats-tooltip-dot" style={{ background: p.color }} />
          <span className="stats-tooltip-name">{p.name}:</span>
          <span className="stats-tooltip-val">{formatter ? formatter(p.value, p.name) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Chart sub-components (need hooks for fullscreen height) ───────────────────

type AttEntry = { month: string; present: number; absent: number; excused: number };
function AttendanceTimeChart({ data }: { data: AttEntry[] }) {
  const h = useChartHeight(240);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data.map((d) => ({ ...d, month: fmtMonth(d.month) }))} barSize={18}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" width={28} />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="present" name="Anwesend" stackId="a" fill={COLORS.present} />
        <Bar dataKey="excused" name="Entschuldigt" stackId="a" fill={COLORS.excused} />
        <Bar dataKey="absent" name="Abwesend" stackId="a" fill={COLORS.absent} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

type ParticipantAttEntry = { name: string; present: number; absent: number; excused: number };
function AttendanceParticipantChart({ data }: { data: ParticipantAttEntry[] }) {
  const h = useChartHeight(Math.max(240, data.length * 32), Math.max(480, data.length * 48));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data.map((d) => ({ name: d.name, Anwesend: d.present, Entschuldigt: d.excused, Abwesend: d.absent }))} barSize={14}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Anwesend" stackId="a" fill={COLORS.present} />
        <Bar dataKey="Entschuldigt" stackId="a" fill={COLORS.excused} />
        <Bar dataKey="Abwesend" stackId="a" fill={COLORS.absent} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

type FinanceEntry = { month: string; income: number; expenses: number; net: number };
function FinanceChart({ data }: { data: FinanceEntry[] }) {
  const h = useChartHeight(240);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data.map((d) => ({ ...d, month: fmtMonth(d.month) }))} barSize={18}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" width={50} />
        <Tooltip content={<ChartTooltip formatter={(v) => `${fmtAmount(v)} CHF`} />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="income" name="Einnahmen" fill={COLORS.income} radius={[4, 4, 0, 0]} />
        <Bar dataKey="expenses" name="Ausgaben" fill={COLORS.expenses} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

type GroupEntry = { name: string; "Alle Termine": number; "Mit Teilnehmern": number; "Ø Teilnehmer": number };
function GroupSessionsChart({ data }: { data: GroupEntry[] }) {
  const h = useChartHeight(Math.max(220, data.length * 52), Math.max(480, data.length * 72));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data} barSize={14} barGap={3}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Alle Termine" fill={COLORS.sessions} radius={[0, 4, 4, 0]} opacity={0.5} />
        <Bar dataKey="Mit Teilnehmern" fill={COLORS.sessions} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function GroupAvgChart({ data }: { data: GroupEntry[] }) {
  const h = useChartHeight(Math.max(220, data.length * 40), Math.max(480, data.length * 60));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data} barSize={18}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip formatter={(v) => v.toFixed(1)} />} />
        <Bar dataKey="Ø Teilnehmer" fill={COLORS.participants} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

type PieEntry = { name: string; value: number; color: string };
function PieDonutChart({ data }: { data: PieEntry[] }) {
  const h = useChartHeight(200, 320);
  return (
    <div className="stats-pie-wrap">
      <ResponsiveContainer width="100%" height={h}>
        <PieChart>
          <Pie data={data} cx="50%" cy="50%" innerRadius={55} outerRadius={85} paddingAngle={3} dataKey="value">
            {data.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
          </Pie>
          <Tooltip formatter={(val) => [`${val}`, ""]} />
        </PieChart>
      </ResponsiveContainer>
      <div className="stats-pie-legend">
        {data.map((d) => (
          <div key={d.name} className="stats-pie-legend-row">
            <span className="stats-pie-dot" style={{ background: d.color }} />
            <span>{d.name}</span>
            <span className="stats-pie-val">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

type FineEntry = { name: string; count: number };
function FinesParticipantChart({ data }: { data: FineEntry[] }) {
  const h = useChartHeight(Math.max(220, data.length * 36), Math.max(480, data.length * 52));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data.map((f) => ({ name: f.name, Anzahl: f.count }))} barSize={14}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip />} />
        <Bar dataKey="Anzahl" fill={COLORS.fines} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────────

export function StatisticsView({ data }: Props) {
  const [period, setPeriod] = useState<Period>("all");
  const [attendanceView, setAttendanceView] = useState<"participant" | "time">("time");
  const [financeAccount, setFinanceAccount] = useState<string>("all");
  const [selectedCycle, setSelectedCycle] = useState<string>("all");

  if (!data) {
    return <div className="stats-empty"><p className="muted">Keine Statistikdaten verfügbar.</p></div>;
  }

  const attendanceTime = useMemo(() => filterByPeriod(data.attendance_over_time, period), [data, period]);
  const financeMonths = useMemo(() => {
    const byPeriod = filterByPeriod(data.finance_by_month, period);
    if (financeAccount === "all") {
      const merged: Record<string, { month: string; income: number; expenses: number; net: number }> = {};
      for (const r of byPeriod) {
        if (!merged[r.month]) merged[r.month] = { month: r.month, income: 0, expenses: 0, net: 0 };
        merged[r.month].income += r.income;
        merged[r.month].expenses += r.expenses;
        merged[r.month].net += r.net;
      }
      return Object.values(merged).sort((a, b) => a.month.localeCompare(b.month));
    }
    return byPeriod.filter((r) => r.account_name === financeAccount);
  }, [data, period, financeAccount]);

  const accounts = useMemo(() => [...new Set(data.finance_by_month.map((r) => r.account_name))], [data]);

  const groupsFiltered = useMemo(() => {
    const stats = data.groups_stats;
    if (selectedCycle === "all") {
      const merged: Record<string, { session_count: number; session_count_with_participants: number; weighted_participants: number; sessions_with_p: number }> = {};
      for (const g of stats) {
        if (!merged[g.group_name]) merged[g.group_name] = { session_count: 0, session_count_with_participants: 0, weighted_participants: 0, sessions_with_p: 0 };
        merged[g.group_name].session_count += g.session_count;
        merged[g.group_name].session_count_with_participants += g.session_count_with_participants;
        merged[g.group_name].weighted_participants += g.avg_participants * g.session_count_with_participants;
        merged[g.group_name].sessions_with_p += g.session_count_with_participants;
      }
      return Object.entries(merged).map(([name, v]) => ({
        name,
        "Alle Termine": v.session_count,
        "Mit Teilnehmern": v.session_count_with_participants,
        "Ø Teilnehmer": v.sessions_with_p > 0 ? Math.round((v.weighted_participants / v.sessions_with_p) * 10) / 10 : 0,
      })).sort((a, b) => b["Alle Termine"] - a["Alle Termine"]);
    }
    const [configId, year] = selectedCycle.split(":").map(Number);
    return stats
      .filter((g) => g.cycle_config_id === configId && g.cycle_year === year)
      .map((g) => ({
        name: g.group_name,
        "Alle Termine": g.session_count,
        "Mit Teilnehmern": g.session_count_with_participants,
        "Ø Teilnehmer": Math.round(g.avg_participants * 10) / 10,
      }))
      .sort((a, b) => b["Alle Termine"] - a["Alle Termine"]);
  }, [data, selectedCycle]);

  const todoData: PieEntry[] = [
    { name: "Erledigt", value: data.todos.done, color: COLORS.done },
    { name: "Offen", value: data.todos.open, color: COLORS.open },
  ];

  const fineTypeData: PieEntry[] = data.fines_by_type.map((f, i) => ({
    name: f.label,
    value: f.count,
    color: PIE_PALETTE[i % PIE_PALETTE.length],
  }));

  const top10Fines = data.fines_by_participant.slice(0, 10);
  const top15Attendance = data.attendance_by_participant.slice(0, 15);

  const hasCycles = data.cycles.length > 0;
  const hasGroups = data.groups_stats.length > 0;

  return (
    <div className="stats-page">

      {/* ── KPI row ── */}
      <div className="stats-kpi-row">
        <StatCard label="Protokolle" value={data.protocols_total} />
        <StatCard label="Mitglieder" value={data.participants_active} sub={`${data.participants_total} gesamt`} />
        <StatCard label="Todos" value={data.todos.total} sub={`${data.todos.open} offen`} />
        <StatCard label="Bussen gesamt" value={data.fines_by_participant.reduce((s, f) => s + f.count, 0)} />
        <StatCard label="Bussenbetrag" value={`${fmtAmount(data.fines_by_participant.reduce((s, f) => s + f.amount, 0))} CHF`} />
      </div>

      {/* ── Section: Gruppen ── */}
      {hasGroups && (
        <div className="stats-section">
          <div className="stats-section-header">
            <h2 className="stats-section-title">Gruppen</h2>
            {hasCycles && (
              <CycleDropdown
                value={selectedCycle}
                onChange={setSelectedCycle}
                options={[
                  { value: "all", label: "Alle Zyklen" },
                  ...data.cycles.map((c) => ({ value: `${c.cycle_config_id}:${c.cycle_year}`, label: c.label })),
                ]}
              />
            )}
          </div>

          <div className="stats-grid">
            <ChartCard title="Termine pro Gruppe">
              {groupsFiltered.length === 0
                ? <p className="stats-no-data">Keine Daten für diesen Zyklus.</p>
                : <GroupSessionsChart data={groupsFiltered} />}
            </ChartCard>

            <ChartCard title="Ø Teilnehmer pro Gruppe">
              {groupsFiltered.length === 0
                ? <p className="stats-no-data">Keine Daten für diesen Zyklus.</p>
                : <GroupAvgChart data={groupsFiltered} />}
            </ChartCard>
          </div>
        </div>
      )}

      {/* ── Section: Zeitreihen ── */}
      <div className="stats-section">
        <div className="stats-section-header">
          <h2 className="stats-section-title">Zeitverlauf</h2>
          <div className="stats-toolbar">
            <PeriodPicker value={period} onChange={setPeriod} />
          </div>
        </div>

        <div className="stats-grid">
          <ChartCard title="Anwesenheit" className="stats-chart-wide">
            <div className="stats-chart-toolbar">
              <div className="stats-segment">
                <button type="button" className={`stats-seg-btn${attendanceView === "time" ? " stats-seg-btn-active" : ""}`} onClick={() => setAttendanceView("time")}>Über Zeit</button>
                <button type="button" className={`stats-seg-btn${attendanceView === "participant" ? " stats-seg-btn-active" : ""}`} onClick={() => setAttendanceView("participant")}>Pro Mitglied</button>
              </div>
            </div>
            {attendanceView === "time" ? (
              attendanceTime.length === 0
                ? <p className="stats-no-data">Keine Anwesenheitsdaten im gewählten Zeitraum.</p>
                : <AttendanceTimeChart data={attendanceTime} />
            ) : (
              top15Attendance.length === 0
                ? <p className="stats-no-data">Keine Anwesenheitsdaten vorhanden.</p>
                : <AttendanceParticipantChart data={top15Attendance} />
            )}
          </ChartCard>

          {data.finance_by_month.length > 0 && (
            <ChartCard title="Finanzen pro Monat" className="stats-chart-wide">
              <div className="stats-chart-toolbar">
                {accounts.length > 1 && (
                  <div className="stats-segment">
                    <button type="button" className={`stats-seg-btn${financeAccount === "all" ? " stats-seg-btn-active" : ""}`} onClick={() => setFinanceAccount("all")}>Alle Konten</button>
                    {accounts.map((a) => (
                      <button key={a} type="button" className={`stats-seg-btn${financeAccount === a ? " stats-seg-btn-active" : ""}`} onClick={() => setFinanceAccount(a)}>{a}</button>
                    ))}
                  </div>
                )}
              </div>
              {financeMonths.length === 0
                ? <p className="stats-no-data">Keine Finanzdaten im gewählten Zeitraum.</p>
                : <FinanceChart data={financeMonths} />}
            </ChartCard>
          )}
        </div>
      </div>

      {/* ── Section: Übersicht ── */}
      <div className="stats-section">
        <div className="stats-section-header">
          <h2 className="stats-section-title">Übersicht</h2>
        </div>
        <div className="stats-grid">
          <ChartCard title="Todos Übersicht">
            <PieDonutChart data={todoData} />
          </ChartCard>

          {fineTypeData.length > 0 && (
            <ChartCard title="Bussen nach Typ">
              <PieDonutChart data={fineTypeData} />
            </ChartCard>
          )}

          {top10Fines.length > 0 && (
            <ChartCard title="Bussen pro Mitglied (Top 10)" className="stats-chart-wide">
              <FinesParticipantChart data={top10Fines} />
            </ChartCard>
          )}
        </div>
      </div>

    </div>
  );
}
