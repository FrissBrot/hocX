"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { StatisticsOverview } from "@/types/api";
import { CHART_COLORS, CHART_PIE_PALETTE } from "@/lib/constants/chart-colors";
import { browserApiFetch } from "@/lib/api/client";
import { ChartCycleSelection } from "@/components/protocol/chart-cycle-selection";
import { SearchableSelect } from "@/components/ui/searchable-select";

const STATS_BUMP_EVENT = "hocx:stats-refresh";
let _statsVersion = 0;

export function bumpStatsCharts() {
  _statsVersion++;
  window.dispatchEvent(new Event(STATS_BUMP_EVENT));
}

// Diagramme mit derselben Zyklus-Auswahl teilen Cache, Anfrage und Polling.
type StatsResult = { data: StatisticsOverview | null; stale: boolean };
const statsCaches = new Map<string, { version: number; result: StatsResult }>();
const statsRequests = new Map<string, { version: number; promise: Promise<StatsResult> }>();
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

function fetchStatsOverview(version: number, scope: string): Promise<StatsResult> {
  const cached = statsCaches.get(scope);
  if (cached?.version === version) return Promise.resolve(cached.result);
  const request = statsRequests.get(scope);
  if (request?.version === version) return request.promise;
  const promise = browserApiFetch<StatisticsOverview>(`/api/statistics/overview?_t=${version}${scope}`)
    .then((data) => {
      const result = { data: data ?? null, stale: false };
      statsCaches.set(scope, { version, result });
      return result;
    })
    .catch(() => ({ data: cached?.result.data ?? null, stale: !!cached?.result.data }))
    .finally(() => { if (statsRequests.get(scope)?.version === version) statsRequests.delete(scope); });
  statsRequests.set(scope, { version, promise });
  return promise;
}

function chartOptions(t: (key: string) => string) {
  return [
    { value: "attendance_over_time", label: t("options.attendanceOverTime") },
    { value: "attendance_by_participant", label: t("options.attendanceByParticipant") },
    { value: "finance_by_month", label: t("options.financeByMonth") },
    { value: "fines_by_participant", label: t("options.finesByParticipant") },
    { value: "fines_by_type", label: t("options.finesByType") },
    { value: "groups_sessions", label: t("options.groupsSessions") },
    { value: "groups_avg", label: t("options.groupsAvg") },
    { value: "todos", label: t("options.todos") },
  ];
}

const C = CHART_COLORS;
const PIE = CHART_PIE_PALETTE;

function fmtMonth(m: string, locale: string) {
  const [y, mo] = m.split("-");
  return new Date(Number(y), Number(mo) - 1, 1).toLocaleDateString(`${locale}-CH`, { month: "short", year: "2-digit" });
}

type Config = {
  chart_type?: string;
  cycle_key?: string;
  cycle_config_id?: string | null;
  cycle_offset?: number;
};

type Props = {
  config: Config;
  editable: boolean;
  onSave: (cfg: Record<string, unknown>) => void;
};

