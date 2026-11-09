"use client";

import { useLocale, useTranslations } from "next-intl";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_COLORS } from "@/lib/constants/chart-colors";
import { formatRappen } from "@/lib/utils/format";
import type { CashflowMonth } from "@/types/api";

// Monatsdiagramm der Plattform-Kasse. Eigenes Modul, damit admin-cashflow.tsx es per
// next/dynamic nachladen kann und recharts nicht im Seiten-Bundle landet.

type TFunc = ReturnType<typeof useTranslations>;

function ChartTooltip({ active, payload, label, locale }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  locale: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="stats-tooltip">
      {label ? <div className="stats-tooltip-label">{label}</div> : null}
      {payload.map((entry) => (
        <div key={entry.name} className="stats-tooltip-row">
          <span className="stats-tooltip-dot" style={{ background: entry.color }} />
          <span className="stats-tooltip-name">{entry.name}:</span>
          <span className="stats-tooltip-val">{formatRappen(Math.round(entry.value * 100), locale)}</span>
        </div>
      ))}
    </div>
  );
}

export function CashflowChart({ t, months, withPlanned, formatMonth }: {
  t: TFunc;
  months: CashflowMonth[];
  withPlanned: boolean;
  formatMonth: (month: string) => string;
}) {
  const locale = useLocale();
  const data = months.map((month) => ({
    month: formatMonth(month.month),
    income: month.income_rp / 100,
    expenses: (month.fixed_rp + month.percent_rp) / 100,
    planned: (month.planned_fixed_rp + month.planned_percent_rp) / 100,
  }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} barSize={16} barGap={2}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" width={56} />
        <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTooltip locale={locale} />} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: "var(--text-xs)" }} />
        <Bar isAnimationActive={false} dataKey="income" name={t("chart.income")} fill={CHART_COLORS.income} radius={[4, 4, 0, 0]} />
        <Bar isAnimationActive={false} dataKey="expenses" name={t("chart.expenses")} stackId="expenses" fill={CHART_COLORS.expenses} radius={withPlanned ? [0, 0, 0, 0] : [4, 4, 0, 0]} />
        {withPlanned ? (
          <Bar isAnimationActive={false} dataKey="planned" name={t("chart.planned")} stackId="expenses" fill="var(--chart-3)" radius={[4, 4, 0, 0]} />
        ) : null}
      </BarChart>
    </ResponsiveContainer>
  );
}
