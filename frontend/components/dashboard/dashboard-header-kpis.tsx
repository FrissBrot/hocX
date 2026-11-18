"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { attendanceRate, percentLabel, sumAttendance } from "@/components/statistics/statistics-model";
import { useYearOverview } from "@/components/statistics/use-statistics-overview";

/**
 * Kennzahlen des laufenden Jahres oben rechts auf der Startseite (Dashboard v2): Anwesenheit,
 * offene Pendenzen und - nur mit Finanzmodul - offene Bussen, dazu der Sprung in die Statistik.
 */
export function DashboardHeaderKpis({ year, fineTotalLabel, showFines }: { year: number; fineTotalLabel: string; showFines: boolean }) {
  const t = useTranslations("dashboard");
  const locale = useLocale();
  const data = useYearOverview(year);
  if (!data?.protocols_total) return null;
  const rate = attendanceRate(sumAttendance(data.attendance_over_time ?? []));

  return (
    <div className="dashboard-kpi-strip">
      <div className="dashboard-kpi">
        <span className="dashboard-kpi-value">{percentLabel(rate, locale)}</span>
        <span className="dashboard-kpi-label">{t("statsAttendance")}</span>
      </div>
      <div className="dashboard-kpi">
        <span className="dashboard-kpi-value">{data.todos?.open ?? 0}</span>
        <span className="dashboard-kpi-label">{t("statsTodosOpen")}</span>
      </div>
      {showFines ? (
        <div className="dashboard-kpi">
          <span className="dashboard-kpi-value">{fineTotalLabel}</span>
          <span className="dashboard-kpi-label">{t("statsFinesOpen")}</span>
        </div>
      ) : null}
      <Link href="/statistics" className="dashboard-kpi-link">
        {t("statisticsLink")}
        <span aria-hidden="true">→</span>
      </Link>
    </div>
  );
}
