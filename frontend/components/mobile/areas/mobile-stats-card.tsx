"use client";

import { CSSProperties } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { MobileCard, MobileCardHeader } from "@/components/mobile/mobile-ui";
import { attendanceRate, countsOf, fineSum, monthLabel, percentLabel, sumAttendance } from "@/components/statistics/statistics-model";
import { useYearOverview } from "@/components/statistics/use-statistics-overview";
import { formatFineTotals } from "@/lib/utils/fine-stats";
import { formatMoney } from "@/lib/utils/format";

const BAR_MONTHS = 6;

/** Kompakte Statistik-Karte unten auf der Übersicht (Dashboard v2): laufendes Jahr. */
export function MobileStatsCard({ year }: { year: number }) {
  const t = useTranslations("mobile");
  const locale = useLocale();
  const router = useRouter();
  const data = useYearOverview(year);

  if (!data?.protocols_total) return null;
  const recent = (data.attendance_over_time ?? []).slice(-BAR_MONTHS);
  const rate = attendanceRate(sumAttendance(data.attendance_over_time ?? []));
  const finesVisible = data.fines_visible !== false;

  return (
    <MobileCard className="mobile-chart-card">
      <MobileCardHeader
        label={t("stats.cardTitleYear", { year })}
        action={
          <button type="button" className="mobile-text-button" onClick={() => router.push("/statistics" as Route)}>
            {t("common.all")}
          </button>
        }
      />
      {recent.length > 0 ? (
        <div className="mobile-bars" style={{ "--mobile-bar-count": recent.length } as CSSProperties}>
          {recent.map((row, index) => (
            <div key={row.month} className="mobile-bar">
              <span
                className={`mobile-bar-fill${index === recent.length - 1 ? "" : " mobile-bar-fill-soft"}`}
                style={{ height: `${Math.max(4, Math.round((attendanceRate(countsOf(row)) ?? 0) * 100))}%` }}
              />
              <span className="mobile-bar-label">{monthLabel(row.month, locale)}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mobile-stats-row">
        <div>
          <div className="mobile-stat-value">{percentLabel(rate, locale)}</div>
          <div className="mobile-muted-sm">{t("stats.present")}</div>
        </div>
        <div>
          <div className="mobile-stat-value">{data.todos?.open ?? 0}</div>
          <div className="mobile-muted-sm">{t("stats.todosOpen")}</div>
        </div>
        {finesVisible ? (
          <div>
            <div className="mobile-stat-value">{formatFineTotals(fineSum(data), (amount) => formatMoney(amount, "", locale))}</div>
            <div className="mobile-muted-sm">{t("stats.finesShort")}</div>
          </div>
        ) : null}
      </div>
    </MobileCard>
  );
}
