"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileGroupCard, MobileListRow } from "@/components/mobile/mobile-ui";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatPercentNumber, formatRappen, toIntlLocale } from "@/lib/utils/format";
import type { TenantPortalCharge, TenantPortalChargeStatus, TenantPortalCharges } from "@/types/api";

// Zuerst die jüngsten Perioden; ältere erst auf Wunsch.
const INITIAL_ROWS = 12;

export const TENANT_CHARGE_VARIANTS: Record<TenantPortalChargeStatus, BadgeVariant> = {
  open: "warning",
  overdue: "danger",
  paid: "success",
  waived: "neutral",
};

/** Forderungen des Betreibers an den eigenen Mandanten (nur Mandanten-Admins). */
export function useTenantCharges(tenantId: string) {
  const [charges, setCharges] = useState<TenantPortalCharges | null>(null);
  useEffect(() => {
    let cancelled = false;
    browserApiFetch<TenantPortalCharges>(`/api/tenants/${tenantId}/charges`)
      .then((result) => {
        if (!cancelled) setCharges(result);
      })
      .catch(() => {
        // Ohne Forderungen (bzw. Fehler) bleibt der Abschnitt einfach ausgeblendet.
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);
  return charges;
}

/** Rabattzeile einer Forderung (Prozent und abgezogener Betrag), falls vorhanden. */
export function chargeDiscount(charge: TenantPortalCharge): { percent: number; amountRp: number } | null {
  const line = charge.lines?.find((entry) => entry.kind === "discount");
  if (!line || !line.percent) return null;
  return { percent: line.percent, amountRp: Math.abs(line.amount_rp) };
}

function ChargeDiscountHint({ charge }: { charge: TenantPortalCharge }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const discount = chargeDiscount(charge);
  if (!discount) return null;
  return (
    <span className="tenant-charges-discount">
      {t("charges.discountIncluded", { percent: formatPercentNumber(discount.percent, locale), amount: formatRappen(discount.amountRp, locale) })}
    </span>
  );
}

/** Letzter Tag einer Periode (period_end ist exklusiv). */
function periodText(charge: TenantPortalCharge): string {
  const [year, month, day] = charge.period_end.split("-").map(Number);
  const last = new Date(Date.UTC(year, month - 1, day - 1)).toISOString().slice(0, 10);
  return `${formatDate(charge.period_start)} – ${formatDate(last)}`;
}

function ChargeSummary({ charges }: { charges: TenantPortalCharges }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  if (charges.open.count === 0) return <p className="muted tenant-charges-summary">{t("charges.allPaid")}</p>;
  return (
    <p className="tenant-charges-summary">
      {t("charges.openSum", { amount: formatRappen(charges.open.amount_rp, locale), count: charges.open.count })}
      {charges.overdue.count > 0 ? (
        <span className="tenant-charges-overdue"> · {t("charges.overdueSum", { amount: formatRappen(charges.overdue.amount_rp, locale) })}</span>
      ) : null}
    </p>
  );
}

/** Ganze Tage von heute bis zum Datum (negativ = vergangen), in Lokalzeit. */
export function daysUntil(iso: string, today = new Date()): number {
  const [year, month, day] = iso.split("-").map(Number);
  const target = Date.UTC(year, month - 1, day);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - now) / 86_400_000);
}

export type ChargeFilter = "all" | "open" | "done";

function matchesFilter(charge: TenantPortalCharge, filter: ChargeFilter): boolean {
  if (filter === "all") return true;
  const open = charge.status === "open" || charge.status === "overdue";
  return filter === "open" ? open : !open;
}

/** Roter Hinweis oben auf der Seite, solange eine Periode überfällig ist. */
export function TenantOverdueBanner({ charges, onShow }: { charges: TenantPortalCharges; onShow: () => void }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const overdue = charges.items.filter((charge) => charge.status === "overdue");
  if (overdue.length === 0) return null;
  const oldest = overdue[overdue.length - 1];
  const days = Math.max(1, -daysUntil(oldest.due_on));
  return (
    <div className="tenant-overdue-banner" role="alert">
      <span className="tenant-overdue-icon" aria-hidden="true">!</span>
      <div className="tenant-overdue-text">
        <strong>{t("charges.overdueHeadline", { amount: formatRappen(charges.overdue.amount_rp, locale) })}</strong>
        <span>
          {overdue.length === 1
            ? t("charges.overdueDetailOne", { period: periodText(oldest), due: formatDate(oldest.due_on), days })
            : t("charges.overdueDetailMany", { count: overdue.length, days })}
        </span>
      </div>
      <button type="button" className="button-secondary tenant-overdue-button" onClick={onShow}>
        {t("charges.showOverdue")}
      </button>
    </div>
  );
}

function DueHint({ charge }: { charge: TenantPortalCharge }) {
  const t = useTranslations("tenantSettings");
  if (charge.status !== "open" && charge.status !== "overdue") return null;
  const days = daysUntil(charge.due_on);
  if (charge.status === "overdue") return <span className="tenant-charges-due-hint tenant-charges-overdue">{t("charges.overdueSince", { count: Math.max(1, -days) })}</span>;
  return <span className="tenant-charges-due-hint">{t("charges.dueIn", { count: Math.max(0, days) })}</span>;
}

/** Abrechnungsperioden mit Filter, Zeitleiste der letzten sechs Perioden und Tabelle. */
export function TenantBillingCard({
  charges,
  filter,
  onFilterChange,
}: {
  charges: TenantPortalCharges;
  filter: ChargeFilter;
  onFilterChange: (filter: ChargeFilter) => void;
}) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const [showAll, setShowAll] = useState(false);
  const shown = charges.items.filter((charge) => matchesFilter(charge, filter));
  const rows = showAll ? shown : shown.slice(0, INITIAL_ROWS);
  const timeline = charges.items.slice(0, 6).reverse();
  const openCount = charges.open.count;
  const doneCount = charges.items.length - openCount;

  return (
    <section className="card grid tenant-charges" id="abrechnung">
      <div className="tenant-charges-head">
        <div className="tenant-charges-title">
          <div className="eyebrow">{t("charges.eyebrow")}</div>
          <h2 className="tenant-charges-heading">{t("charges.title")}</h2>
          <span className="muted tenant-charges-hint">{t("charges.hint", { days: charges.payment_term_days })}</span>
        </div>
        <FilterTabs<ChargeFilter>
          value={filter}
          onChange={(value) => {
            onFilterChange(value);
            setShowAll(false);
          }}
          options={[
            { value: "all", label: t("charges.filter.all"), count: charges.items.length },
            { value: "open", label: t("charges.filter.open"), count: openCount },
            { value: "done", label: t("charges.filter.done"), count: doneCount },
          ]}
        />
      </div>

      {timeline.length > 1 ? (
        <div className="tenant-charges-timeline" role="list" aria-label={t("charges.timelineLabel")}>
          {timeline.map((charge) => (
            <div key={charge.id} role="listitem" className="tenant-charges-timeline-item" title={`${periodText(charge)} · ${t(`charges.status.${charge.status}`)}`}>
              <span className={`tenant-charges-bar tenant-charges-bar-${charge.status}`} />
              <span className="tenant-charges-month">{monthShort(charge.period_start, locale)}</span>
            </div>
          ))}
        </div>
      ) : null}

      <DataTable
        className="tenant-charges-table"
        columns={[
          { key: "period", label: t("charges.columns.period") },
          { key: "amount", label: t("charges.columns.amount") },
          { key: "due", label: t("charges.columns.dueOn") },
          { key: "status", label: t("charges.columns.status") },
        ]}
        emptyMessage={t("charges.empty")}
      >
        {rows.map((charge) => (
          <tr key={charge.id} className={`tenant-charges-row-${charge.status}`}>
            <td>
              <span className="tenant-charges-period">{periodText(charge)}</span>
              <span className="muted tenant-charges-meta">{t(charge.billing_cycle === "monthly" ? "billingMonthly" : "billingYearly")}</span>
            </td>
            <td className="tenant-charges-amount">
              {formatRappen(charge.amount_rp, locale)}
              <ChargeDiscountHint charge={charge} />
            </td>
            <td>
              <span className="tenant-charges-date">{formatDate(charge.due_on)}</span>
              <DueHint charge={charge} />
            </td>
            <td>
              <Badge variant={TENANT_CHARGE_VARIANTS[charge.status]} dot>{t(`charges.status.${charge.status}`)}</Badge>
              {charge.paid_on ? <span className="muted tenant-charges-meta">{t("charges.paidAt", { date: formatDate(charge.paid_on) })}</span> : null}
            </td>
          </tr>
        ))}
      </DataTable>
      {shown.length > INITIAL_ROWS ? (
        <div>
          <button type="button" className="button-ghost" onClick={() => setShowAll((value) => !value)}>
            {showAll ? t("charges.showLess") : t("charges.showAll", { count: shown.length })}
          </button>
        </div>
      ) : null}
    </section>
  );
}

