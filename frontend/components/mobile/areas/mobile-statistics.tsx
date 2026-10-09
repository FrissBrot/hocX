"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { CSSProperties, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileCard, MobileCardHeader, MobileEmpty, MobileListRow, MobileSegmented, MobileStat, MobileSubHeader } from "@/components/mobile/mobile-ui";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { toIntlLocale } from "@/lib/utils/format";
import type { StatisticsOverview } from "@/types/api";

type Period = "3m" | "6m" | "12m" | "all";
type Detail = "members" | "finance" | "fines" | "groups" | null;

function filterByPeriod<T extends { month: string }>(items: T[], period: Period): T[] {
  if (period === "all") return items;
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - (period === "12m" ? 12 : period === "6m" ? 6 : 3));
  return items.filter((item) => item.month >= cutoff.toISOString().slice(0, 7));
}

function monthShort(month: string, locale: string) {
  return new Intl.DateTimeFormat(toIntlLocale(locale), { month: "short" }).format(new Date(`${month}-01T12:00:00`)).replace(".", "");
}

function money(amount: number, locale: string) {
  return amount.toLocaleString(toIntlLocale(locale), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Saeulen pro Monat (Anwesenheitsquote) - die juengsten Monate rechts. */
export function MobileMonthBars({ items, locale }: { items: { month: string; value: number }[]; locale: string }) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="mobile-bars" style={{ "--mobile-bar-count": items.length } as CSSProperties}>
      {items.map((item) => (
        <div key={item.month} className="mobile-bar">
          <span className="mobile-bar-fill" style={{ height: `${Math.max(4, Math.round((item.value / max) * 100))}%` }} />
          <span className="mobile-bar-label">{monthShort(item.month, locale)}</span>
        </div>
      ))}
    </div>
  );
}

function HBar({ label, value, max, display, tone = "primary" }: { label: string; value: number; max: number; display: string; tone?: "primary" | "success" | "danger" }) {
  return (
    <div className="mobile-hbar">
      <div className="mobile-hbar-head">
        <span className="mobile-hbar-label">{label}</span>
        <span className="mobile-muted-sm">{display}</span>
      </div>
      <div className="mobile-progress-track">
        <span className={`mobile-hbar-fill-${tone}`} style={{ width: `${max > 0 ? Math.round((value / max) * 100) : 0}%` }} />
      </div>
    </div>
  );
}

function attendanceRate(row: { present: number; total: number }) {
  return row.total > 0 ? Math.round((row.present / row.total) * 100) : 0;
}

