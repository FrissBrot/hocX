"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileGroupCard, MobileListRow } from "@/components/mobile/mobile-ui";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatMonthYear, formatPercentNumber, formatRappen } from "@/lib/utils/format";
import type { TenantChargeLine, TenantPortalCharge, TenantPortalChargeStatus, TenantPortalCharges } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

// Zuerst die jüngsten Rechnungen; ältere erst auf Wunsch.
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
        // Ohne Forderungen (bzw. Fehler) bleibt der Reiter «Rechnungen» einfach ausgeblendet.
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);
  return charges;
}

/** Betrag mit typografischem Minus (Rabattzeilen), statt «CHF-8.80» aus Intl. */
export function formatSignedRappen(rp: number, locale: string): string {
  return rp < 0 ? `−${formatRappen(-rp, locale)}` : formatRappen(rp, locale);
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
function lastDay(charge: TenantPortalCharge): string {
  const [year, month, day] = charge.period_end.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day - 1)).toISOString().slice(0, 10);
}

function periodText(charge: TenantPortalCharge): string {
  return `${formatDate(charge.period_start)} – ${formatDate(lastDay(charge))}`;
}

/** Kurzname einer Rechnung: Monat und Jahr bei monatlicher Abrechnung, sonst der Zeitraum. */
export function chargeTitle(charge: TenantPortalCharge, locale: string): string {
  return charge.billing_cycle === "monthly" ? formatMonthYear(charge.period_start, locale) : periodText(charge);
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

function isOpen(charge: TenantPortalCharge): boolean {
  return charge.status === "open" || charge.status === "overdue";
}

function matchesFilter(charge: TenantPortalCharge, filter: ChargeFilter): boolean {
  if (filter === "all") return true;
  return filter === "open" ? isOpen(charge) : !isOpen(charge);
}

/** Text «x Rechnungen · y überfällig» bzw. «alles bezahlt» zu den offenen Rechnungen. */
export function openChargesLabel(charges: TenantPortalCharges, t: TFunc): string {
  if (charges.open.count === 0) return t("charges.allPaidShort");
  return charges.overdue.count
    ? t("charges.openInvoicesOverdue", { count: charges.open.count, overdue: charges.overdue.count })
    : t("charges.openInvoices", { count: charges.open.count });
}

/**
 * Roter Hinweis oben auf der Seite, solange eine Rechnung überfällig ist. Eine einzelne
 * Rechnung öffnet direkt deren Seitenpanel, mehrere die gefilterte Liste.
 */
export function TenantOverdueBanner({
  charges,
  onOpenCharge,
  onShowOpen,
}: {
  charges: TenantPortalCharges;
  onOpenCharge: (charge: TenantPortalCharge) => void;
  onShowOpen: () => void;
}) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const overdue = charges.items.filter((charge) => charge.status === "overdue");
  if (overdue.length === 0) return null;
  const oldest = overdue[overdue.length - 1];
  const days = Math.max(1, -daysUntil(oldest.due_on));
  const amount = formatRappen(charges.overdue.amount_rp, locale);
  return (
    <div className="tenant-overdue-banner" role="alert">
      <span className="tenant-overdue-icon" aria-hidden="true">!</span>
      <div className="tenant-overdue-text">
        <strong>
          {overdue.length === 1
            ? t("charges.overdueInvoiceOne", { title: chargeTitle(oldest, locale), amount })
            : t("charges.overdueInvoiceMany", { count: overdue.length, amount })}
        </strong>
        <span>
          {overdue.length === 1
            ? t("charges.overdueInvoiceDetailOne", { due: formatDate(oldest.due_on), days })
            : t("charges.overdueInvoiceDetailMany", { days })}
        </span>
      </div>
      <button
        type="button"
        className="button-secondary tenant-overdue-button"
        onClick={() => (overdue.length === 1 ? onOpenCharge(oldest) : onShowOpen())}
      >
        {overdue.length === 1 ? t("charges.openInvoice") : t("charges.showOpenInvoices")}
      </button>
    </div>
  );
}