function monthShort(iso: string, locale: string): string {
  const [year, month] = iso.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString(toIntlLocale(locale), { month: "short" });
}

export function MobileTenantCharges({ tenantId }: { tenantId: string }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const charges = useTenantCharges(tenantId);
  const [showAll, setShowAll] = useState(false);
  if (!charges || charges.items.length === 0) return null;
  const rows = showAll ? charges.items : charges.items.slice(0, 6);

  return (
    <MobileGroupCard label={t("charges.eyebrow")}>
      <div className="mobile-tenant-quota-note">
        <ChargeSummary charges={charges} />
      </div>
      {rows.map((charge) => (
        <MobileListRow
          key={charge.id}
          chevron={false}
          label={
            <span className="mobile-row-stack">
              <span className="mobile-row-title">{formatRappen(charge.amount_rp, locale)}</span>
              <span className="mobile-row-meta mobile-row-meta-wrap">{periodText(charge)}</span>
              <ChargeDiscountHint charge={charge} />
              <span className="mobile-row-meta">
                {charge.paid_on ? t("charges.paidOn", { date: formatDate(charge.paid_on) }) : t("charges.dueOn", { date: formatDate(charge.due_on) })}
              </span>
            </span>
          }
          trailing={<Badge variant={TENANT_CHARGE_VARIANTS[charge.status]}>{t(`charges.status.${charge.status}`)}</Badge>}
        />
      ))}
      {charges.items.length > rows.length || showAll ? (
        <MobileListRow
          label={showAll ? t("charges.showLess") : t("charges.showAll", { count: charges.items.length })}
          onClick={() => setShowAll((value) => !value)}
        />
      ) : null}
    </MobileGroupCard>
  );
}
