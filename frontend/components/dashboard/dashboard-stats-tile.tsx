"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { toIntlLocale } from "@/lib/utils/format";
import { browserApiFetch } from "@/lib/api/client";
import type { StatisticsOverview } from "@/types/api";

/** Kennzahlen der letzten 6 Monate - Desktop-Gegenstueck zu MobileStatsCard. */
export function DashboardStatsTile({ showFines }: { showFines: boolean }) {
  const t = useTranslations("dashboard");
  const locale = useLocale();
  const router = useRouter();
  const [data, setData] = useState<StatisticsOverview | null>(null);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<StatisticsOverview>("/api/statistics/overview")
      .then((overview) => {
        if (!cancelled) setData(overview);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data?.protocols_total) return null;
  const recent = (data.attendance_over_time ?? []).slice(-6);
  const totals = recent.reduce((sum, row) => ({ present: sum.present + row.present, total: sum.total + row.total }), { present: 0, total: 0 });
  const finesTotal = (data.fines_by_type ?? []).reduce((sum, row) => sum + row.amount, 0);
  const money = finesTotal.toLocaleString(toIntlLocale(locale), { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <section className="card dashboard-tile">
      <div className="dashboard-list-header">
        <div className="eyebrow">{t("statsEyebrow")}</div>
        <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/statistics")}>
          {t("allButton")}
        </button>
      </div>
      <div className="dashboard-kpis">
        <div>
          <div className="dashboard-kpi-value">{totals.total > 0 ? `${Math.round((totals.present / totals.total) * 100)}%` : "—"}</div>
          <div className="dashboard-list-row-sub">{t("statsAttendance")}</div>
        </div>
        <div>
          <div className="dashboard-kpi-value">{data.todos?.open ?? 0}</div>
          <div className="dashboard-list-row-sub">{t("statsTodosOpen")}</div>
        </div>
        {showFines ? (
          <div>
            <div className="dashboard-kpi-value">{money}</div>
            <div className="dashboard-list-row-sub">{t("statsFines")}</div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
