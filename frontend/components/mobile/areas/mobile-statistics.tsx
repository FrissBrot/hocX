"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { MobileCard, MobileCardHeader, MobileEmpty, MobileSegmented, MobileSubHeader, MobileSwitch } from "@/components/mobile/mobile-ui";
import { Badge } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { AttendanceMonthChart, ChartLegend, DivergingMonthChart, ProgressBar, StackedBar, percentLabel } from "@/components/statistics/statistics-bars";
import {
  LOW_ATTENDANCE_RATE,
  attendanceBars,
  attendanceRate,
  financeView,
  fineSum,
  fineTypeRows,
  finesByPerson,
  groupRows,
  mainAmount,
  memberRows,
  sumAttendance,
  trendOf,
  yearMonths,
} from "@/components/statistics/statistics-model";
import { useStatisticsFormat } from "@/components/statistics/use-statistics-format";
import { useStatisticsOverview } from "@/components/statistics/use-statistics-overview";
import type { StatisticsOverview } from "@/types/api";

const MEMBER_PREVIEW = 5;
const FINE_PEOPLE_PREVIEW = 3;

/** Statistik auf dem Smartphone (Dashboard v2): gleiche Zahlen wie Desktop, untereinander. */
export function MobileStatistics({ data: initialData, year: initialYear, today }: { data: StatisticsOverview | null; year: number; today: string }) {
  const t = useTranslations("statistics");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const router = useRouter();
  const fmt = useStatisticsFormat();
  const { year, setYear, compare, setCompare, canCompare, years, data, failed } = useStatisticsOverview(initialData, initialYear);
  const [sort, setSort] = useState<"low" | "high">("low");
  const [allMembers, setAllMembers] = useState(false);

  const months = useMemo(() => yearMonths(year, today), [year, today]);
  const comparison = compare ? data?.comparison ?? null : null;
  const bars = useMemo(() => attendanceBars(data?.attendance_over_time ?? [], comparison?.attendance_over_time ?? null, months), [data, comparison, months]);
  const finance = useMemo(() => (data ? financeView({ finance_by_month: data.finance_by_month, comparison }, "all", months) : null), [data, comparison, months]);

  const back = <MobileSubHeader title={t("pageTitle")} backLabel={tMobile("tabs.overview")} onBack={() => router.push("/" as Route)} />;
  if (!data) {
    return (
      <div className="mobile-page">
        {back}
        <MobileEmpty title={failed ? t("loadFailed") : t("emptyTitle")} hint={t("emptyDescription")} />
      </div>
    );
  }

  const ownScope = data.per_person_scope === "own";
  const finesVisible = data.fines_visible !== false;
  const isRunning = year === Number(today.slice(0, 4));
  const intro = isRunning
    ? t("yearIntroRunning", { year, from: fmt.month(months[0]), to: fmt.month(months[months.length - 1]) })
    : t("yearIntro", { year, from: fmt.month(months[0]), to: fmt.month(months[months.length - 1]) });
  const previousPeriod = data.comparison ? fmt.period(data.comparison.period_start.slice(0, 7), data.comparison.period_end.slice(0, 7)) : "";
  const yearOptions = [...years].sort((a, b) => b - a).slice(0, 3).map((value) => ({ value: String(value), label: String(value) }));

  const totals = sumAttendance(data.attendance_over_time);
  const rate = attendanceRate(totals);
  const previousTotals = comparison ? sumAttendance(comparison.attendance_over_time) : null;
  const previousRate = previousTotals ? attendanceRate(previousTotals) : null;
  const avgPresent = data.protocols_total > 0 ? (totals.present + totals.late) / data.protocols_total : null;
  const previousAvg = previousTotals && comparison && comparison.protocols_total > 0 ? (previousTotals.present + previousTotals.late) / comparison.protocols_total : null;
  const todoRate = data.todos.total > 0 ? data.todos.done / data.todos.total : null;

  type Kpi = { label: string; value: string; sub: string; delta?: { text: string; good: boolean; flat: boolean } };
  const kpis: Kpi[] = [
    {
      label: t("kpiAttendanceRate"),
      value: percentLabel(rate, locale),
      sub: t("kpiAttendanceRateSubShort"),
      ...(rate !== null && previousRate !== null
        ? { delta: fmt.delta(trendOf(rate, previousRate), t("deltaVsPrevious", { delta: t("deltaPoints", { delta: fmt.signed(Math.round((rate - previousRate) * 100), 0) }) })) }
        : {}),
    },
    {
      label: t("kpiAvgPresentShort"),
      value: fmt.number(avgPresent, 1),
      sub: t("kpiAvgPresentSubShort"),
      ...(avgPresent !== null && previousAvg !== null ? { delta: fmt.delta(trendOf(avgPresent, previousAvg), t("deltaVsPrevious", { delta: fmt.signed(avgPresent - previousAvg, 1) })) } : {}),
    },
    { label: t("kpiSessionsShort"), value: fmt.number(data.protocols_total, 0), sub: t("kpiSessionsSubShort") },
    { label: t("kpiTodosDone"), value: percentLabel(todoRate, locale), sub: t("kpiTodosDoneSub", { count: data.todos.open }) },
  ];

  const members = memberRows(data.attendance_by_participant, sort);
  const shownMembers = allMembers ? members : members.slice(0, MEMBER_PREVIEW);

  const fineTotals = fineSum(data);
  const previousFineTotals = comparison ? fineSum({ fines_by_type: comparison.fines_by_type, fines_by_participant: comparison.own_fines, per_person_scope: data.per_person_scope }) : null;
  const types = fineTypeRows(data);
  const typeMax = Math.max(0, ...types.map((row) => mainAmount(row.totals)));
  const finePeople = ownScope ? [] : finesByPerson(data.fines_by_participant).slice(0, FINE_PEOPLE_PREVIEW);
  const groups = groupRows(data.groups_stats);
  const showFinance = finance !== null && (data.finance_by_month.length > 0 || (comparison?.finance_by_account.length ?? 0) > 0);

  return (
    <div className="mobile-page mobile-page-list">
      {back}
      <div className="mobile-section stats-mobile">
        <p className="mobile-muted-sm">{intro}</p>
        <MobileSegmented ariaLabel={t("yearSelectLabel")} value={String(year)} onChange={(value) => setYear(Number(value))} options={yearOptions} />
        <button type="button" className="mobile-card stats-mobile-compare" aria-pressed={compare} disabled={!canCompare} onClick={() => setCompare(!compare)}>
          <span className="stats-mobile-compare-text">
            <span className="stats-mobile-compare-title">{t("compareToggle")}</span>
            <span className="mobile-muted-sm">{canCompare ? t("compareSub", { period: previousPeriod || fmt.period(`${year - 1}-01`, `${year - 1}-12`) }) : t("compareUnavailable", { year: year - 1 })}</span>
          </span>
          <MobileSwitch checked={compare} />
        </button>
        {ownScope ? <StatusBanner tone="neutral" message={t("perPersonOwnShort")} /> : null}
        {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}

        <div className="mobile-stat-grid">
          {kpis.map((kpi) => (
            <div key={kpi.label} className="mobile-card mobile-stat stats-mobile-kpi">
              <div className="mobile-eyebrow">{kpi.label}</div>
              <div className="mobile-stat-value">{kpi.value}</div>
              {kpi.delta ? <Badge variant={kpi.delta.flat ? "neutral" : kpi.delta.good ? "success" : "danger"}>{kpi.delta.text}</Badge> : null}
              <div className="mobile-muted-sm">{kpi.sub}</div>
            </div>
          ))}
        </div>

        <MobileCard className="mobile-chart-card">
          <MobileCardHeader label={t("chartAttendancePerMonth")} />
          {data.attendance_over_time.length === 0 ? (
            <p className="mobile-card-empty">{t("noAttendanceDataPeriod")}</p>
          ) : (
            <AttendanceMonthChart
              compact
              bars={bars}
              locale={locale}
              title={(bar) => t("monthTooltip", { month: fmt.monthYear(bar.month), rate: percentLabel(bar.rate, locale) })}
            />
          )}
          <ChartLegend
            items={[
              { series: "present", label: t("present") },
              { series: "late", label: t("late") },
              { series: "excused", label: t("excused") },
              { series: "absent", label: t("absent") },
              ...(comparison ? [{ series: "previous" as const, label: t("previousYear") }] : []),
            ]}
          />
        </MobileCard>

        <MobileCard className="mobile-list-card">
          <MobileCardHeader
            label={t("membersShort")}
            action={
              ownScope ? undefined : (
                <MobileSegmented
                  compact
                  ariaLabel={t("sortLabel")}
                  value={sort}
                  onChange={setSort}
                  options={[
                    { value: "low", label: t("sortLowShort") },
                    { value: "high", label: t("sortHighShort") },
                  ]}
                />
              )
            }
          />
          {members.length === 0 ? <p className="mobile-card-empty">{t("noAttendanceData")}</p> : null}
          {shownMembers.map((row) => (
            <div key={row.name} className="stats-mobile-member">
              <div className="stats-mobile-member-head">
                <span>{row.name}</span>
                <span className={`stats-row-value${row.rate < LOW_ATTENDANCE_RATE ? " stats-row-value-low" : ""}`}>{percentLabel(row.rate, locale)}</span>
              </div>
              <StackedBar
                segments={[
                  { series: "present", value: row.present },
                  { series: "late", value: row.late },
                  { series: "excused", value: row.excused },
                  { series: "absent", value: row.absent },
                ]}
              />
            </div>
          ))}
          {members.length > MEMBER_PREVIEW ? (
            <button type="button" className="mobile-text-button stats-mobile-more" onClick={() => setAllMembers(!allMembers)}>
              {allMembers ? t("showFewerMembers") : t("showAllMembers", { count: members.length })}
            </button>
          ) : null}
        </MobileCard>

        {finesVisible ? (
          <MobileCard className="mobile-list-card">
            <div className="stats-mobile-fines-head">
              <div>
                <div className="mobile-eyebrow">{ownScope ? t("kpiMyFines") : t("kpiFines")}</div>
                <div className="stats-mobile-total">{fmt.fineTotals(fineTotals)}</div>
              </div>
              {previousFineTotals ? <span className="mobile-muted-sm">{t("previousShort", { value: fmt.fineTotals(previousFineTotals) })}</span> : null}
            </div>
            <div className="stats-type-list stats-mobile-pad">
              {types.length === 0 ? <p className="mobile-card-empty">{t("noFines")}</p> : null}
              {types.map((row) => (
                <div key={row.fineType} className="stats-type">
                  <div className="stats-type-head">
                    <span>{row.fineType === "absent" || row.fineType === "late" ? t(`fineType.${row.fineType}`) : row.fineType}</span>
                    <span className="stats-type-figures">
                      {t("fineTypeCount", { count: row.count })} · <strong>{fmt.fineTotals(row.totals)}</strong>
                    </span>
                  </div>
                  <ProgressBar value={typeMax > 0 ? mainAmount(row.totals) / typeMax : 0} series={row.fineType === "late" ? "late" : "absent"} />
                </div>
              ))}
            </div>
            {finePeople.map((row) => (
              <div key={row.key} className="stats-mobile-row">
                <span className="stats-mobile-row-name">{row.name}</span>
                <span className="mobile-muted-sm">{t("fineTypeCount", { count: row.count })}</span>
                <span className="stats-mobile-row-amount">{fmt.fineTotals(row.totals)}</span>
              </div>
            ))}
          </MobileCard>
        ) : null}

        {showFinance && finance ? (
          <MobileCard className="mobile-chart-card">
            <MobileCardHeader label={t("financeAllAccountsTitle")} />
            <div className="stats-mobile-finance-totals">
              {[
                { key: "income", label: t("income"), value: fmt.money(finance.income, finance.currency ?? ""), previous: finance.previous ? fmt.money(finance.previous.income, finance.currency ?? "") : null, tone: "" },
                { key: "expenses", label: t("expenses"), value: fmt.money(finance.expenses, finance.currency ?? ""), previous: finance.previous ? fmt.money(finance.previous.expenses, finance.currency ?? "") : null, tone: "" },
                {
                  key: "net",
                  label: t("financeResult"),
                  value: fmt.signedMoney(finance.net, finance.currency ?? ""),
                  previous: finance.previous ? fmt.signedMoney(finance.previous.net, finance.currency ?? "") : null,
                  tone: finance.net >= 0 ? " stats-value-good" : " stats-value-bad",
                },
              ].map((item) => (
                <div key={item.key}>
                  <div className="mobile-muted-sm">{item.label}</div>
                  <div className={`stats-mobile-finance-value${item.tone}`}>{item.value}</div>
                  {item.previous ? <div className="mobile-muted-sm">{t("previousAbbrev", { value: item.previous })}</div> : null}
                </div>
              ))}
            </div>
            <div className="stats-panel-title">{t("financeResultPerMonth")}</div>
            <DivergingMonthChart
              compact
              months={finance.months}
              scale={finance.scale}
              locale={locale}
              title={(month) => t("financeMonthTooltip", { month: fmt.monthYear(month.month), value: fmt.signedMoney(month.net, finance.currency ?? "") })}
            />
          </MobileCard>
        ) : null}

        <MobileCard className="mobile-list-card">
          <div className="stats-mobile-groups-head">
            <div className="mobile-eyebrow">{t("sectionGroups")}</div>
            <div className="mobile-muted-sm">{t("groupsMobileIntro")}</div>
          </div>
          {groups.length === 0 ? <p className="mobile-card-empty">{data.groups_source_configured ? t("groupsEmptyNoEvents") : t("groupsEmptyNoSource")}</p> : null}
          {groups.map((row) => (
            <div key={row.name} className="stats-mobile-row">
              <span className="stats-mobile-row-name">{row.name}</span>
              <span className="mobile-muted-sm">{t("groupSessionsCount", { count: row.sessions })}</span>
              <span className="stats-mobile-row-amount">{t("groupAvgValue", { value: fmt.number(row.avgParticipants, 1) })}</span>
            </div>
          ))}
        </MobileCard>
      </div>
    </div>
  );
}
