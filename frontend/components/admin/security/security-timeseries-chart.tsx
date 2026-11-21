"use client";

import { useTranslations } from "next-intl";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_COLORS } from "@/lib/constants/chart-colors";

// Fehlversuche/Anmeldungen in 5-Minuten-Abschnitten. Eigenes Modul, damit die Übersicht recharts per
// next/dynamic nachlädt (wie admin-cashflow-chart.tsx).

export type SecurityChartPoint = { label: string; failures: number; successes: number; blocked: number };

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="stats-tooltip">
      {label ? <div className="stats-tooltip-label">{label}</div> : null}
      {payload.map((entry) => (
        <div key={entry.name} className="stats-tooltip-row">
          <span className="stats-tooltip-dot" style={{ background: entry.color }} />
          <span className="stats-tooltip-name">{entry.name}:</span>
          <span className="stats-tooltip-val">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

export function SecurityTimeseriesChart({ data }: { data: SecurityChartPoint[] }) {
  const t = useTranslations("adminSecurity.overview.series");
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} barGap={0}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="var(--muted)" minTickGap={24} />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" width={40} allowDecimals={false} />
        <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTooltip />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        <Bar isAnimationActive={false} dataKey="failures" name={t("failures")} stackId="a" fill={CHART_COLORS.securityFailures} />
        <Bar isAnimationActive={false} dataKey="blocked" name={t("blocked")} stackId="a" fill={CHART_COLORS.securityBlocked} />
        <Bar isAnimationActive={false} dataKey="successes" name={t("successes")} stackId="a" fill={CHART_COLORS.securitySuccesses} />
      </BarChart>
    </ResponsiveContainer>
  );
}
