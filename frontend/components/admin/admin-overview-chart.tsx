"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_COLORS } from "@/lib/constants/chart-colors";

// Diagramme der Admin-Übersicht. Eigenes Modul, damit admin-overview.tsx es per next/dynamic
// nachladen kann und recharts nicht im Seiten-Bundle landet (wie admin-cashflow-chart.tsx).

export type OverviewChartRow = { label: string; success?: number; failure?: number; errors?: number };

function ChartTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
}) {
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

export function OverviewBarChart({
  rows,
  series,
  describedBy,
}: {
  rows: OverviewChartRow[];
  series: { key: "success" | "failure" | "errors"; name: string }[];
  describedBy?: string;
}) {
  const colors = { success: CHART_COLORS.loginSuccess, failure: CHART_COLORS.loginFailure, errors: CHART_COLORS.errors };
  const stacked = series.length > 1;
  return (
    <div aria-describedby={describedBy}>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={rows} barGap={1}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="var(--muted)" minTickGap={16} />
          <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" width={40} allowDecimals={false} />
          <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTooltip />} />
          {stacked ? <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} /> : null}
          {series.map((entry, index) => (
            <Bar
              key={entry.key}
              isAnimationActive={false}
              dataKey={entry.key}
              name={entry.name}
              stackId={stacked ? "stack" : undefined}
              fill={colors[entry.key]}
              radius={!stacked || index === series.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
