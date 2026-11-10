"use client";

import { useLocale, useTranslations } from "next-intl";
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

import { CHART_COLORS } from "@/lib/constants/chart-colors";
import { fmtAmount, fmtMonth, useChartHeight } from "@/components/statistics/statistics-chart-utils";

// Die recharts-Diagramme der Statistikseite. Eigenes Modul, damit statistics-view.tsx sie per
// next/dynamic nachladen kann und recharts nicht im Seiten-Bundle landet.

const COLORS = CHART_COLORS;

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

export type AttEntry = { month: string; present: number; absent: number; excused: number };
export function AttendanceTimeChart({ data }: { data: AttEntry[] }) {
  const t = useTranslations("statistics");
  const locale = useLocale();
  const h = useChartHeight(240);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data.map((d) => ({ ...d, month: fmtMonth(d.month, locale) }))} barSize={18}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" width={28} />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        <Bar dataKey="present" name={t("present")} stackId="a" fill={COLORS.present} />
        <Bar dataKey="excused" name={t("excused")} stackId="a" fill={COLORS.excused} />
        <Bar dataKey="absent" name={t("absent")} stackId="a" fill={COLORS.absent} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export type ParticipantAttEntry = { name: string; present: number; absent: number; excused: number };
export function AttendanceParticipantChart({ data }: { data: ParticipantAttEntry[] }) {
  const t = useTranslations("statistics");
  const h = useChartHeight(Math.max(240, data.length * 32), Math.max(480, data.length * 48));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data.map((d) => ({ name: d.name, present: d.present, excused: d.excused, absent: d.absent }))} barSize={14}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        <Bar dataKey="present" name={t("present")} stackId="a" fill={COLORS.present} />
        <Bar dataKey="excused" name={t("excused")} stackId="a" fill={COLORS.excused} />
        <Bar dataKey="absent" name={t("absent")} stackId="a" fill={COLORS.absent} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export type FinanceEntry = { month: string; income: number; expenses: number; net: number };
export function FinanceChart({ data }: { data: FinanceEntry[] }) {
  const t = useTranslations("statistics");
  const locale = useLocale();
  const h = useChartHeight(240);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data.map((d) => ({ ...d, month: fmtMonth(d.month, locale) }))} barSize={18}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" width={50} />
        <Tooltip content={<ChartTooltip formatter={(v) => `${fmtAmount(v, locale)} CHF`} />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        <Bar dataKey="income" name={t("income")} fill={COLORS.income} radius={[4, 4, 0, 0]} />
        <Bar dataKey="expenses" name={t("expenses")} fill={COLORS.expenses} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export type GroupEntry = { name: string; allSessions: number; withParticipants: number; avgParticipants: number };
export function GroupSessionsChart({ data }: { data: GroupEntry[] }) {
  const t = useTranslations("statistics");
  const h = useChartHeight(Math.max(220, data.length * 52), Math.max(480, data.length * 72));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data} barSize={14} barGap={3}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        <Bar dataKey="allSessions" name={t("allSessions")} fill={COLORS.sessions} radius={[0, 4, 4, 0]} opacity={0.5} />
        <Bar dataKey="withParticipants" name={t("withParticipants")} fill={COLORS.sessions} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GroupAvgChart({ data }: { data: GroupEntry[] }) {
  const t = useTranslations("statistics");
  const h = useChartHeight(Math.max(220, data.length * 40), Math.max(480, data.length * 60));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data} barSize={18}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip formatter={(v) => v.toFixed(1)} />} />
        <Bar dataKey="avgParticipants" name={t("avgParticipants")} fill={COLORS.participants} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export type PieEntry = { name: string; value: number; color: string };
export function PieDonutChart({ data }: { data: PieEntry[] }) {
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
            <span>{d.name} · {d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export type FineEntry = { name: string; count: number };
export function FinesParticipantChart({ data }: { data: FineEntry[] }) {
  const t = useTranslations("statistics");
  const h = useChartHeight(Math.max(220, data.length * 36), Math.max(480, data.length * 52));
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={data.map((f) => ({ name: f.name, count: f.count }))} barSize={14}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip content={<ChartTooltip />} />
        <Bar dataKey="count" name={t("count")} fill={COLORS.fines} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