function DueHint({ charge }: { charge: TenantPortalCharge }) {
  const t = useTranslations("tenantSettings");
  if (charge.status === "paid" && charge.paid_on) return <span className="tenant-charges-due-hint">{t("charges.paidHint", { date: formatDate(charge.paid_on) })}</span>;
  if (!isOpen(charge)) return null;
  const days = daysUntil(charge.due_on);
  if (charge.status === "overdue") return <span className="tenant-charges-due-hint tenant-charges-overdue">{t("charges.overdueSince", { count: Math.max(1, -days) })}</span>;
  return <span className="tenant-charges-due-hint">{t("charges.dueIn", { count: Math.max(0, days) })}</span>;
}

/**
 * Kennzahlen im Reiter «Rechnungen»: offene Beträge, die nächste Rechnung und was im laufenden
 * Jahr bezahlt wurde. Die nächste Rechnung entsteht am Ende der jüngsten Periode (Forderungen
 * werden je Periodenbeginn angelegt); den Betrag gibt es nur, wenn er sich aus dem Abo genau
 * ergibt (`nextAmountRp`).
 */
export function TenantInvoiceSummary({ charges, nextAmountRp, today = new Date() }: { charges: TenantPortalCharges; nextAmountRp: number | null; today?: Date }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const year = today.getFullYear();
  const paid = charges.items.filter((charge) => charge.status === "paid" && charge.paid_on?.startsWith(`${year}-`));
  const paidRp = paid.reduce((sum, charge) => sum + charge.amount_rp, 0);
  const latest = charges.items[0];
  const nextOn = latest && daysUntil(latest.period_end, today) > 0 ? latest.period_end : null;

  return (
    <section className="card tenant-usage-summary tenant-usage-summary-3">
      <div className="tenant-usage-summary-cell">
        <span className="tenant-usage-stat-label">{t("charges.openLabel")}</span>
        <span className="tenant-usage-summary-inline">
          <span className={`tenant-usage-summary-value${charges.overdue.count ? " tenant-charges-overdue" : ""}`}>{formatRappen(charges.open.amount_rp, locale)}</span>
          <span className={charges.overdue.count ? "tenant-usage-summary-unit tenant-charges-overdue" : "muted tenant-usage-summary-unit"}>{openChargesLabel(charges, t)}</span>
        </span>
      </div>
      <div className="tenant-usage-summary-cell">
        <span className="tenant-usage-stat-label">{t("charges.nextInvoice")}</span>
        {nextOn ? (
          <span className="tenant-usage-summary-inline">
            <span className="tenant-usage-summary-value">{nextAmountRp !== null ? formatRappen(nextAmountRp, locale) : formatDate(nextOn)}</span>
            {nextAmountRp !== null ? <span className="muted tenant-usage-summary-unit">{t("charges.nextInvoiceOn", { date: formatDate(nextOn) })}</span> : null}
          </span>
        ) : (
          <span className="muted tenant-usage-summary-unit">{t("charges.nextInvoiceUnknown")}</span>
        )}
      </div>
      <div className="tenant-usage-summary-cell">
        <span className="tenant-usage-stat-label">{t("charges.paidInYear", { year: String(year) })}</span>
        <span className="tenant-usage-summary-inline">
          <span className="tenant-usage-summary-value">{formatRappen(paidRp, locale)}</span>
          <span className="muted tenant-usage-summary-unit">{t("charges.invoiceCount", { count: paid.length })}</span>
        </span>
      </div>
    </section>
  );
}

