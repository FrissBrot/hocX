"use client";

import { DocumentExportButton } from "@/components/documents/export-dialog";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBanner } from "@/components/ui/status-banner";
import { ActionIcon } from "@/components/ui/action-icons";
import { StatisticsOverview } from "@/types/api";
import { CHART_COLORS, CHART_PIE_PALETTE } from "@/lib/constants/chart-colors";
import { FullscreenCtx, fmtAmount } from "@/components/statistics/statistics-chart-utils";
import type { PieEntry } from "@/components/statistics/statistics-charts";
import { fineCountsByParticipant, fineCountsByType, fineTotalsByCurrency, formatFineTotals } from "@/lib/utils/fine-stats";

import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";

type Props = { data: StatisticsOverview | null };

// recharts erst nachladen (nur im Browser): die Diagramme brauchen ohnehin die gemessene
// Containerbreite, serverseitig gerendert wuerden sie nichts zeigen.
const AttendanceTimeChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.AttendanceTimeChart),
  { ssr: false }
);
const AttendanceParticipantChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.AttendanceParticipantChart),
  { ssr: false }
);
const FinanceChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.FinanceChart),
  { ssr: false }
);
const GroupSessionsChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.GroupSessionsChart),
  { ssr: false }
);
const GroupAvgChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.GroupAvgChart),
  { ssr: false }
);
const PieDonutChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.PieDonutChart),
  { ssr: false }
);
const FinesParticipantChart = dynamic(
  () => import("@/components/statistics/statistics-charts").then((m) => m.FinesParticipantChart),
  { ssr: false }
);

const COLORS = CHART_COLORS;
const PIE_PALETTE = CHART_PIE_PALETTE;

type Period = "all" | "12m" | "6m" | "3m";

function filterByPeriod<T extends { month: string }>(items: T[], period: Period): T[] {
  if (period === "all" || items.length === 0) return items;
  const months = period === "12m" ? 12 : period === "6m" ? 6 : 3;
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - months);
  return items.filter((i) => i.month >= cutoff.toISOString().slice(0, 7));
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="stats-card">
      <div className="stats-card-label">{label}</div>
      <div className="stats-card-value">{value}</div>
      {sub && <div className="stats-card-sub">{sub}</div>}
    </div>
  );
}

function ExpandIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <polyline points="10,2 14,2 14,6" />
      <polyline points="6,14 2,14 2,10" />
      <line x1="14" y1="2" x2="9" y2="7" />
      <line x1="2" y1="14" x2="7" y2="9" />
    </svg>
  );
}

