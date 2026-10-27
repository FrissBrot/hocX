"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ActionIcon } from "@/components/ui/action-icons";
import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { PillMenu, PillMenuOption } from "@/components/ui/pill-menu";
import { SearchInput } from "@/components/ui/search-input";
import { Tabs } from "@/components/ui/tabs";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { CHART_COLORS } from "@/lib/constants/chart-colors";
import { formatDate, formatRappen, toIntlLocale } from "@/lib/utils/format";
import type {
  CashflowCost,
  CashflowCostStatus,
  CashflowCostWrite,
  CashflowMonth,
  CashflowOverview,
  TenantCharge,
  TenantChargePage,
  TenantChargeStatus,
} from "@/types/api";
import { Select } from "@/components/ui/select";

type TFunc = ReturnType<typeof useTranslations>;
type TabId = "overview" | "charges" | "costs";
const CHARGE_PAGE_SIZE = 50;

const CHARGE_VARIANTS: Record<TenantChargeStatus, BadgeVariant> = { open: "warning", paid: "success", waived: "neutral" };
const COST_VARIANTS: Record<CashflowCostStatus, BadgeVariant> = { active: "success", planned: "info" };

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function monthLabel(month: string, locale: string, style: "long" | "short" = "long"): string {
  const [year, value] = month.split("-").map(Number);
  return new Date(year, value - 1, 1).toLocaleDateString(toIntlLocale(locale), { month: style, year: style === "long" ? "numeric" : "2-digit" });
}

/** Letzter Tag einer Periode (period_end ist exklusiv). */
function periodLastDay(periodEnd: string): string {
  const [year, month, day] = periodEnd.split("-").map(Number);
  const last = new Date(Date.UTC(year, month - 1, day - 1));
  return last.toISOString().slice(0, 10);
}

