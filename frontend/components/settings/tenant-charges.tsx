"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileGroupCard, MobileListRow } from "@/components/mobile/mobile-ui";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatRappen } from "@/lib/utils/format";
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

export function TenantChargesSection({ tenantId }: { tenantId: string }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const charges = useTenantCharges(tenantId);
  const [showAll, setShowAll] = useState(false);
  if (!charges || charges.items.length === 0) return null;
  const rows = showAll ? charges.items : charges.items.slice(0, INITIAL_ROWS);

  return (
    <section className="card grid tenant-charges">
      <div>
        <div className="eyebrow">{t("charges.eyebrow")}</div>
        <ChargeSummary charges={charges} />
        <p className="muted tenant-charges-hint">{t("charges.hint", { days: charges.payment_term_days })}</p>
      </div>
      <DataTable
        columns={[
          { key: "period", label: t("charges.columns.period") },
          { key: "amount", label: t("charges.columns.amount") },
          { key: "due", label: t("charges.columns.dueOn") },
          { key: "status", label: t("charges.columns.status") },
          { key: "paid", label: t("charges.columns.paidOn") },
        ]}
      >
        {rows.map((charge) => (
          <tr key={charge.id}>
            <td>
              {periodText(charge)}
              <div className="muted tenant-charges-meta">{t(charge.billing_cycle === "monthly" ? "billingMonthly" : "billingYearly")}</div>
            </td>
            <td className="tenant-charges-amount">{formatRappen(charge.amount_rp, locale)}</td>
            <td>{formatDate(charge.due_on)}</td>
            <td>
              <Badge variant={TENANT_CHARGE_VARIANTS[charge.status]}>{t(`charges.status.${charge.status}`)}</Badge>
            </td>
            <td>{charge.paid_on ? formatDate(charge.paid_on) : <span className="muted">–</span>}</td>
          </tr>
        ))}
      </DataTable>
      {charges.items.length > INITIAL_ROWS ? (
        <div>
          <button type="button" className="button-ghost" onClick={() => setShowAll((value) => !value)}>
            {showAll ? t("charges.showLess") : t("charges.showAll", { count: charges.items.length })}
          </button>
        </div>
      ) : null}
    </section>
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