export function ChartBlock({ config, editable, onSave }: Props) {
  const t = useTranslations("protocols.chart");
  const locale = useLocale();
  const scope = config.cycle_config_id ? `&cycle_config_id=${encodeURIComponent(config.cycle_config_id)}&cycle_offset=${config.cycle_offset ?? 0}` : "";
  const [data, setData] = useState<StatisticsOverview | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
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
    setLoading(true);
    fetchStatsOverview(tick, scope).then(({ data: d, stale: s }) => {
      if (cancelled) return;
      setData(d);
      setStale(s);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [tick, scope]);

  function save(partial: Partial<Config>) {
    onSave({ ...config, ...partial });
  }

  if (loading) return <div className="muted" style={{ padding: "var(--space-3) 0" }}>{t("loading")}</div>;
  if (!data) return <div className="muted" style={{ padding: "var(--space-3) 0" }}>{t("noData")}</div>;

  const hasCycles = data.cycles.length > 0;
  const cycleOptions = [
    { key: "all", label: t("allCycles") },
    ...data.cycles.map((c) => ({ key: `${c.cycle_config_id}:${c.cycle_year}`, label: c.label })),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {editable && (
        <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
          <select
            className="stats-cycle-select"
            value={chartType}
            onChange={(e) => save({ chart_type: e.target.value })}
            style={{ minWidth: 220 }}
          >
            <option value="">{t("selectPlaceholder")}</option>
            {chartOptions(t).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {!config.cycle_config_id && hasCycles && (chartType === "groups_sessions" || chartType === "groups_avg") && (
            <SearchableSelect
              className="stats-cycle-select"
              options={cycleOptions}
              getId={(o) => o.key}
              getLabel={(o) => o.label}
              value={cycleKey}
              onChange={(o) => save({ cycle_key: o ? o.key : "all" })}
            />
          )}
        </div>
      )}
      {editable && <ChartCycleSelection config={config} onChange={(partial) => save({ ...partial, cycle_key: "all" })} />}
      {!editable && !chartType && (
        <p className="muted">{t("noChartSelected")}</p>
      )}
      {stale && (
        <p className="muted" style={{ fontSize: "var(--text-xs)" }}>
          ⚠ {t("staleWarning")}
        </p>
      )}
      {chartType && <ChartPreview chartType={chartType} cycleKey={cycleKey} data={data} t={t} locale={locale} />}
    </div>
  );
}

function ChartPreview({ chartType, cycleKey, data, t, locale }: { chartType: string; cycleKey: string; data: StatisticsOverview; t: ReturnType<typeof useTranslations>; locale: string }) {
  const h = 220;

  if (chartType === "attendance_over_time") {
    const d = data.attendance_over_time.map((r) => ({ ...r, month: fmtMonth(r.month, locale) }));
    if (!d.length) return <NoData t={t} />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={d} barSize={14}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" width={24} />
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
          <Bar dataKey="present" name={t("series.present")} stackId="a" fill={C.present} />
          <Bar dataKey="excused" name={t("series.excused")} stackId="a" fill={C.excused} />
          <Bar dataKey="absent" name={t("series.absent")} stackId="a" fill={C.absent} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "attendance_by_participant") {
    const d = data.attendance_by_participant.slice(0, 15).map((r) => ({ name: r.name, present: r.present, excused: r.excused, absent: r.absent }));
    if (!d.length) return <NoData t={t} />;
    return (
      <ResponsiveContainer width="100%" height={Math.max(h, d.length * 28)}>
        <BarChart layout="vertical" data={d} barSize={10}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
          <Bar dataKey="present" name={t("series.present")} stackId="a" fill={C.present} />
          <Bar dataKey="excused" name={t("series.excused")} stackId="a" fill={C.excused} />
          <Bar dataKey="absent" name={t("series.absent")} stackId="a" fill={C.absent} radius={[0, 4, 4, 0]} />
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
    const arr = Object.values(d).sort((a, b) => a.month.localeCompare(b.month)).map((r) => ({ ...r, month: fmtMonth(r.month, locale) }));
    if (!arr.length) return <NoData t={t} />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={arr} barSize={14}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis tick={{ fontSize: 10 }} stroke="var(--muted)" width={40} />
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
          <Bar dataKey="income" name={t("series.income")} fill={C.income} radius={[4, 4, 0, 0]} />
          <Bar dataKey="expenses" name={t("series.expenses")} fill={C.expenses} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "fines_by_participant") {
    const d = data.fines_by_participant.slice(0, 10).map((f) => ({ name: f.name, amount: f.amount }));
    if (!d.length) return <NoData t={t} />;
    return (
      <ResponsiveContainer width="100%" height={Math.max(h, d.length * 28)}>
        <BarChart layout="vertical" data={d} barSize={12}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <Tooltip />
          <Bar dataKey="amount" name={t("series.amount")} fill={C.fines} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "fines_by_type") {
    const d = data.fines_by_type.map((f, i) => ({ name: f.label, value: f.count, color: PIE[i % PIE.length] }));
    if (!d.length) return <NoData t={t} />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <PieChart>
          <Pie data={d} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
            {d.map((e) => <Cell key={e.name} fill={e.color} />)}
          </Pie>
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "todos") {
    const d = [
      { name: t("series.done"), value: data.todos.done, color: C.done },
      { name: t("series.open"), value: data.todos.open, color: C.open },
    ];
    return (
      <ResponsiveContainer width="100%" height={h}>
        <PieChart>
          <Pie data={d} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
            {d.map((e) => <Cell key={e.name} fill={e.color} />)}
          </Pie>
          <Tooltip />
          <Legend iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "groups_sessions" || chartType === "groups_avg") {
    let groups = data.groups_stats;
    if (cycleKey !== "all") {
      const [cid, yr] = cycleKey.split(":");
      groups = groups.filter((g) => g.cycle_config_id === cid && g.cycle_year === Number(yr));
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
    if (!d.length) return <NoData t={t} />;

    if (chartType === "groups_sessions") {
      const arr = d.map((g) => ({ name: g.name, allSessions: g.sessions, withParticipants: g.sessions_with_p }));
      return (
        <ResponsiveContainer width="100%" height={Math.max(h, d.length * 42)}>
          <BarChart layout="vertical" data={arr} barSize={10} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" />
            <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} stroke="var(--muted)" />
            <Tooltip />
            <Legend iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
            <Bar dataKey="allSessions" name={t("series.allSessions")} fill={C.sessions} opacity={0.5} radius={[0, 4, 4, 0]} />
            <Bar dataKey="withParticipants" name={t("series.withParticipants")} fill={C.sessions} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      );
    }

    const arr = d.map((g) => ({ name: g.name, avgParticipants: g.sp > 0 ? Math.round(g.weighted / g.sp * 10) / 10 : 0 }));
    return (
      <ResponsiveContainer width="100%" height={Math.max(h, d.length * 32)}>
        <BarChart layout="vertical" data={arr} barSize={14}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} stroke="var(--muted)" />
          <Tooltip />
          <Bar dataKey="avgParticipants" name={t("series.avgParticipants")} fill={C.participants} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  return <NoData t={t} />;
}

function NoData({ t }: { t: ReturnType<typeof useTranslations> }) {
  return <p className="muted" style={{ padding: "var(--space-2) 0" }}>{t("noDataGeneric")}</p>;
}