export function MobileStatistics({ data }: { data: StatisticsOverview | null }) {
  const t = useTranslations("statistics");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const router = useRouter();
  const [period, setPeriod] = useState<Period>("6m");
  const [detail, setDetail] = useState<Detail>(null);

  const attendance = useMemo(() => filterByPeriod(data?.attendance_over_time ?? [], period), [data, period]);
  const finance = useMemo(() => {
    const byMonth = new Map<string, { income: number; expenses: number }>();
    filterByPeriod(data?.finance_by_month ?? [], period).forEach((row) => {
      const current = byMonth.get(row.month) ?? { income: 0, expenses: 0 };
      byMonth.set(row.month, { income: current.income + row.income, expenses: current.expenses + Math.abs(row.expenses) });
    });
    return [...byMonth.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [data, period]);

  if (!data || data.protocols_total === 0) {
    return (
      <div className="mobile-page">
        <MobileSubHeader title={t("pageTitle")} backLabel={tMobile("tabs.overview")} onBack={() => router.push("/" as Route)} />
        <MobileEmpty title={t("emptyTitle")} hint={t("emptyDescription")} />
      </div>
    );
  }

  const finesTotal = data.fines_by_type.reduce((sum, row) => sum + row.amount, 0);
  const finesCount = data.fines_by_type.reduce((sum, row) => sum + row.count, 0);
  const members = [...data.attendance_by_participant].sort((a, b) => attendanceRate(b) - attendanceRate(a));
  const finesMax = Math.max(1, ...data.fines_by_type.map((row) => row.amount));
  const groupsMax = Math.max(1, ...data.groups_stats.map((row) => row.session_count));
  const financeMax = Math.max(1, ...finance.flatMap(([, row]) => [row.income, row.expenses]));

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("pageTitle")} subtitle={t("pageIntro")} backLabel={tMobile("tabs.overview")} onBack={() => router.push("/" as Route)} />
      <div className="mobile-section">
        <MobileSegmented<Period>
          ariaLabel={t("sectionTimeline")}
          value={period}
          onChange={setPeriod}
          options={[
            { value: "3m", label: t("period3m") },
            { value: "6m", label: t("period6m") },
            { value: "12m", label: t("period12m") },
            { value: "all", label: t("periodAll") },
          ]}
        />
        <div className="mobile-stat-grid">
          <MobileStat label={t("kpiProtocols")} value={data.protocols_total} />
          <MobileStat label={t("kpiMembers")} value={data.participants_active} sub={t("totalCountSub", { count: data.participants_total })} />
          <MobileStat label={t("kpiTodos")} value={data.todos.open} sub={tMobile("stats.todosDone", { count: data.todos.done })} />
          <MobileStat label={t("kpiFinesAmount")} value={money(finesTotal, locale)} sub={tMobile("stats.finesCount", { count: finesCount })} />
        </div>
        <MobileCard className="mobile-chart-card">
          <MobileCardHeader label={t("chartAttendance")} />
          {attendance.length > 0 ? (
            <MobileMonthBars items={attendance.map((row) => ({ month: row.month, value: attendanceRate(row) }))} locale={locale} />
          ) : (
            <p className="mobile-card-empty">{t("noAttendanceDataPeriod")}</p>
          )}
        </MobileCard>
        <div className="mobile-card mobile-group-card">
          <MobileListRow label={tMobile("stats.attendancePerMember")} onClick={() => setDetail("members")} />
          <MobileListRow label={t("chartFinancePerMonth")} onClick={() => setDetail("finance")} />
          <MobileListRow label={t("chartFinesByType")} onClick={() => setDetail("fines")} />
          <MobileListRow label={t("chartSessionsPerGroup")} onClick={() => setDetail("groups")} />
        </div>
      </div>

      {detail ? (
        <Modal
          open
          size="sheet"
          title={
            detail === "members" ? tMobile("stats.attendancePerMember") : detail === "finance" ? t("chartFinancePerMonth") : detail === "fines" ? t("chartFinesByType") : t("chartSessionsPerGroup")
          }
          onClose={() => setDetail(null)}
          className="mobile-sheet mobile-sheet-tall"
        >
          <div className="mobile-hbar-list">
            {detail === "members"
              ? members.map((row) => <HBar key={row.name} label={row.name} value={attendanceRate(row)} max={100} display={`${attendanceRate(row)}%`} tone="success" />)
              : null}
            {detail === "finance"
              ? finance.map(([month, row]) => (
                  <div key={month} className="mobile-hbar-group">
                    <div className="mobile-eyebrow">{new Intl.DateTimeFormat(toIntlLocale(locale), { month: "long", year: "numeric" }).format(new Date(`${month}-01T12:00:00`))}</div>
                    <HBar label={t("income")} value={row.income} max={financeMax} display={money(row.income, locale)} tone="success" />
                    <HBar label={t("expenses")} value={row.expenses} max={financeMax} display={money(row.expenses, locale)} tone="danger" />
                  </div>
                ))
              : null}
            {detail === "fines" ? data.fines_by_type.map((row) => <HBar key={row.fine_type} label={`${row.label} (${row.count})`} value={row.amount} max={finesMax} display={money(row.amount, locale)} tone="danger" />) : null}
            {detail === "groups" ? data.groups_stats.map((row, index) => <HBar key={`${row.group_name}-${index}`} label={row.group_name} value={row.session_count} max={groupsMax} display={String(row.session_count)} />) : null}
            {(detail === "finance" && finance.length === 0) || (detail === "members" && members.length === 0) ? <p className="mobile-card-empty">{t("noDataAvailable")}</p> : null}
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

/** Kompakte Statistik-Karte unten auf der Übersicht. */
export function MobileStatsCard() {
  const t = useTranslations("statistics");
  const tMobile = useTranslations("mobile");
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

  if (!data || data.protocols_total === 0) return null;
  const recent = data.attendance_over_time.slice(-6);
  const totals = recent.reduce((sum, row) => ({ present: sum.present + row.present, total: sum.total + row.total }), { present: 0, total: 0 });
  const finesTotal = data.fines_by_type.reduce((sum, row) => sum + row.amount, 0);

  return (
    <MobileCard className="mobile-chart-card">
      <MobileCardHeader
        label={tMobile("stats.cardTitle")}
        action={
          <button type="button" className="mobile-text-button" onClick={() => router.push("/statistics" as Route)}>
            {tMobile("common.all")}
          </button>
        }
      />
      {recent.length > 0 ? <MobileMonthBars items={recent.map((row) => ({ month: row.month, value: attendanceRate(row) }))} locale={locale} /> : null}
      <div className="mobile-stats-row">
        <div>
          <div className="mobile-stat-value">{totals.total > 0 ? `${Math.round((totals.present / totals.total) * 100)}%` : "—"}</div>
          <div className="mobile-muted-sm">{t("present")}</div>
        </div>
        <div>
          <div className="mobile-stat-value">{data.todos.open}</div>
          <div className="mobile-muted-sm">{tMobile("stats.todosOpen")}</div>
        </div>
        <div>
          <div className="mobile-stat-value">{money(finesTotal, locale)}</div>
          <div className="mobile-muted-sm">{t("kpiFinesAmount")}</div>
        </div>
      </div>
    </MobileCard>
  );
}
