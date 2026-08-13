"use client";

import { useEffect, useState } from "react";
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { StatisticsOverview } from "@/types/api";
import { browserApiFetch } from "@/lib/api/client";

const STATS_BUMP_EVENT = "hocx:stats-refresh";
let _statsVersion = 0;

export function bumpStatsCharts() {
  _statsVersion++;
  window.dispatchEvent(new Event(STATS_BUMP_EVENT));
}

// Every ChartBlock instance shows the same /api/statistics/overview data (there's no
// per-block query param), so a page with several chart blocks previously fired one
// identical request per block, per 15s tick. This module-level cache + a single shared
// poll timer (ref-counted across mounted instances) makes concurrent instances share one
// in-flight request/interval instead of each running its own.
let _statsCache: StatisticsOverview | null = null;
let _statsCacheVersion = -1;
// True once a refresh attempt has failed and fallen back to _statsCache - so the chart can
// still render (better than blanking out on a transient error), but the user is told the
// numbers on screen may no longer be current instead of that being silent.
let _statsCacheStale = false;
let _statsInFlight: { version: number; promise: Promise<{ data: StatisticsOverview | null; stale: boolean }> } | null = null;
let _statsPollInterval: ReturnType<typeof setInterval> | null = null;
let _statsPollRefCount = 0;

function acquireStatsPolling() {
  _statsPollRefCount++;
  if (!_statsPollInterval) {
    _statsPollInterval = setInterval(() => bumpStatsCharts(), 15_000);
  }
}

function releaseStatsPolling() {
  _statsPollRefCount = Math.max(0, _statsPollRefCount - 1);
  if (_statsPollRefCount === 0 && _statsPollInterval) {
    clearInterval(_statsPollInterval);
    _statsPollInterval = null;
  }
}

function fetchStatsOverview(version: number): Promise<{ data: StatisticsOverview | null; stale: boolean }> {
  if (_statsCacheVersion === version) return Promise.resolve({ data: _statsCache, stale: _statsCacheStale });
  if (_statsInFlight?.version === version) return _statsInFlight.promise;
  const promise = browserApiFetch<StatisticsOverview>(`/api/statistics/overview?_t=${version}`)
    .then((d) => {
      _statsCache = d ?? null;
      _statsCacheVersion = version;
      _statsCacheStale = false;
      return { data: _statsCache, stale: false };
    })
    .catch(() => {
      _statsCacheStale = _statsCache !== null;
      return { data: _statsCache, stale: _statsCacheStale };
    })
    .finally(() => {
      if (_statsInFlight?.version === version) _statsInFlight = null;
    });
  _statsInFlight = { version, promise };
  return promise;
}

const CHART_OPTIONS = [
  { value: "attendance_over_time", label: "Anwesenheit über Zeit" },
  { value: "attendance_by_participant", label: "Anwesenheit pro Mitglied" },
  { value: "finance_by_month", label: "Finanzen pro Monat" },
  { value: "fines_by_participant", label: "Bussen pro Mitglied" },
  { value: "fines_by_type", label: "Bussen nach Typ" },
  { value: "groups_sessions", label: "Termine pro Gruppe" },
  { value: "groups_avg", label: "Ø Teilnehmer pro Gruppe" },
  { value: "todos", label: "Todos Übersicht" },
];

const C = {
  present: "#22c55e", absent: "#ef4444", excused: "#f59e0b",
  income: "#22c55e", expenses: "#ef4444",
  done: "#22c55e", open: "#94a3b8",
  fines: "#f59e0b", sessions: "#6366f1", participants: "#06b6d4",
};
const PIE = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7"];

function fmtMonth(m: string) {
  const [y, mo] = m.split("-");
  return new Date(Number(y), Number(mo) - 1, 1).toLocaleDateString("de-CH", { month: "short", year: "2-digit" });
}

type Config = {
  chart_type?: string;
  cycle_key?: string;
};

type Props = {
  blockId: number;
  config: Config;
  editable: boolean;
  onSave: (cfg: Record<string, unknown>) => void;
};