/** Liste aller Rechnungen mit Filter Alle/Offen/Erledigt; ein Klick öffnet das Seitenpanel. */
export function TenantInvoiceList({
  charges,
  filter,
  onFilterChange,
  onOpen,
}: {
  charges: TenantPortalCharges;
  filter: ChargeFilter;
  onFilterChange: (filter: ChargeFilter) => void;
  onOpen: (charge: TenantPortalCharge) => void;
}) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const [showAll, setShowAll] = useState(false);
  const shown = charges.items.filter((charge) => matchesFilter(charge, filter));
  const rows = showAll ? shown : shown.slice(0, INITIAL_ROWS);
  const openCount = charges.open.count;
  const doneCount = charges.items.length - openCount;

  return (
    <section className="card grid tenant-charges">
      <div className="tenant-charges-head">
        <div className="tenant-charges-title">
          <h2 className="tenant-charges-heading">{t("charges.listTitle")}</h2>
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

      <DataTable
        className="tenant-charges-table"
        columns={[
          { key: "period", label: t("charges.columns.period") },
          { key: "amount", label: t("charges.columns.amount") },
          { key: "due", label: t("charges.columns.dueOn") },
          { key: "status", label: t("charges.columns.status") },
        ]}
        emptyMessage={t("charges.emptyInvoices")}
      >
        {rows.map((charge) => (
          <tr key={charge.id} className={`table-row-clickable tenant-charges-row-${charge.status}`} onClick={() => onOpen(charge)}>
            <td>
              <button type="button" className="table-row-link tenant-charges-period" onClick={(event) => { event.stopPropagation(); onOpen(charge); }}>
                {chargeTitle(charge, locale)}
              </button>
              <span className="muted tenant-charges-meta">
                {charge.billing_cycle === "monthly" ? periodText(charge) : t("billingYearly")}
              </span>
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

/** Bezeichnung einer Rechnungsposition; Rabatt und Speicherpakete sind im Backend nur Codes/Namen. */
function lineLabel(line: TenantChargeLine, t: TFunc, locale: string): string {
  if (line.kind === "discount") return line.percent ? t("charges.lineDiscount", { percent: formatPercentNumber(line.percent, locale) }) : t("charges.lineDiscountPlain");
  if (line.kind === "storage_package" && line.quantity && line.quantity > 1) return t("charges.linePackage", { name: line.label, quantity: line.quantity });
  return line.label;
}

/** Seitenpanel einer Rechnung: Periode, Fälligkeit, Zahlung und Positionen mit Total. */
export function TenantInvoicePanel({ charge, onClose }: { charge: TenantPortalCharge | null; onClose: () => void }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  if (!charge) return null;
  const title = t("charges.panelTitle", { title: chargeTitle(charge, locale) });
  return (
    <Modal
      open
      title={title}
      onClose={onClose}
      className="tenant-invoice-panel"
      header={
        <div className="tenant-invoice-panel-head">
          <h2>{title}</h2>
          <Badge variant={TENANT_CHARGE_VARIANTS[charge.status]} dot>{t(`charges.status.${charge.status}`)}</Badge>
        </div>
      }
    >
      <dl className="tenant-invoice-facts">
        <div>
          <dt>{t("charges.columns.period")}</dt>
          <dd>{periodText(charge)}</dd>
        </div>
        <div>
          <dt>{t("charges.columns.dueOn")}</dt>
          <dd>
            {formatDate(charge.due_on)}
            <DueHint charge={{ ...charge, paid_on: null }} />
          </dd>
        </div>
        <div>
          <dt>{t("charges.columns.paidOn")}</dt>
          <dd>{charge.paid_on ? formatDate(charge.paid_on) : "–"}</dd>
        </div>
      </dl>
      <ul className="tenant-invoice-lines" aria-label={t("charges.linesLabel")}>
        {charge.lines.map((line, index) => (
          <li key={`${line.kind}-${index}`} className={`tenant-invoice-line${line.kind === "discount" ? " tenant-invoice-line-discount" : ""}`}>
            <span>{lineLabel(line, t, locale)}</span>
            <span className="tenant-invoice-amount">{formatSignedRappen(line.amount_rp, locale)}</span>
          </li>
        ))}
        <li className="tenant-invoice-line tenant-invoice-total">
          <span>{t("charges.total")}</span>
          <span className="tenant-invoice-amount">{formatRappen(charge.amount_rp, locale)}</span>
        </li>
      </ul>
      {charge.status === "waived" ? <p className="muted tenant-invoice-note">{t("charges.waivedNote")}</p> : null}
    </Modal>
  );
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
