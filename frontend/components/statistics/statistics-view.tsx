"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { DocumentExportButton } from "@/components/documents/export-dialog";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { DocsLink, HelpPopover } from "@/components/ui/help-popover";
import { StatusBanner } from "@/components/ui/status-banner";
import type { StatisticsOverview } from "@/types/api";

import {
  AttendanceMonthChart,
  ChartLegend,
  DivergingMonthChart,
  DonutRing,
  OverlayBar,
  ProgressBar,
  StackedBar,
  percentLabel,
} from "./statistics-bars";
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
} from "./statistics-model";
import { useStatisticsOverview } from "./use-statistics-overview";
import { useStatisticsFormat } from "./use-statistics-format";

type Props = { data: StatisticsOverview | null; year: number; today: string };

const MEMBER_LIMIT = 8;
const PERSON_LIMIT = 8;

function SectionHeader({ title, intro, children }: { title: ReactNode; intro?: string; children?: ReactNode }) {
  return (
    <div className="stats-section-header">
      <div className="stats-section-heading">
        <h2 className="stats-section-title">{title}</h2>
        {intro ? <span className="stats-section-intro">{intro}</span> : null}
      </div>
      {children}
    </div>
  );
}

export function StatisticsView({ data: initialData, year: initialYear, today }: Props) {
  const t = useTranslations("statistics");
  const locale = useLocale();
  const router = useRouter();
  const fmt = useStatisticsFormat();
  const { year, setYear, compare, setCompare, canCompare, years, data, loading, failed } = useStatisticsOverview(initialData, initialYear);
  const [memberSort, setMemberSort] = useState<"low" | "high">("low");
  const [account, setAccount] = useState("all");

  const months = useMemo(() => yearMonths(year, today), [year, today]);
  const comparison = compare ? data?.comparison ?? null : null;
  const bars = useMemo(() => attendanceBars(data?.attendance_over_time ?? [], comparison?.attendance_over_time ?? null, months), [data, comparison, months]);
  const finance = useMemo(() => (data ? financeView({ finance_by_month: data.finance_by_month, comparison }, account, months) : null), [data, comparison, account, months]);

  if (!data) {
    return <StatusBanner tone="error" message={failed ? t("loadFailed") : t("noDataAvailable")} />;
  }

  const ownScope = data.per_person_scope === "own";
  const finesVisible = data.fines_visible !== false;
  const previousPeriod = comparison ? fmt.period(comparison.period_start.slice(0, 7), comparison.period_end.slice(0, 7)) : "";
  const introBase = year === Number(today.slice(0, 4))
    ? t("yearIntroRunning", { year, from: fmt.month(months[0]), to: fmt.month(months[months.length - 1]) })
    : t("yearIntro", { year, from: fmt.month(months[0]), to: fmt.month(months[months.length - 1]) });
  const intro = comparison ? t("yearIntroCompared", { intro: introBase, period: previousPeriod }) : introBase;
  const yearOptions = [...years].sort((a, b) => b - a).slice(0, 3).map((value) => ({ value: String(value), label: String(value) }));

  const header = (
    <div className="page-header stats-header">
      <div>
        <h1 className="page-title">{t("pageTitle")}</h1>
        <p className="muted">{intro}</p>
      </div>
      <div className="stats-header-actions" aria-busy={loading}>
        <FilterTabs options={yearOptions} value={String(year)} onChange={(value) => setYear(Number(value))} />
        <button
          type="button"
          className={`button-toggle stats-compare-toggle${compare ? " button-toggle-active" : ""}`}
          aria-pressed={compare}
          disabled={!canCompare}
          title={canCompare ? undefined : t("compareUnavailable", { year: year - 1 })}
          onClick={() => setCompare(!compare)}
        >
          <span className={`stats-switch${compare ? " stats-switch-on" : ""}`} aria-hidden="true" />
          {t("compareToggle")}
        </button>
        <DocumentExportButton context={{ documentType: "statistics" }} />
      </div>
    </div>
  );

  const hasData =
    data.protocols_total > 0 ||
    data.todos.total > 0 ||
    data.attendance_over_time.length > 0 ||
    data.fines_by_type.length > 0 ||
    data.finance_by_month.length > 0;

  if (!hasData) {
    return (
      <div className="stats-page">
        {header}
        <EmptyState
          title={t("emptyTitle")}
          description={years.length > 1 ? t("noDataForYear", { year }) : t("emptyDescription")}
          actions={
            <button type="button" className="button-primary" onClick={() => router.push("/protocols")}>
              {t("goToFirstProtocol")}
            </button>
          }
          hint={t("emptyHint")}
        />
      </div>
    );
  }

  // ── Kennzahlen ──
  const totals = sumAttendance(data.attendance_over_time);
  const rate = attendanceRate(totals);
  const previousTotals = comparison ? sumAttendance(comparison.attendance_over_time) : null;
  const previousRate = previousTotals ? attendanceRate(previousTotals) : null;
  const avgPresent = data.protocols_total > 0 ? (totals.present + totals.late) / data.protocols_total : null;
  const previousAvg = previousTotals && comparison && comparison.protocols_total > 0 ? (previousTotals.present + previousTotals.late) / comparison.protocols_total : null;
  const todoRate = data.todos.total > 0 ? data.todos.done / data.todos.total : null;
  const previousTodoRate = comparison && comparison.todos.total > 0 ? comparison.todos.done / comparison.todos.total : null;
  const fineTotals = fineSum(data);
  const previousFineTotals = comparison ? fineSum({ fines_by_type: comparison.fines_by_type, fines_by_participant: comparison.own_fines, per_person_scope: data.per_person_scope }) : null;
  const fineCount = fineTotals.reduce((sum, row) => sum + row.count, 0);
  const singleCurrency = fineTotals.length <= 1 && (previousFineTotals?.length ?? 0) <= 1 && (fineTotals[0]?.currency ?? "") === (previousFineTotals?.[0]?.currency ?? fineTotals[0]?.currency ?? "");

  type Kpi = { label: string; value: string; sub: string; delta?: { text: string; good: boolean; flat: boolean }; previous?: string };
  const kpis: Kpi[] = [
    {
      label: t("kpiAttendanceRate"),
      value: percentLabel(rate, locale),
      sub: t("kpiAttendanceRateSub"),
      ...(comparison && rate !== null && previousRate !== null
        ? { delta: fmt.delta(trendOf(rate, previousRate), t("deltaPoints", { delta: fmt.signed(Math.round((rate - previousRate) * 100), 0) })), previous: t("previousValue", { period: previousPeriod, value: percentLabel(previousRate, locale) }) }
        : {}),
    },
    {
      label: t("kpiAvgPresent"),
      value: fmt.number(avgPresent, 1),
      sub: t("kpiAvgPresentSub", { count: data.participants_active }),
      ...(comparison && avgPresent !== null && previousAvg !== null
        ? { delta: fmt.delta(trendOf(avgPresent, previousAvg), fmt.signed(avgPresent - previousAvg, 1)), previous: t("previousValue", { period: previousPeriod, value: fmt.number(previousAvg, 1) }) }
        : {}),
    },
    {
      label: t("kpiSessions"),
      value: fmt.number(data.protocols_total, 0),
      sub: t("kpiProtocolsSub"),
      ...(comparison ? { previous: t("previousValue", { period: previousPeriod, value: fmt.number(comparison.protocols_total, 0) }) } : {}),
    },
    {
      label: t("kpiTodosDone"),
      value: percentLabel(todoRate, locale),
      sub: t("kpiTodosDoneSub", { count: data.todos.open }),
      ...(comparison ? { previous: t("previousValue", { period: previousPeriod, value: percentLabel(previousTodoRate, locale) }) } : {}),
    },
  ];
  if (finesVisible) {
    const current = mainAmount(fineTotals);
    const previous = previousFineTotals ? mainAmount(previousFineTotals) : null;
    kpis.push({
      label: ownScope ? t("kpiMyFines") : t("kpiFines"),
      value: fmt.fineTotals(fineTotals),
      sub: t("kpiFinesSub", { count: fineCount }),
      ...(comparison && previousFineTotals
        ? {
            previous: t("previousValue", { period: previousPeriod, value: fmt.fineTotals(previousFineTotals) }),
            ...(singleCurrency && previous !== null && !ownScope ? { delta: fmt.delta(trendOf(current, previous, false), fmt.signedMoney(current - previous, fineTotals[0]?.currency ?? previousFineTotals[0]?.currency ?? "")) } : {}),
          }
        : {}),
    });
  }

  // ── Anwesenheit ──
  const members = memberRows(data.attendance_by_participant, memberSort);
  const lowMembers = members.filter((row) => row.rate < LOW_ATTENDANCE_RATE).length;

  // ── Pendenzen ──
  const insights = data.todo_insights ?? { overdue: 0, overdue_long: 0, avg_days_to_done: null, open_by_person: [] };
  const todoPeople = insights.open_by_person.slice(0, PERSON_LIMIT);
  const todoMax = Math.max(1, ...todoPeople.map((row) => row.open));
  const previousDays = comparison?.todo_avg_days_to_done ?? null;

  // ── Bussen ──
  const types = fineTypeRows(data);
  const typeMax = Math.max(0, ...types.map((row) => mainAmount(row.totals)));
  const status = data.fines_status ?? [];
  const paidTotals = status.map((row) => ({ currency: row.currency ?? "", count: row.paid_count, amount: row.paid_amount }));
  const openTotals = status.map((row) => ({ currency: row.currency ?? "", count: row.open_count, amount: row.open_amount }));
  const people = finesByPerson(data.fines_by_participant).slice(0, PERSON_LIMIT);
  const peopleMax = Math.max(0, ...people.map((row) => mainAmount(row.totals)));

  // ── Gruppen ──
  const groups = groupRows(data.groups_stats);
  const groupMax = Math.max(1, ...groups.map((row) => row.sessions));
  const groupsHelp = (
    <HelpPopover topic={t("sectionGroups")} docs={{ page: "statistik", anchor: "gruppen" }}>
      {t("groupsHelp")}
    </HelpPopover>
  );

  const showFinance = finance !== null && (data.finance_by_month.length > 0 || (comparison?.finance_by_account.length ?? 0) > 0);

  return (
    <div className="stats-page">
      {header}
      {ownScope ? <StatusBanner tone="neutral" message={t("perPersonOwnShort")} /> : null}
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}

      <div className="stats-kpi-grid">
        {kpis.map((kpi) => (
          <div key={kpi.label} className="card stats-kpi">
            <span className="stats-kpi-label">{kpi.label}</span>
            <div className="stats-kpi-value-row">
              <span className="stats-kpi-value">{kpi.value}</span>
              {kpi.delta ? (
                <Badge variant={kpi.delta.flat ? "neutral" : kpi.delta.good ? "success" : "danger"}>{kpi.delta.text}</Badge>
              ) : null}
            </div>
            <span className="stats-kpi-sub">{kpi.sub}</span>
            {kpi.previous ? <span className="stats-kpi-previous">{kpi.previous}</span> : null}
          </div>
        ))}
      </div>

      <section className="stats-section">
        <SectionHeader title={t("sectionAttendance")} intro={t("sectionAttendanceIntro")} />
        <div className="stats-grid stats-grid-wide">
          <div className="card stats-panel">
            <div className="stats-panel-header">
              <h3 className="stats-panel-title">{t("chartRatePerMonth")}</h3>
              <ChartLegend
                items={[
                  { series: "present", label: t("present") },
                  { series: "late", label: t("late") },
                  { series: "excused", label: t("excused") },
                  { series: "absent", label: t("absent") },
                ]}
              />
            </div>
            {data.attendance_over_time.length === 0 ? (
              <p className="stats-no-data">{t("noAttendanceDataPeriod")}</p>
            ) : (
              <AttendanceMonthChart
                bars={bars}
                locale={locale}
                title={(bar) =>
                  bar.previousRate !== null
                    ? t("monthTooltipPrevious", { month: fmt.monthYear(bar.month), rate: percentLabel(bar.rate, locale), previous: percentLabel(bar.previousRate, locale) })
                    : t("monthTooltip", { month: fmt.monthYear(bar.month), rate: percentLabel(bar.rate, locale) })
                }
              />
            )}
            {comparison ? (
              <div className="stats-note">
                <ChartLegend items={[{ series: "previous", label: t("previousYearMarker") }]} />
              </div>
            ) : null}
          </div>

          <div className="card stats-panel">
            <div className="stats-panel-header">
              <h3 className="stats-panel-title">{t("membersByRate")}</h3>
              {ownScope ? null : (
                <FilterTabs
                  options={[
                    { value: "low", label: t("sortLow") },
                    { value: "high", label: t("sortHigh") },
                  ]}
                  value={memberSort}
                  onChange={setMemberSort}
                />
              )}
            </div>
            {members.length === 0 ? (
              <p className="stats-no-data">{t("noAttendanceData")}</p>
            ) : (
              <div className="stats-rows">
                {members.slice(0, MEMBER_LIMIT).map((row) => (
                  <div
                    key={row.name}
                    className="stats-row"
                    title={t("memberTooltip", {
                      name: row.name,
                      present: percentLabel(row.present, locale),
                      late: percentLabel(row.late, locale),
                      excused: percentLabel(row.excused, locale),
                      absent: percentLabel(row.absent, locale),
                    })}
                  >
                    <span className="stats-row-name">{row.name}</span>
                    <StackedBar
                      segments={[
                        { series: "present", value: row.present },
                        { series: "late", value: row.late },
                        { series: "excused", value: row.excused },
                        { series: "absent", value: row.absent },
                      ]}
                    />
                    <span className={`stats-row-value${row.rate < LOW_ATTENDANCE_RATE ? " stats-row-value-low" : ""}`}>{percentLabel(row.rate, locale)}</span>
                  </div>
                ))}
              </div>
            )}
            <p className="stats-note">
              {ownScope ? t("membersOwnNote") : t("membersLowNote", { count: lowMembers, threshold: percentLabel(LOW_ATTENDANCE_RATE, locale) })}
            </p>
          </div>
        </div>
      </section>

      <section className="stats-section">
        <SectionHeader title={t("sectionTodos")} intro={t("sectionTodosIntro")} />
        <div className="stats-grid stats-grid-thirds">
          <div className="card stats-panel">
            <h3 className="stats-panel-title">{t("todoCompletionRate")}</h3>
            <div className="stats-ring-row">
              <DonutRing value={todoRate ?? 0}>
                <span className="stats-ring-value">{percentLabel(todoRate, locale)}</span>
                <span className="stats-ring-label">{t("todoDoneLower")}</span>
              </DonutRing>
              <div className="stats-ring-legend">
                <span className="stats-legend-item">
                  <span className="stats-legend-swatch stats-fill-done" aria-hidden="true" />
                  {t("todoDone")} <strong>{data.todos.done}</strong>
                </span>
                <span className="stats-legend-item">
                  <span className="stats-legend-swatch stats-fill-open" aria-hidden="true" />
                  {t("todoOpen")} <strong>{data.todos.open}</strong>
                </span>
              </div>
            </div>
          </div>

          <div className="card stats-panel stats-panel-split">
            <div className="stats-figure">
              <h3 className="stats-panel-title">{t("todoOverdue")}</h3>
              <span className={`stats-figure-value${insights.overdue > 0 ? " stats-figure-value-danger" : ""}`}>{insights.overdue}</span>
              <span className="stats-kpi-sub">{t("todoOverdueLong", { count: insights.overdue_long })}</span>
            </div>
            <div className="stats-figure">
              <h3 className="stats-panel-title">{t("todoAvgDays")}</h3>
              <div className="stats-kpi-value-row">
                <span className="stats-figure-value">{insights.avg_days_to_done !== null ? t("daysValue", { count: insights.avg_days_to_done }) : "–"}</span>
                {comparison && insights.avg_days_to_done !== null && previousDays !== null ? (
                  (() => {
                    const diff = Math.round((insights.avg_days_to_done - previousDays) * 10) / 10;
                    const delta = fmt.delta(trendOf(insights.avg_days_to_done, previousDays, false), t("deltaDays", { delta: fmt.signed(diff, 1), count: Math.abs(diff) }));
                    return <Badge variant={delta.flat ? "neutral" : delta.good ? "success" : "danger"}>{delta.text}</Badge>;
                  })()
                ) : null}
              </div>
            </div>
          </div>

          <div className="card stats-panel">
            <h3 className="stats-panel-title">{t("todoOpenPerPerson")}</h3>
            {todoPeople.length === 0 ? (
              <p className="stats-no-data">{t("noOpenTodos")}</p>
            ) : (
              <div className="stats-rows">
                {todoPeople.map((row) => (
                  <div key={row.participant_key} className="stats-row stats-row-narrow">
                    <span className="stats-row-name">{row.name}</span>
                    <StackedBar
                      mode="weight"
                      width={row.open / todoMax}
                      segments={[
                        { series: "absent", value: row.overdue },
                        { series: "onTrack", value: row.open - row.overdue },
                      ]}
                    />
                    <span className="stats-row-value">{row.open}</span>
                  </div>
                ))}
              </div>
            )}
            <ChartLegend
              items={[
                { series: "absent", label: t("todoOverdue") },
                { series: "onTrack", label: t("todoOnTrack") },
              ]}
            />
          </div>
        </div>
      </section>

      {finesVisible ? (
        <section className="stats-section">
          <SectionHeader title={t("sectionFines")} intro={t("sectionFinesIntro")} />
          <div className="stats-grid">
            <div className="card stats-panel">
              <h3 className="stats-panel-title">{t("finesByType")}</h3>
              {types.length === 0 ? (
                <p className="stats-no-data">{t("noFines")}</p>
              ) : (
                <div className="stats-type-list">
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
              )}
              {status.length > 0 ? (
                <div className="stats-paid">
                  <h3 className="stats-panel-title">{t("finesPaidOpen")}</h3>
                  <StackedBar
                    mode="weight"
                    className="stats-stack-tall"
                    segments={[
                      { series: "paid", value: mainAmount(paidTotals) },
                      { series: "finesOpen", value: mainAmount(openTotals) },
                    ]}
                  />
                  <div className="stats-paid-labels">
                    <span>{t("finesPaid", { amount: fmt.fineTotals(paidTotals) })}</span>
                    <span>{t("finesOpen", { amount: fmt.fineTotals(openTotals) })}</span>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="card stats-panel">
              <h3 className="stats-panel-title">{ownScope ? t("kpiMyFines") : t("finesPerPerson")}</h3>
              {people.length === 0 ? (
                <p className="stats-no-data">{t("noFines")}</p>
              ) : (
                <div className="stats-rows">
                  {people.map((row) => (
                    <div key={row.key} className="stats-row stats-row-amount">
                      <span className="stats-row-name">{row.name}</span>
                      <StackedBar
                        mode="weight"
                        width={peopleMax > 0 ? mainAmount(row.totals) / peopleMax : 0}
                        segments={[
                          { series: "absent", value: row.absent },
                          { series: "late", value: row.late },
                        ]}
                      />
                      <span className="stats-row-value">{fmt.fineTotals(row.totals)}</span>
                    </div>
                  ))}
                </div>
              )}
              <ChartLegend
                items={[
                  { series: "absent", label: t("fineType.absent") },
                  { series: "late", label: t("fineType.late") },
                ]}
              />
            </div>
          </div>
        </section>
      ) : null}

      {showFinance && finance ? (
        <section className="stats-section">
          <SectionHeader title={t("sectionFinance")} intro={t("sectionFinanceIntro")}>
            {finance.accounts.length > 1 ? (
              <FilterTabs
                options={[{ value: "all", label: t("allAccounts") }, ...finance.accounts.map((item) => ({ value: item.id, label: item.name }))]}
                value={account}
                onChange={setAccount}
              />
            ) : null}
          </SectionHeader>
          <div className="card stats-panel stats-finance">
            <div className="stats-finance-totals">
              {[
                { key: "income", label: t("income"), value: finance.income, previous: finance.previous?.income, sign: false },
                { key: "expenses", label: t("expenses"), value: finance.expenses, previous: finance.previous?.expenses, sign: false },
                { key: "net", label: t("financeResult"), value: finance.net, previous: finance.previous?.net, sign: true },
              ].map((item) => (
                <div key={item.key} className="stats-finance-total">
                  <span className="stats-kpi-label">{item.label}</span>
                  <div className="stats-kpi-value-row">
                    <span className={`stats-finance-value${item.sign ? (item.value >= 0 ? " stats-value-good" : " stats-value-bad") : ""}`}>
                      {item.sign ? fmt.signedMoney(item.value, finance.currency ?? "") : fmt.money(item.value, finance.currency ?? "")}
                    </span>
                    {item.previous !== undefined ? (
                      <span className="stats-kpi-sub">
                        {t("previousShort", { value: item.sign ? fmt.signedMoney(item.previous, finance.currency ?? "") : fmt.money(item.previous, finance.currency ?? "") })}
                      </span>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
            <div className="stats-finance-chart">
              <div className="stats-panel-header">
                <h3 className="stats-panel-title">{t("financeResultPerMonth")}</h3>
                <ChartLegend
                  items={[
                    { series: "surplus", label: t("financeSurplus") },
                    { series: "deficit", label: t("financeDeficit") },
                  ]}
                />
              </div>
              {data.finance_by_month.length === 0 ? (
                <p className="stats-no-data">{t("noFinanceData")}</p>
              ) : (
                <DivergingMonthChart
                  months={finance.months}
                  scale={finance.scale}
                  locale={locale}
                  axis={{ top: fmt.signed(finance.scale, 0), bottom: fmt.signed(-finance.scale, 0) }}
                  title={(month) => t("financeMonthTooltip", { month: fmt.monthYear(month.month), value: fmt.signedMoney(month.net, finance.currency ?? "") })}
                />
              )}
            </div>
          </div>
        </section>
      ) : null}

      <section className="stats-section">
        <SectionHeader title={<>{t("sectionGroups")} {groupsHelp}</>} intro={t("sectionGroupsIntro")} />
        {groups.length === 0 ? (
          <p className="muted">
            {data.groups_source_configured ? t("groupsEmptyNoEvents") : t("groupsEmptyNoSource")}{" "}
            <DocsLink page="statistik" anchor="gruppen">{t("groupsDocsLink")}</DocsLink>
          </p>
        ) : (
          <div className="card stats-panel">
            <div className="stats-groups" role="table">
              <div className="stats-groups-row stats-groups-head" role="row">
                <span role="columnheader">{t("groupColumn")}</span>
                <span role="columnheader">{t("groupSessionsColumn")}</span>
                <span role="columnheader" className="stats-groups-number">{t("groupAvgColumn")}</span>
              </div>
              {groups.map((row) => (
                <div key={row.name} className="stats-groups-row" role="row">
                  <span role="cell">{row.name}</span>
                  <span role="cell" className="stats-groups-bar">
                    <OverlayBar outer={row.sessions / groupMax} inner={row.withParticipants / groupMax} />
                    <span className="stats-groups-count">{t("groupSessionsValue", { with: row.withParticipants, all: row.sessions })}</span>
                  </span>
                  <span role="cell" className="stats-groups-number">{fmt.number(row.avgParticipants, 1)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