export function ChartBlock({ blockId, config, editable, onSave }: Props) {
  const [data, setData] = useState<StatisticsOverview | null>(_statsCacheVersion >= 0 ? _statsCache : null);
  const [stale, setStale] = useState(_statsCacheStale);
  const [loading, setLoading] = useState(_statsCacheVersion < 0);
  const [tick, setTick] = useState(() => _statsVersion);
  const chartType = config.chart_type ?? "";
  const cycleKey = config.cycle_key ?? "all";

  useEffect(() => {
    const refresh = () => setTick(_statsVersion);
    window.addEventListener(STATS_BUMP_EVENT, refresh);
    acquireStatsPolling();
    return () => {
      window.removeEventListener(STATS_BUMP_EVENT, refresh);
      releaseStatsPolling();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (_statsCacheVersion !== tick) setLoading(true);
    fetchStatsOverview(tick).then(({ data: d, stale: s }) => {
      if (cancelled) return;
      setData(d);
      setStale(s);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  function save(partial: Partial<Config>) {
    onSave({ ...config, ...partial });
  }

  if (loading) return <div className="muted" style={{ padding: "12px 0" }}>Lade Daten…</div>;
  if (!data) return <div className="muted" style={{ padding: "12px 0" }}>Statistikdaten nicht verfügbar.</div>;

  const hasCycles = data.cycles.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {editable && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <select
            className="stats-cycle-select"
            value={chartType}
            onChange={(e) => save({ chart_type: e.target.value })}
            style={{ minWidth: 220 }}
          >
            <option value="">– Diagramm auswählen –</option>
            {CHART_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {hasCycles && (chartType === "groups_sessions" || chartType === "groups_avg") && (
            <select
              className="stats-cycle-select"
              value={cycleKey}
              onChange={(e) => save({ cycle_key: e.target.value })}
            >
              <option value="all">Alle Zyklen</option>
              {data.cycles.map((c) => {
                const k = `${c.cycle_config_id}:${c.cycle_year}`;
                return <option key={k} value={k}>{c.label}</option>;
              })}
            </select>
          )}
        </div>
      )}
      {!editable && !chartType && (
        <p className="muted">Kein Diagramm ausgewählt.</p>
      )}
      {stale && (
        <p className="muted" style={{ fontSize: 12 }}>
          ⚠ Aktualisierung fehlgeschlagen – zeige zwischengespeicherte Daten.
        </p>
      )}
      {chartType && <ChartPreview chartType={chartType} cycleKey={cycleKey} data={data} />}
    </div>
  );
}

function ChartPreview({ chartType, cycleKey, data }: { chartType: string; cycleKey: string; data: StatisticsOverview }) {
  const h = 220;

  if (chartType === "attendance_over_time") {
    const d = data.attendance_over_time.map((r) => ({ ...r, month: fmtMonth(r.month) }));
    if (!d.length) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={d} barSize={14}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" width={24} />
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="present" name="Anwesend" stackId="a" fill={C.present} />
          <Bar dataKey="excused" name="Entschuldigt" stackId="a" fill={C.excused} />
          <Bar dataKey="absent" name="Abwesend" stackId="a" fill={C.absent} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "attendance_by_participant") {
    const d = data.attendance_by_participant.slice(0, 15).map((r) => ({ name: r.name, Anwesend: r.present, Entschuldigt: r.excused, Abwesend: r.absent }));
    if (!d.length) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={Math.max(h, d.length * 28)}>
        <BarChart layout="vertical" data={d} barSize={10}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="Anwesend" stackId="a" fill={C.present} />
          <Bar dataKey="Entschuldigt" stackId="a" fill={C.excused} />
          <Bar dataKey="Abwesend" stackId="a" fill={C.absent} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "finance_by_month") {
    const d = data.finance_by_month.reduce<Record<string, { month: string; income: number; expenses: number }>>((acc, r) => {
      if (!acc[r.month]) acc[r.month] = { month: r.month, income: 0, expenses: 0 };
      acc[r.month].income += r.income;
      acc[r.month].expenses += r.expenses;
      return acc;
    }, {});
    const arr = Object.values(d).sort((a, b) => a.month.localeCompare(b.month)).map((r) => ({ ...r, month: fmtMonth(r.month) }));
    if (!arr.length) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={arr} barSize={14}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis tick={{ fontSize: 10 }} stroke="var(--muted)" width={40} />
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="income" name="Einnahmen" fill={C.income} radius={[4, 4, 0, 0]} />
          <Bar dataKey="expenses" name="Ausgaben" fill={C.expenses} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "fines_by_participant") {
    const d = data.fines_by_participant.slice(0, 10).map((f) => ({ name: f.name, Betrag: f.amount }));
    if (!d.length) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={Math.max(h, d.length * 28)}>
        <BarChart layout="vertical" data={d} barSize={12}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <Tooltip />
          <Bar dataKey="Betrag" fill={C.fines} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "fines_by_type") {
    const d = data.fines_by_type.map((f, i) => ({ name: f.label, value: f.count, color: PIE[i % PIE.length] }));
    if (!d.length) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <PieChart>
          <Pie data={d} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
            {d.map((e) => <Cell key={e.name} fill={e.color} />)}
          </Pie>
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "todos") {
    const d = [
      { name: "Erledigt", value: data.todos.done, color: C.done },
      { name: "Offen", value: data.todos.open, color: C.open },
    ];
    return (
      <ResponsiveContainer width="100%" height={h}>
        <PieChart>
          <Pie data={d} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
            {d.map((e) => <Cell key={e.name} fill={e.color} />)}
          </Pie>
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "groups_sessions" || chartType === "groups_avg") {
    let groups = data.groups_stats;
    if (cycleKey !== "all") {
      const [cid, yr] = cycleKey.split(":").map(Number);
      groups = groups.filter((g) => g.cycle_config_id === cid && g.cycle_year === yr);
    }
    const merged: Record<string, { name: string; sessions: number; sessions_with_p: number; weighted: number; sp: number }> = {};
    for (const g of groups) {
      if (!merged[g.group_name]) merged[g.group_name] = { name: g.group_name, sessions: 0, sessions_with_p: 0, weighted: 0, sp: 0 };
      merged[g.group_name].sessions += g.session_count;
      merged[g.group_name].sessions_with_p += g.session_count_with_participants;
      merged[g.group_name].weighted += g.avg_participants * g.session_count_with_participants;
      merged[g.group_name].sp += g.session_count_with_participants;
    }
    const d = Object.values(merged).sort((a, b) => b.sessions - a.sessions);
    if (!d.length) return <NoData />;

    if (chartType === "groups_sessions") {
      const arr = d.map((g) => ({ name: g.name, "Alle Termine": g.sessions, "Mit Teilnehmern": g.sessions_with_p }));
      return (
        <ResponsiveContainer width="100%" height={Math.max(h, d.length * 42)}>
          <BarChart layout="vertical" data={arr} barSize={10} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" />
            <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} stroke="var(--muted)" />
            <Tooltip />
            <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="Alle Termine" fill={C.sessions} opacity={0.5} radius={[0, 4, 4, 0]} />
            <Bar dataKey="Mit Teilnehmern" fill={C.sessions} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      );
    }

    const arr = d.map((g) => ({ name: g.name, "Ø Teilnehmer": g.sp > 0 ? Math.round(g.weighted / g.sp * 10) / 10 : 0 }));
    return (
      <ResponsiveContainer width="100%" height={Math.max(h, d.length * 32)}>
        <BarChart layout="vertical" data={arr} barSize={14}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <Tooltip />
          <Bar dataKey="Ø Teilnehmer" fill={C.participants} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  return <NoData />;
}

function NoData() {
  return <p className="muted" style={{ padding: "8px 0" }}>Keine Daten verfügbar.</p>;
}