function percentText(bp: number | null, locale: string): string {
  if (bp === null) return "–";
  return new Intl.NumberFormat(toIntlLocale(locale), { style: "percent", minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(bp / 10000);
}

/** Aktuelle Werte für Callbacks, ohne dass Lade-Effekte bei jedem Render neu starten. */
function useLatest<T>(value: T) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

function signedClass(value: number): string {
  return value < 0 ? "cashflow-negative" : value > 0 ? "cashflow-positive" : "";
}

export function AdminCashflow({ initialOverview }: { initialOverview: CashflowOverview }) {
  const t = useTranslations("adminCashflow");
  const [tab, setTab] = useState<TabId>("overview");
  const [overview, setOverview] = useState(initialOverview);
  const [year, setYear] = useState(initialOverview.year);
  const [costs, setCosts] = useState<CashflowCost[] | null>(null);
  const [editingCost, setEditingCost] = useState<CashflowCost | "new" | null>(null);
  const showToast = useToast();
  const latest = useLatest({ t, showToast });

  const reloadOverview = useCallback(
    async (targetYear: number) => {
      try {
        setOverview(await browserApiFetch<CashflowOverview>(`/api/admin/cashflow/overview?year=${targetYear}`));
      } catch (error) {
        latest.current.showToast(errorText(error, latest.current.t("toast.loadFailed")), "error");
      }
    },
    [latest]
  );

  const reloadCosts = useCallback(async () => {
    try {
      setCosts(await browserApiFetch<CashflowCost[]>("/api/admin/cashflow/costs"));
    } catch (error) {
      latest.current.showToast(errorText(error, latest.current.t("toast.loadFailed")), "error");
    }
  }, [latest]);

  useEffect(() => {
    void reloadCosts();
  }, [reloadCosts]);

  function changeYear(next: number) {
    setYear(next);
    void reloadOverview(next);
  }

  async function costsChanged() {
    await Promise.all([reloadCosts(), reloadOverview(year)]);
  }

  return (
    <div className="grid cashflow-page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        <button type="button" className="button-primary" onClick={() => setEditingCost("new")}>
          {t("actions.newCost")}
        </button>
      </div>

      <Tabs
        activeId={tab}
        onChange={(id) => setTab(id as TabId)}
        tabs={[
          { id: "overview", label: t("tabs.overview"), content: <OverviewTab t={t} overview={overview} year={year} onYearChange={changeYear} /> },
          { id: "charges", label: t("tabs.charges"), content: <ChargesTab t={t} onChanged={() => reloadOverview(year)} /> },
          {
            id: "costs",
            label: t("tabs.costs"),
            content: <CostsTab t={t} costs={costs} onEdit={setEditingCost} onChanged={costsChanged} />,
          },
        ]}
      />

      {editingCost !== null ? (
        <CostModal
          t={t}
          cost={editingCost === "new" ? null : editingCost}
          onClose={() => setEditingCost(null)}
          onSaved={async () => {
            setEditingCost(null);
            await costsChanged();
          }}
        />
      ) : null}
    </div>
  );
}

// --- Übersicht ---------------------------------------------------------------------------------

function OverviewTab({ t, overview, year, onYearChange }: { t: TFunc; overview: CashflowOverview; year: number; onYearChange: (year: number) => void }) {
  const locale = useLocale();
  const [withPlanned, setWithPlanned] = useState(false);
  const ytd = overview.year_to_date;
  const all = overview.all_time;
  const ytdExpenses = ytd.expenses_rp + (withPlanned ? ytd.planned_expenses_rp : 0);
  const ytdNet = ytd.income_rp - ytdExpenses;
  const balance = all.income_rp - all.expenses_rp;
  const balancePlanned = balance - all.planned_expenses_rp;
  const rr = overview.run_rate;
  const rrExpenses = rr.fixed_rp + rr.percent_rp;
  const rrNet = rr.income_rp - rrExpenses;
  const rrNetPlanned = rrNet - rr.planned_fixed_rp - rr.planned_percent_rp;

  const monthExpenses = (month: CashflowMonth) =>
    month.fixed_rp + month.percent_rp + (withPlanned ? month.planned_fixed_rp + month.planned_percent_rp : 0);
  // Total wie die Kennzahlen bis heute: Prognosemonate zählen nicht mit.
  const pastMonths = overview.months.filter((month) => !month.is_future);
  const hasForecast = pastMonths.length < overview.months.length;
  const totals = pastMonths.reduce(
    (sum, month) => ({
      income: sum.income + month.income_rp,
      fixed: sum.fixed + month.fixed_rp + (withPlanned ? month.planned_fixed_rp : 0),
      percent: sum.percent + month.percent_rp + (withPlanned ? month.planned_percent_rp : 0),
      open: sum.open + month.open_rp,
    }),
    { income: 0, fixed: 0, percent: 0, open: 0 }
  );

  return (
    <div className="grid cashflow-overview">
      <div className="cashflow-toolbar">
        <label className="cashflow-year">
          <span className="field-label">{t("overview.year")}</span>
          <Select value={year} onChange={(event) => onYearChange(Number(event.target.value))}>
            {overview.years.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </label>
        <button
          type="button"
          className={withPlanned ? "button-toggle button-toggle-active" : "button-toggle"}
          aria-pressed={withPlanned}
          onClick={() => setWithPlanned((value) => !value)}
        >
          {t("overview.includePlanned")}
        </button>
      </div>

      <div className="stats-kpi-row">
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.income", { year })}</span>
          <span className="stats-card-value">{formatRappen(ytd.income_rp, locale)}</span>
          <span className="stats-card-sub">{t("overview.incomeSub")}</span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.expenses", { year })}</span>
          <span className="stats-card-value">{formatRappen(ytdExpenses, locale)}</span>
          <span className="stats-card-sub">
            {withPlanned ? t("overview.expensesSubPlanned", { planned: formatRappen(ytd.planned_expenses_rp, locale) }) : t("overview.expensesSub")}
          </span>
        </div>
        <div className="stats-card">
          <span className="stats-card-label">{t("overview.result", { year })}</span>
          <span className={`stats-card-value ${signedClass(ytdNet)}`}>{formatRappen(ytdNet, locale)}</span>
          <span className="stats-card-sub">{t("overview.resultSub")}</span>
        </div>
        <div className="stats-card cashflow-balance-card">
          <span className="stats-card-label">{t("overview.balance")}</span>
          <span className={`stats-card-value ${signedClass(balance)}`}>{formatRappen(balance, locale)}</span>
          <span className="stats-card-sub">{t("overview.balancePlanned", { amount: formatRappen(balancePlanned, locale) })}</span>
        </div>
      </div>

      <div className="cashflow-cards">
        <section className="card admin-cost-card">
          <div className="admin-section-title">{t("runRate.title")}</div>
          <div className="admin-cost-row">
            <span>{t("runRate.income", { count: rr.paying_tenants })}</span>
            <span>{formatRappen(rr.income_rp, locale)}</span>
          </div>
          <div className="admin-cost-row">
            <span>{t("runRate.fixed")}</span>
            <span>– {formatRappen(rr.fixed_rp, locale)}</span>
          </div>
          <div className="admin-cost-row">
            <span>{t("runRate.percent")}</span>
            <span>– {formatRappen(rr.percent_rp, locale)}</span>
          </div>
          <div className="admin-cost-total">
            <span>{t("runRate.net")}</span>
            <strong className={signedClass(rrNet)}>{formatRappen(rrNet, locale)}</strong>
          </div>
          <div className="admin-cost-row cashflow-planned-row">
            <span>{t("runRate.planned", { amount: formatRappen(rr.planned_fixed_rp + rr.planned_percent_rp, locale) })}</span>
            <span className={signedClass(rrNetPlanned)}>{formatRappen(rrNetPlanned, locale)}</span>
          </div>
          <div className="muted admin-cost-hint">{t("runRate.hint")}</div>
        </section>
        <section className="card admin-cost-card">
          <div className="admin-section-title">{t("receivables.title")}</div>
          <div className="admin-cost-row">
            <span>{t("receivables.open", { count: overview.open.count })}</span>
            <span>{formatRappen(overview.open.amount_rp, locale)}</span>
          </div>
          <div className="admin-cost-row">
            <span className={overview.overdue.count ? "cashflow-overdue" : undefined}>{t("receivables.overdue", { count: overview.overdue.count })}</span>
            <span className={overview.overdue.count ? "cashflow-overdue" : undefined}>{formatRappen(overview.overdue.amount_rp, locale)}</span>
          </div>
          <div className="admin-cost-row">
            <span>{t("receivables.waived", { count: overview.waived.count })}</span>
            <span>{formatRappen(overview.waived.amount_rp, locale)}</span>
          </div>
          <div className="muted admin-cost-hint">{t("receivables.hint")}</div>
        </section>
      </div>

      <section className="stats-chart-card">
        <div className="stats-chart-header">
          <span className="stats-chart-title">{t("chart.title", { year })}</span>
        </div>
        <CashflowChart t={t} months={overview.months} withPlanned={withPlanned} />
      </section>

      <DataTable
        className="cashflow-month-table"
        columns={[
          { key: "month", label: t("table.month") },
          { key: "income", label: t("table.income") },
          { key: "fixed", label: t("table.fixed") },
          { key: "percent", label: t("table.percent") },
          { key: "net", label: t("table.net") },
          { key: "open", label: t("table.open") },
        ]}
      >
        {overview.months.map((month) => {
          const fixed = month.fixed_rp + (withPlanned ? month.planned_fixed_rp : 0);
          const percent = month.percent_rp + (withPlanned ? month.planned_percent_rp : 0);
          const net = month.income_rp - monthExpenses(month);
          return (
            <tr key={month.month} className={month.is_future ? "cashflow-row-future" : undefined}>
              <td>
                <span className="cashflow-month-cell">
                  {monthLabel(month.month, locale)}
                  {month.is_future ? <Badge variant="neutral">{t("table.forecast")}</Badge> : null}
                </span>
              </td>
              <td>{formatRappen(month.income_rp, locale)}</td>
              <td>{fixed ? `– ${formatRappen(fixed, locale)}` : "–"}</td>
              <td>{percent ? `– ${formatRappen(percent, locale)}` : "–"}</td>
              <td className={signedClass(net)}>{formatRappen(net, locale)}</td>
              <td className="muted">{month.open_rp ? formatRappen(month.open_rp, locale) : "–"}</td>
            </tr>
          );
        })}
        <tr className="cashflow-total-row">
          <td>{hasForecast ? t("table.totalToDate") : t("table.total", { year })}</td>
          <td>{formatRappen(totals.income, locale)}</td>
          <td>– {formatRappen(totals.fixed, locale)}</td>
          <td>– {formatRappen(totals.percent, locale)}</td>
          <td className={signedClass(totals.income - totals.fixed - totals.percent)}>{formatRappen(totals.income - totals.fixed - totals.percent, locale)}</td>
          <td>{formatRappen(totals.open, locale)}</td>
        </tr>
      </DataTable>
    </div>
  );
}

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

function CashflowChart({ t, months, withPlanned }: { t: TFunc; months: CashflowMonth[]; withPlanned: boolean }) {
  const locale = useLocale();
  const data = months.map((month) => ({
    month: monthLabel(month.month, locale, "short"),
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

// --- Forderungen -------------------------------------------------------------------------------

type ChargeFilter = TenantChargeStatus | "overdue" | "all";

function ChargesTab({ t, onChanged }: { t: TFunc; onChanged: () => Promise<void> }) {
  const locale = useLocale();
  const showToast = useToast();
  const [filter, setFilter] = useState<ChargeFilter>("open");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TenantChargePage | null>(null);
  const [detail, setDetail] = useState<TenantCharge | null>(null);
  const latest = useLatest({ t, showToast });

  const load = useCallback(async () => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(CHARGE_PAGE_SIZE) });
    if (filter !== "all") params.set("status", filter);
    if (query.trim()) params.set("q", query.trim());
    try {
      setPage(await browserApiFetch<TenantChargePage>(`/api/admin/cashflow/charges?${params.toString()}`));
    } catch (error) {
      latest.current.showToast(errorText(error, latest.current.t("toast.loadFailed")), "error");
    }
  }, [filter, offset, query, latest]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 200);
    return () => clearTimeout(timer);
  }, [load]);

  async function update(charge: TenantCharge, body: { status: TenantChargeStatus; paid_on?: string | null; note?: string | null }) {
    try {
      await browserApiFetch<TenantCharge>(`/api/admin/cashflow/charges/${charge.id}`, { method: "PATCH", body: JSON.stringify(body) });
      showToast(t(`toast.charge.${body.status}`), "success");
      await Promise.all([load(), onChanged()]);
      return true;
    } catch (error) {
      showToast(errorText(error, t("toast.failed")), "error");
      return false;
    }
  }

  async function recalculate(charge: TenantCharge) {
    try {
      await browserApiFetch<TenantCharge>(`/api/admin/cashflow/charges/${charge.id}/recalculate`, { method: "POST" });
      showToast(t("toast.recalculated"), "success");
      await Promise.all([load(), onChanged()]);
    } catch (error) {
      showToast(errorText(error, t("toast.failed")), "error");
    }
  }

  const statusOptions: PillMenuOption<TenantChargeStatus>[] = (["open", "paid", "waived"] as const).map((value) => ({
    value,
    label: t(`chargeStatus.${value}`),
    variant: CHARGE_VARIANTS[value],
  }));
  const totals = page?.totals;
  const allCount = totals ? totals.open.count + totals.paid.count + totals.waived.count : undefined;
  const showPagination = (page?.total ?? 0) > CHARGE_PAGE_SIZE; // i18n-ok: Zahlenvergleich

  return (
    <div className="grid">
      <p className="muted cashflow-tab-intro">{t("charges.intro")}</p>
      <div className="list-filter-row">
        <FilterTabs<ChargeFilter>
          value={filter}
          onChange={(value) => {
            setFilter(value);
            setOffset(0);
          }}
          options={[
            { value: "open", label: t("chargeStatus.open"), count: totals?.open.count },
            { value: "overdue", label: t("chargeStatus.overdue"), count: totals?.overdue.count },
            { value: "paid", label: t("chargeStatus.paid"), count: totals?.paid.count },
            { value: "waived", label: t("chargeStatus.waived"), count: totals?.waived.count },
            { value: "all", label: t("charges.all"), count: allCount },
          ]}
        />
        <SearchInput
          value={query}
          onChange={(value) => {
            setQuery(value);
            setOffset(0);
          }}
          placeholder={t("charges.search")}
          aria-label={t("charges.search")}
        />
      </div>
      {totals && filter !== "all" ? (
        <p className="muted cashflow-sum-line">{t("charges.sum", { amount: formatRappen(totals[filter].amount_rp, locale), count: totals[filter].count })}</p>
      ) : null}
      <DataTable
        columns={[
          { key: "tenant", label: t("charges.columns.tenant") },
          { key: "period", label: t("charges.columns.period") },
          { key: "amount", label: t("charges.columns.amount") },
          { key: "due", label: t("charges.columns.dueOn") },
          { key: "status", label: t("charges.columns.status") },
          { key: "paid", label: t("charges.columns.paidOn") },
          { key: "actions", label: "" },
        ]}
        emptyMessage={page ? t("charges.empty") : t("loading")}
        footer={showPagination ? <Pagination offset={offset} limit={CHARGE_PAGE_SIZE} total={page?.total ?? 0} onOffsetChange={setOffset} /> : undefined}
      >
        {(page?.items ?? []).map((charge) => {
          const items: ActionMenuItem[] = [{ label: t("charges.actions.details"), onClick: () => setDetail(charge) }];
          if (charge.status !== "paid" && charge.tenant_id) items.push({ label: t("charges.actions.recalculate"), onClick: () => void recalculate(charge) });
          return (
            <tr key={charge.id}>
              <td>
                <button type="button" className="cashflow-link" onClick={() => setDetail(charge)}>
                  {charge.tenant_name}
                </button>
                {charge.tenant_id === null ? <span className="muted cashflow-deleted"> {t("charges.deletedTenant")}</span> : null}
              </td>
              <td>
                <span className="cashflow-period">
                  {formatDate(charge.period_start)} – {formatDate(periodLastDay(charge.period_end))}
                  <span className="muted">{t(`cycle.${charge.billing_cycle}`)}</span>
                </span>
              </td>
              <td className="cashflow-amount">{formatRappen(charge.amount_rp, locale)}</td>
              <td className={charge.is_overdue ? "cashflow-overdue" : undefined}>{formatDate(charge.due_on)}</td>
              <td>
                <span className="cashflow-status-cell">
                  <PillMenu value={charge.status} options={statusOptions} onChange={(status) => void update(charge, { status })} />
                  {charge.is_overdue ? <Badge variant="danger">{t("chargeStatus.overdue")}</Badge> : null}
                </span>
              </td>
              <td>{charge.paid_on ? formatDate(charge.paid_on) : <span className="muted">–</span>}</td>
              <td className="cashflow-actions-cell">
                <ActionMenu items={items} />
              </td>
            </tr>
          );
        })}
      </DataTable>

      {detail ? (
        <ChargeModal
          t={t}
          charge={detail}
          onClose={() => setDetail(null)}
          onSave={async (body) => {
            if (await update(detail, body)) setDetail(null);
          }}
        />
      ) : null}
    </div>
  );
}

function ChargeModal({ t, charge, onClose, onSave }: {
  t: TFunc;
  charge: TenantCharge;
  onClose: () => void;
  onSave: (body: { status: TenantChargeStatus; paid_on: string | null; note: string | null }) => Promise<void>;
}) {
  const locale = useLocale();
  const [status, setStatus] = useState<TenantChargeStatus>(charge.status);
  const [paidOn, setPaidOn] = useState(charge.paid_on ?? new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState(charge.note ?? "");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSave({ status, paid_on: status === "paid" ? paidOn || null : null, note: note.trim() || null });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open title={charge.tenant_name} description={`${formatDate(charge.period_start)} – ${formatDate(periodLastDay(charge.period_end))}`} onClose={onClose}>
      <ModalSaveForm className="grid" onSubmit={submit}>
        <div className="card admin-cost-card">
          {charge.lines.map((line, index) => (
            <div className="admin-cost-row" key={`${line.kind}-${index}`}>
              <span>
                {line.kind === "discount"
                  ? t("charge.discount", { percent: line.percent ?? 0 })
                  : line.kind === "storage_package" && (line.quantity ?? 1) > 1
                    ? t("charge.quantity", { label: line.label, quantity: line.quantity ?? 1 })
                    : line.label}
              </span>
              <span>{formatRappen(line.amount_rp, locale)}</span>
            </div>
          ))}
          <div className="admin-cost-total">
            <span>{t("charge.total")}</span>
            <strong>{formatRappen(charge.amount_rp, locale)}</strong>
          </div>
          <div className="muted admin-cost-hint">{t("charge.frozen")}</div>
        </div>

        <div className="field-stack">
          <span className="field-label">{t("charge.status")}</span>
          <FilterTabs<TenantChargeStatus>
            value={status}
            onChange={setStatus}
            options={(["open", "paid", "waived"] as const).map((value) => ({ value, label: t(`chargeStatus.${value}`) }))}
          />
        </div>
        {status === "paid" ? (
          <label className="field-stack">
            <span className="field-label">{t("charge.paidOn")}</span>
            <DateInput value={paidOn} onChange={setPaidOn} />
          </label>
        ) : null}
        <label className="field-stack">
          <span className="field-label">{t("charge.note")}</span>
          <input value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} />
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("actions.cancel")}
          </button>
          <button type="submit" data-modal-save className="button-primary" disabled={busy || (status === "paid" && !paidOn)}>
            {t("actions.save")}
          </button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

// --- Kosten ------------------------------------------------------------------------------------

type CostFilter = CashflowCostStatus | "all";

function costAmountText(t: TFunc, cost: Pick<CashflowCost, "kind" | "amount_rp" | "percent_bp" | "interval">, locale: string): string {
  if (cost.kind === "percent") return t("costs.percentAmount", { percent: percentText(cost.percent_bp, locale) });
  return t(`costs.fixedAmount.${cost.interval ?? "monthly"}`, { amount: formatRappen(cost.amount_rp, locale) });
}

function CostsTab({ t, costs, onEdit, onChanged }: {
  t: TFunc;
  costs: CashflowCost[] | null;
  onEdit: (cost: CashflowCost) => void;
  onChanged: () => Promise<void>;
}) {
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [filter, setFilter] = useState<CostFilter>("all");
  const list = useMemo(() => (costs ?? []).filter((cost) => filter === "all" || cost.status === filter), [costs, filter]);
  const count = (status: CashflowCostStatus) => (costs ?? []).filter((cost) => cost.status === status).length;
  const monthly = (status: CashflowCostStatus) =>
    (costs ?? []).filter((cost) => cost.status === status && cost.kind === "fixed" && (!cost.end_date || cost.end_date >= new Date().toISOString().slice(0, 10)))
      .reduce((sum, cost) => sum + cost.monthly_equivalent_rp, 0);

  async function setStatus(cost: CashflowCost, status: CashflowCostStatus) {
    try {
      await browserApiFetch(`/api/admin/cashflow/costs/${cost.id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
      showToast(t(`toast.cost.${status}`, { name: cost.name }), "success");
      await onChanged();
    } catch (error) {
      showToast(errorText(error, t("toast.failed")), "error");
    }
  }

  async function remove(cost: CashflowCost) {
    if (!(await confirm({ message: t("costs.confirmDelete", { name: cost.name }), tone: "danger", confirmLabel: t("actions.delete") }))) return;
    try {
      await browserApiFetch(`/api/admin/cashflow/costs/${cost.id}`, { method: "DELETE" });
      showToast(t("toast.costDeleted"), "success");
      await onChanged();
    } catch (error) {
      showToast(errorText(error, t("toast.failed")), "error");
    }
  }

  const statusOptions: PillMenuOption<CashflowCostStatus>[] = (["active", "planned"] as const).map((value) => ({
    value,
    label: t(`costStatus.${value}`),
    variant: COST_VARIANTS[value],
  }));

  return (
    <div className="grid">
      <p className="muted cashflow-tab-intro">{t("costs.intro")}</p>
      <div className="list-filter-row">
        <FilterTabs<CostFilter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: t("costs.all"), count: costs?.length },
            { value: "active", label: t("costStatus.active"), count: count("active") },
            { value: "planned", label: t("costStatus.planned"), count: count("planned") },
          ]}
        />
        <p className="muted cashflow-sum-line">
          {t("costs.monthlySum", { active: formatRappen(monthly("active"), locale), planned: formatRappen(monthly("active") + monthly("planned"), locale) })}
        </p>
      </div>
      <DataTable
        columns={[
          { key: "name", label: t("costs.columns.name") },
          { key: "kind", label: t("costs.columns.kind") },
          { key: "amount", label: t("costs.columns.amount") },
          { key: "start", label: t("costs.columns.start") },
          { key: "next", label: t("costs.columns.next") },
          { key: "status", label: t("costs.columns.status") },
          { key: "actions", label: "" },
        ]}
        emptyMessage={costs ? t("costs.empty") : t("loading")}
      >
        {list.map((cost) => (
          <tr key={cost.id}>
            <td>
              <button type="button" className="cashflow-link" onClick={() => onEdit(cost)}>
                {cost.name}
              </button>
              {cost.note ? <div className="muted cashflow-note">{cost.note}</div> : null}
            </td>
            <td>
              <Badge variant={cost.kind === "fixed" ? "neutral" : "violet"}>{t(`costKind.${cost.kind}`)}</Badge>
            </td>
            <td className="cashflow-amount">{costAmountText(t, cost, locale)}</td>
            <td>
              {formatDate(cost.start_date)}
              {cost.end_date ? <div className="muted cashflow-note">{t("costs.until", { date: formatDate(cost.end_date) })}</div> : null}
            </td>
            <td>{cost.kind === "percent" ? <span className="muted">{t("costs.perPayment")}</span> : <DueDate value={cost.next_due_on} />}</td>
            <td>
              <PillMenu value={cost.status} options={statusOptions} onChange={(status) => void setStatus(cost, status)} />
            </td>
            <td className="cashflow-actions-cell">
              <span className="cashflow-row-actions">
                <button type="button" className="button-icon-soft" aria-label={t("actions.edit")} title={t("actions.edit")} onClick={() => onEdit(cost)}>
                  <ActionIcon name="edit" />
                </button>
                <button type="button" className="button-icon-soft button-icon-soft-danger" aria-label={t("actions.delete")} title={t("actions.delete")} onClick={() => void remove(cost)}>
                  <ActionIcon name="delete" />
                </button>
              </span>
            </td>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

function DueDate({ value }: { value: string | null }) {
  return value ? <>{formatDate(value)}</> : <span className="muted">–</span>;
}

function inRange(value: number | null, min: number, max: number): value is number {
  return value !== null && Number.isFinite(value) && value >= min && value <= max; // i18n-ok: Zahlenvergleich
}

function toFrancs(rp: number | null): string {
  return rp === null ? "" : (rp / 100).toFixed(2);
}

function CostModal({ t, cost, onClose, onSaved }: { t: TFunc; cost: CashflowCost | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const locale = useLocale();
  const showToast = useToast();
  const [name, setName] = useState(cost?.name ?? "");
  const [kind, setKind] = useState(cost?.kind ?? "fixed");
  const [amount, setAmount] = useState(toFrancs(cost?.amount_rp ?? null));
  const [percent, setPercent] = useState(cost?.percent_bp != null ? String(cost.percent_bp / 100) : "");
  const [costInterval, setCostInterval] = useState(cost?.interval ?? "monthly");
  const [startDate, setStartDate] = useState(cost?.start_date ?? new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(cost?.end_date ?? "");
  const [status, setStatus] = useState<CashflowCostStatus>(cost?.status ?? "active");
  const [note, setNote] = useState(cost?.note ?? "");
  const [busy, setBusy] = useState(false);

  const amountRp = amount.trim() === "" ? null : Math.round(Number(amount.replace(",", ".")) * 100);
  const percentBp = percent.trim() === "" ? null : Math.round(Number(percent.replace(",", ".")) * 100);
  const valueValid = kind === "fixed" ? inRange(amountRp, 0, Number.MAX_SAFE_INTEGER) : inRange(percentBp, 1, 10000);
  const valid = name.trim() !== "" && startDate !== "" && valueValid && (!endDate || endDate >= startDate);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    const body: CashflowCostWrite = {
      name: name.trim(),
      kind,
      amount_rp: kind === "fixed" ? amountRp : null,
      percent_bp: kind === "percent" ? percentBp : null,
      interval: kind === "fixed" ? costInterval : null,
      start_date: startDate,
      end_date: endDate || null,
      status,
      note: note.trim() || null,
    };
    setBusy(true);
    try {
      await browserApiFetch(cost ? `/api/admin/cashflow/costs/${cost.id}` : "/api/admin/cashflow/costs", {
        method: cost ? "PUT" : "POST",
        body: JSON.stringify(body),
      });
      showToast(t(cost ? "toast.costUpdated" : "toast.costCreated"), "success");
      await onSaved();
    } catch (error) {
      showToast(errorText(error, t("toast.failed")), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open title={cost ? t("costForm.editTitle") : t("costForm.newTitle")} onClose={onClose}>
      <ModalSaveForm className="grid" onSubmit={submit}>
        <div className="cashflow-kind-options" role="radiogroup" aria-label={t("costForm.kind")}>
          {(["fixed", "percent"] as const).map((value) => (
            <label key={value} className={`admin-module-option${kind === value ? " admin-module-option-checked" : ""}`}>
              <input type="radio" name="cashflow-kind" checked={kind === value} onChange={() => setKind(value)} />
              <span>
                <strong>{t(`costKind.${value}`)}</strong>
                <span className="muted">{t(`costForm.kindHelp.${value}`)}</span>
              </span>
            </label>
          ))}
        </div>
        <label className="field-stack">
          <span className="field-label">{t("costForm.name")}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} placeholder={t(`costForm.namePlaceholder.${kind}`)} autoFocus />
        </label>
        {kind === "fixed" ? (
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("costForm.amount")}</span>
              <span className="admin-input-suffix">
                <input type="number" min={0} step="0.05" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} />
                <span aria-hidden="true">CHF</span>
              </span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("costForm.interval")}</span>
              <Select value={costInterval} onChange={(event) => setCostInterval(event.target.value as typeof costInterval)}>
                {(["monthly", "yearly", "once"] as const).map((value) => (
                  <option key={value} value={value}>
                    {t(`interval.${value}`)}
                  </option>
                ))}
              </Select>
            </label>
          </div>
        ) : (
          <label className="field-stack">
            <span className="field-label">{t("costForm.percent")}</span>
            <span className="admin-input-suffix">
              <input type="number" min={0.01} max={100} step="0.01" inputMode="decimal" value={percent} onChange={(event) => setPercent(event.target.value)} />
              <span aria-hidden="true">%</span>
            </span>
            <span className="field-help">{t("costForm.percentHelp")}</span>
          </label>
        )}
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{kind === "fixed" && costInterval === "once" ? t("costForm.date") : t("costForm.startDate")}</span>
            <DateInput value={startDate} onChange={setStartDate} />
          </label>
          {kind === "fixed" && costInterval === "once" ? null : (
            <label className="field-stack">
              <span className="field-label">{t("costForm.endDate")}</span>
              <DateInput value={endDate} onChange={setEndDate} min={startDate || undefined} />
            </label>
          )}
        </div>
        <div className="field-stack">
          <span className="field-label">{t("costForm.status")}</span>
          <FilterTabs<CashflowCostStatus>
            value={status}
            onChange={setStatus}
            options={(["active", "planned"] as const).map((value) => ({ value, label: t(`costStatus.${value}`) }))}
          />
          <span className="field-help">{t(`costForm.statusHelp.${status}`)}</span>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("costForm.note")}</span>
          <input value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} />
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("actions.cancel")}
          </button>
          <button type="submit" data-modal-save className="button-primary" disabled={busy || !valid}>
            {cost ? t("actions.save") : t("actions.create")}
          </button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