type CycleOption = { value: string; label: string };
function CycleDropdown({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: CycleOption[] }) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!(e.target as Element).closest(".stats-cycle-dd")) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className="stats-cycle-dd">
      <button
        type="button"
        className={`stats-cycle-btn${open ? " stats-cycle-btn-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
      >
        <span>{current?.label}</span>
        <svg className={`stats-cycle-chevron${open ? " open" : ""}`} width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="2,4 6,8 10,4" />
        </svg>
      </button>
      {open && (
        <div className="stats-cycle-menu">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              className={`stats-cycle-item${o.value === value ? " active" : ""}`}
              onClick={() => { onChange(o.value); setOpen(false); }}
            >
              {o.value !== "all" && <span className="stats-cycle-dot" />}
              {o.label}
              {o.value === value && (
                <svg className="stats-cycle-check" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="2,6 5,9 10,3" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ChartCard({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  const t = useTranslations("statistics");
  const tCommon = useTranslations("common");
  const [fullscreen, setFullscreen] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  usePopupEscape(fullscreen, () => setFullscreen(false), rootRef);
  usePopupScrollLock(fullscreen);

  const overlay = fullscreen && typeof document !== "undefined" ? createPortal(
    <div ref={rootRef} className="stats-fs-backdrop" onClick={() => setFullscreen(false)}>
      <div className="stats-fs-card" onClick={(e) => e.stopPropagation()}>
        <div className="stats-fs-header">
          <span className="stats-chart-title">{title}</span>
          <button type="button" className="stats-fs-close" onClick={() => setFullscreen(false)} aria-label={tCommon("close")}>
            <ActionIcon name="close" />
          </button>
        </div>
        <div className="stats-fs-content">
          <FullscreenCtx.Provider value={true}>{children}</FullscreenCtx.Provider>
        </div>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <div className={`stats-chart-card ${className}`}>
      <div className="stats-chart-header">
        <span className="stats-chart-title">{title}</span>
        <button type="button" className="stats-expand-btn" onClick={() => setFullscreen(true)} title={t("fullscreen")}>
          <ExpandIcon />
        </button>
      </div>
      {children}
      {overlay}
    </div>
  );
}

function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const t = useTranslations("statistics");
  const options: { label: string; value: Period }[] = [
    { label: t("period3m"), value: "3m" },
    { label: t("period6m"), value: "6m" },
    { label: t("period12m"), value: "12m" },
    { label: t("periodAll"), value: "all" },
  ];
  return (
    <div className="stats-period-picker">
      {options.map((o) => (
        <button key={o.value} type="button" className={`stats-period-btn${value === o.value ? " stats-period-btn-active" : ""}`} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────────

export function StatisticsView({ data }: Props) {
  const t = useTranslations("statistics");
  const locale = useLocale();
  const router = useRouter();
  const [period, setPeriod] = useState<Period>("all");
  const [attendanceView, setAttendanceView] = useState<"participant" | "time">("time");
  const [financeAccount, setFinanceAccount] = useState<string>("all");
  const [selectedCycle, setSelectedCycle] = useState<string>("all");

  // Rules-of-Hooks fix (audit finding, 2026-08-25): the four useMemo calls below used to
  // sit after an early `if (!data) return ...`, so they were skipped entirely whenever
  // data was null - harmless today only because data is a static SSR prop that never
  // actually changes within one mounted instance of this component, but the moment that
  // stopped being true, React would see a different number of hooks between renders and
  // crash. Hooks now always run (each body is null-safe on its own); the early return
  // moves below them instead, gating everything that isn't a hook call.
  const attendanceTime = useMemo(() => filterByPeriod(data?.attendance_over_time ?? [], period), [data, period]);
  const financeMonths = useMemo(() => {
    const byPeriod = filterByPeriod(data?.finance_by_month ?? [], period);
    if (financeAccount === "all") {
      const merged: Record<string, { month: string; income: number; expenses: number; net: number }> = {};
      for (const r of byPeriod) {
        if (!merged[r.month]) merged[r.month] = { month: r.month, income: 0, expenses: 0, net: 0 };
        merged[r.month].income += r.income;
        merged[r.month].expenses += r.expenses;
        merged[r.month].net += r.net;
      }
      return Object.values(merged).sort((a, b) => a.month.localeCompare(b.month));
    }
    return byPeriod.filter((r) => r.account_name === financeAccount);
  }, [data, period, financeAccount]);

  const accounts = useMemo(() => [...new Set((data?.finance_by_month ?? []).map((r) => r.account_name))], [data]);

  const groupsFiltered = useMemo(() => {
    const stats = data?.groups_stats ?? [];
    if (selectedCycle === "all") {
      // Weighted "Ø Teilnehmer" merge across cycles - this is a THIRD, hand-duplicated copy
      // of the same logic that already lives twice in the backend (now de-duplicated into
      // aggregate_group_rows in backend/app/services/statistics_common.py, used by both
      // app/api/routes/statistics.py and app/services/chart_service.py). It can't be
      // eliminated here without an API change (the /statistics/overview endpoint returns
      // raw per-cycle rows, not a pre-merged view) - see that function's docstring.
      // KEEP IN SYNC BY HAND: if the merge rule (weight by session_count_with_participants)
      // changes there, change it here too (2026-08-13 audit, M11).
      const merged: Record<string, { session_count: number; session_count_with_participants: number; weighted_participants: number; sessions_with_p: number }> = {};
      for (const g of stats) {
        if (!merged[g.group_name]) merged[g.group_name] = { session_count: 0, session_count_with_participants: 0, weighted_participants: 0, sessions_with_p: 0 };
        merged[g.group_name].session_count += g.session_count;
        merged[g.group_name].session_count_with_participants += g.session_count_with_participants;
        merged[g.group_name].weighted_participants += g.avg_participants * g.session_count_with_participants;
        merged[g.group_name].sessions_with_p += g.session_count_with_participants;
      }
      return Object.entries(merged).map(([name, v]) => ({
        name,
        allSessions: v.session_count,
        withParticipants: v.session_count_with_participants,
        avgParticipants: v.sessions_with_p > 0 ? Math.round((v.weighted_participants / v.sessions_with_p) * 10) / 10 : 0,
      })).sort((a, b) => b.allSessions - a.allSessions);
    }
    const [configId, year] = selectedCycle.split(":");
    return stats
      .filter((g) => g.cycle_config_id === configId && g.cycle_year === Number(year))
      .map((g) => ({
        name: g.group_name,
        allSessions: g.session_count,
        withParticipants: g.session_count_with_participants,
        avgParticipants: Math.round(g.avg_participants * 10) / 10,
      }))
      .sort((a, b) => b.allSessions - a.allSessions);
  }, [data, selectedCycle]);

  if (!data) {
    return <div className="stats-empty"><p className="muted">{t("noDataAvailable")}</p></div>;
  }

  const hasNoStatistics =
    data.protocols_total === 0 &&
    data.todos.total === 0 &&
    data.attendance_over_time.length === 0 &&
    data.attendance_by_participant.length === 0 &&
    data.fines_by_participant.length === 0 &&
    data.finance_by_month.length === 0;

  if (hasNoStatistics) {
    return (
      <div className="stats-page">
        <div className="page-header">
          <div>
            <h1 className="page-title">{t("pageTitle")}</h1>
            <p className="muted">{t("pageIntroEmpty")}</p>
          </div>
        </div>
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
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

  const todoData: PieEntry[] = [
    { name: t("todoDone"), value: data.todos.done, color: COLORS.done },
    { name: t("todoOpen"), value: data.todos.open, color: COLORS.open },
  ];

  const fineTypeData: PieEntry[] = fineCountsByType(data.fines_by_type).map((f, i) => ({
    name: f.label,
    value: f.count,
    color: PIE_PALETTE[i % PIE_PALETTE.length],
  }));

  const top10Fines = fineCountsByParticipant(data.fines_by_participant).slice(0, 10);
  // Summen aus den Typen: fines_by_participant enthält für Leser nur die eigene Zeile.
  const fineTotals = fineTotalsByCurrency(data.fines_by_type);
  const top15Attendance = data.attendance_by_participant.slice(0, 15);

  const hasCycles = data.cycles.length > 0;
  const hasGroups = data.groups_stats.length > 0;

  return (
    <div className="stats-page">

      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageIntro")}</p>
        </div>
        <DocumentExportButton context={{ documentType: "statistics" }} />
      </div>
      {data.per_person_scope === "own" ? <StatusBanner tone="neutral" message={t("perPersonOwnHint")} /> : null}

      {/* ── KPI row ── */}
      <div className="stats-kpi-row">
        <StatCard label={t("kpiProtocols")} value={data.protocols_total} />
        <StatCard label={t("kpiMembers")} value={data.participants_active} sub={t("totalCountSub", { count: data.participants_total })} />
        <StatCard label={t("kpiTodos")} value={data.todos.total} sub={t("openCountSub", { count: data.todos.open })} />
        <StatCard label={t("kpiFinesTotal")} value={fineTotals.reduce((s, f) => s + f.count, 0)} />
        <StatCard label={t("kpiFinesAmount")} value={formatFineTotals(fineTotals, (amount) => fmtAmount(amount, locale))} />
      </div>

      {/* ── Section: Gruppen ── */}
      {hasGroups && (
        <div className="stats-section">
          <div className="stats-section-header">
            <h2 className="stats-section-title">{t("sectionGroups")}</h2>
            {hasCycles && (
              <CycleDropdown
                value={selectedCycle}
                onChange={setSelectedCycle}
                options={[
                  { value: "all", label: t("allCycles") },
                  ...data.cycles.map((c) => ({ value: `${c.cycle_config_id}:${c.cycle_year}`, label: c.label })),
                ]}
              />
            )}
          </div>

          <div className="stats-grid">
            <ChartCard title={t("chartSessionsPerGroup")}>
              {groupsFiltered.length === 0
                ? <p className="stats-no-data">{t("noDataForCycle")}</p>
                : <GroupSessionsChart data={groupsFiltered} />}
            </ChartCard>

            <ChartCard title={t("chartAvgParticipantsPerGroup")}>
              {groupsFiltered.length === 0
                ? <p className="stats-no-data">{t("noDataForCycle")}</p>
                : <GroupAvgChart data={groupsFiltered} />}
            </ChartCard>
          </div>
        </div>
      )}

      {/* ── Section: Zeitreihen ── */}
      <div className="stats-section">
        <div className="stats-section-header">
          <h2 className="stats-section-title">{t("sectionTimeline")}</h2>
          <div className="stats-toolbar">
            <PeriodPicker value={period} onChange={setPeriod} />
          </div>
        </div>

        <div className="stats-grid">
          <ChartCard title={t("chartAttendance")} className="stats-chart-wide">
            <div className="stats-chart-toolbar">
              <div className="stats-segment">
                <button type="button" className={`stats-seg-btn${attendanceView === "time" ? " stats-seg-btn-active" : ""}`} onClick={() => setAttendanceView("time")}>{t("viewByTime")}</button>
                <button type="button" className={`stats-seg-btn${attendanceView === "participant" ? " stats-seg-btn-active" : ""}`} onClick={() => setAttendanceView("participant")}>{t("viewByMember")}</button>
              </div>
            </div>
            {attendanceView === "time" ? (
              attendanceTime.length === 0
                ? <p className="stats-no-data">{t("noAttendanceDataPeriod")}</p>
                : <AttendanceTimeChart data={attendanceTime} />
            ) : (
              top15Attendance.length === 0
                ? <p className="stats-no-data">{t("noAttendanceData")}</p>
                : <AttendanceParticipantChart data={top15Attendance} />
            )}
          </ChartCard>

          {data.finance_by_month.length > 0 && (
            <ChartCard title={t("chartFinancePerMonth")} className="stats-chart-wide">
              <div className="stats-chart-toolbar">
                {accounts.length > 1 && (
                  <div className="stats-segment">
                    <button type="button" className={`stats-seg-btn${financeAccount === "all" ? " stats-seg-btn-active" : ""}`} onClick={() => setFinanceAccount("all")}>{t("allAccounts")}</button>
                    {accounts.map((a) => (
                      <button key={a} type="button" className={`stats-seg-btn${financeAccount === a ? " stats-seg-btn-active" : ""}`} onClick={() => setFinanceAccount(a)}>{a}</button>
                    ))}
                  </div>
                )}
              </div>
              {financeMonths.length === 0
                ? <p className="stats-no-data">{t("noFinanceDataPeriod")}</p>
                : <FinanceChart data={financeMonths} />}
            </ChartCard>
          )}
        </div>
      </div>

      {/* ── Section: Übersicht ── */}
      <div className="stats-section">
        <div className="stats-section-header">
          <h2 className="stats-section-title">{t("sectionOverview")}</h2>
        </div>
        <div className="stats-grid">
          <ChartCard title={t("chartTodosOverview")}>
            <PieDonutChart data={todoData} />
          </ChartCard>

          {fineTypeData.length > 0 && (
            <ChartCard title={t("chartFinesByType")}>
              <PieDonutChart data={fineTypeData} />
            </ChartCard>
          )}

          {top10Fines.length > 0 && (
            <ChartCard title={t("chartFinesPerMemberTop10")} className="stats-chart-wide">
              <FinesParticipantChart data={top10Fines} />
            </ChartCard>
          )}
        </div>
      </div>

    </div>
  );
}
