"use client";

import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// Verlaufsdiagramm der Admin-Analysen. Eigenes Modul, damit admin-analytics.tsx es per next/dynamic
// nachladen kann und recharts nicht im Seiten-Bundle landet (Muster admin-cashflow-chart.tsx).

export type AnalyticsChartSeries = { key: string; label: string; color: string; kind: "line" | "bar" };

type ChartRow = Record<string, string | number | null>;

function ChartTooltip({ active, payload, label, formatValue }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string; dataKey: string }[];
  label?: string;
  formatValue: (key: string, value: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="stats-tooltip">
      {label ? <div className="stats-tooltip-label">{label}</div> : null}
      {payload.map((entry) => (
        <div key={entry.dataKey} className="stats-tooltip-row">
          <span className="stats-tooltip-dot" style={{ background: entry.color }} />
          <span className="stats-tooltip-name">{entry.name}:</span>
          <span className="stats-tooltip-val">{formatValue(entry.dataKey, entry.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function AnalyticsChart({ rows, series, formatValue, formatAxis, describedBy, label }: {
  rows: ChartRow[];
  series: AnalyticsChartSeries[];
  formatValue: (key: string, value: number) => string;
  formatAxis: (value: number) => string;
  describedBy?: string;
  /** Zugänglicher Name des Diagramms (role="img" braucht einen, axe role-img-alt); Standard: Reihen */
  label?: string;
}) {
  return (
    <div className="admin-analytics-chart" aria-describedby={describedBy} aria-label={label ?? series.map((item) => item.label).join(", ")} role="img">
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} barSize={10} barGap={2}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="var(--muted)" minTickGap={16} />
          <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" width={64} tickFormatter={formatAxis} />
          <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTooltip formatValue={formatValue} />} />
          <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
          {series.map((item) =>
            item.kind === "bar" ? (
              <Bar key={item.key} isAnimationActive={false} dataKey={item.key} name={item.label} fill={item.color} radius={[4, 4, 0, 0]} />
            ) : (
              <Line key={item.key} isAnimationActive={false} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2} dot={false} connectNulls />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
