"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ChargeFilter,
  formatSignedRappen,
  openChargesLabel,
  TenantInvoiceList,
  TenantInvoicePanel,
  TenantInvoiceSummary,
  TenantOverdueBanner,
  useTenantCharges,
} from "@/components/settings/tenant-charges";
import { Badge } from "@/components/ui/badge";
import { DocsLink, HelpPopover } from "@/components/ui/help-popover";
import { Tabs } from "@/components/ui/tabs";
import type { NavIconKey } from "@/components/ui/nav-icons";
import { colorForUser, initials } from "@/components/protocol/collaboration-presence";
import { CATEGORY_COLORS, categoryHints, categoryLabels, StorageQuotaComposition } from "@/components/storage/storage-usage-view";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize, formatPercentNumber, formatRappen } from "@/lib/utils/format";
import { FEATURES } from "@/lib/features.generated";
import type { StorageUsageRead, TenantPortalCharge, TenantPortalCharges, TenantSubscription, TenantSubscriptionFeature, TenantSummary, UserSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

export const FEATURE_ICONS: Record<string, NavIconKey> = {
  abgabebox: "submissions",
  finance: "finances",
};

/** Abo, Speichernutzung und Nutzerliste eines Mandanten - geteilt zwischen Desktop und Mobile. */
export function useTenantSubscriptionData(tenantId: string) {
  const [subscription, setSubscription] = useState<TenantSubscription | null>(null);
  const [subscriptionLoading, setSubscriptionLoading] = useState(false);
  const [storageUsage, setStorageUsage] = useState<StorageUsageRead | null>(null);
  const [tenantUsers, setTenantUsers] = useState<UserSummary[]>([]);

  useEffect(() => {
    void loadSubscription();
    void loadStorageUsage();
    void loadTenantUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function loadSubscription() {
    setSubscriptionLoading(true);
    try {
      const result = await browserApiFetch<TenantSubscription>(`/api/tenants/${tenantId}/subscription`);
      setSubscription(result);
    } catch {
      // kein Abo bzw. Fehler beim Laden - Abschnitt zeigt dann nur den Ladehinweis
    } finally {
      setSubscriptionLoading(false);
    }
  }

  async function loadStorageUsage() {
    try {
      const result = await browserApiFetch<StorageUsageRead>("/api/storage/usage");
      setStorageUsage(result);
    } catch {
      // Speicherdaten nicht verfuegbar - Karte zeigt dann nur die Summe aus dem Abo
    }
  }

  async function loadTenantUsers() {
    try {
      const result = await browserApiFetch<UserSummary[]>("/api/users");
      setTenantUsers(result);
    } catch {
      // Nutzerliste nicht verfuegbar (z.B. keine Admin-Rechte) - Avatare bleiben dann leer
    }
  }

  return { subscription, subscriptionLoading, storageUsage, tenantUsers };
}

/** Kosten im gewählten Abrechnungsintervall, oder null wenn (noch) kein Preis gesetzt ist. */
export function subscriptionCostRp(subscription: TenantSubscription): number | null {
  return subscription.billing_cycle === "monthly" ? subscription.estimated_monthly_cost_rp : subscription.estimated_yearly_cost_rp;
}

/** Rabatt des Abos mit dem Preis davor, oder null ohne Rabatt bzw. ohne Preis. */
export function subscriptionDiscount(subscription: TenantSubscription): { percent: number; listRp: number; savedRp: number } | null {
  const cost = subscriptionCostRp(subscription);
  const listRp = subscription.billing_cycle === "monthly" ? subscription.list_monthly_cost_rp : subscription.list_yearly_cost_rp;
  if (!subscription.discount_percent || cost === null || listRp === null) return null;
  return { percent: subscription.discount_percent, listRp, savedRp: listRp - cost };
}

/** Rabatt-Hinweis unter den Abo-Kosten: Preis ohne Rabatt durchgestrichen und die Prozente. */
export function SubscriptionDiscountNote({ subscription, className }: { subscription: TenantSubscription; className?: string }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const discount = subscriptionDiscount(subscription);
  if (!discount) return null;
  return (
    <span className={`tenant-discount-note${className ? ` ${className}` : ""}`}>
      <s className="muted">{formatRappen(discount.listRp, locale)}</s>
      <Badge variant="success">{t("discountBadge", { percent: formatPercentNumber(discount.percent, locale) })}</Badge>
    </span>
  );
}

type SubscriptionTab = "subscription" | "invoices";

/**
 * Inhalt von /tenant-settings/abo: Reiter «Abo & Nutzung» (Kennzahlen, Kostenaufstellung, Nutzer,
 * Speicher) und «Rechnungen» (?tab=invoices, Forderungen des Betreibers mit Seitenpanel).
 */
export function TenantSubscriptionView({ initialTenant }: Props) {
  const t = useTranslations("tenantSettings");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { subscription, subscriptionLoading, storageUsage, tenantUsers } = useTenantSubscriptionData(initialTenant.id);
  const charges = useTenantCharges(initialTenant.id);
  const [chargeFilter, setChargeFilter] = useState<ChargeFilter>("all");
  const [selectedChargeId, setSelectedChargeId] = useState<string | null>(null);
  const tab: SubscriptionTab = searchParams.get("tab") === "invoices" ? "invoices" : "subscription";
  const selectedCharge = charges?.items.find((charge) => charge.id === selectedChargeId) ?? null;

  function selectTab(next: SubscriptionTab) {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "invoices") params.set("tab", "invoices");
    else params.delete("tab");
    const query = params.toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  }

  function openCharge(charge: TenantPortalCharge) {
    selectTab("invoices");
    setSelectedChargeId(charge.id);
  }

  function showOpenCharges() {
    setChargeFilter("open");
    selectTab("invoices");
  }

  if (subscriptionLoading && !subscription) {
    return (
      <section className="card">
        <div className="eyebrow">{t("currentPlanEyebrow")}</div>
        <div className="muted">{t("loadingPlan")}</div>
      </section>
    );
  }
  if (!subscription) {
    return (
      <section className="card">
        <div className="eyebrow">{t("currentPlanEyebrow")}</div>
        <div className="muted">{t("subscriptionLoadFailed")}</div>
      </section>
    );
  }

  const banner = charges ? <TenantOverdueBanner charges={charges} onOpenCharge={openCharge} onShowOpen={showOpenCharges} /> : null;
  // Folgt der Betrag der nächsten Rechnung genau aus dem Abo? Speicherpakete kennt die
  // Abo-Antwort nur als Bytes, nicht als Preis - dann nennt die Kennzahl nur das Datum.
  const nextAmountRp = subscription.package_storage_bytes === 0 ? subscriptionCostRp(subscription) : null;

  return (
    <>
      <Tabs
        activeId={tab}
        onChange={(id) => selectTab(id as SubscriptionTab)}
        tabs={[
          {
            id: "subscription",
            label: t("abo.tabs.subscription"),
            content: (
              <div className="tenant-abo-stack">
                {banner}
                <SubscriptionSummary subscription={subscription} charges={charges} onShowInvoices={() => selectTab("invoices")} />
                <div className="tenant-abo-columns">
                  <PlanBreakdown subscription={subscription} />
                  <div className="tenant-abo-side">
                    <UsersCard subscription={subscription} tenantUsers={tenantUsers} />
                    <StorageCard subscription={subscription} storageUsage={storageUsage} />
                  </div>
                </div>
              </div>
            ),
          },
          {
            id: "invoices",
            label: t("abo.tabs.invoices"),
            count: charges?.open.count ?? null,
            countTone: charges?.overdue.count ? "danger" : undefined,
            content: charges ? (
              <div className="tenant-abo-stack">
                {banner}
                <TenantInvoiceSummary charges={charges} nextAmountRp={nextAmountRp} />
                <TenantInvoiceList charges={charges} filter={chargeFilter} onFilterChange={setChargeFilter} onOpen={(charge) => setSelectedChargeId(charge.id)} />
              </div>
            ) : (
              <section className="card">
                <div className="muted">{t("loadingPlan")}</div>
              </section>
            ),
          },
        ]}
      />
      <TenantInvoicePanel charge={selectedCharge} onClose={() => setSelectedChargeId(null)} />
    </>
  );
}

/** Kennzahlenleiste: Plan und Rhythmus, Total je Abrechnungsintervall, offene Rechnungen. */
function SubscriptionSummary({
  subscription,
  charges,
  onShowInvoices,
}: {
  subscription: TenantSubscription;
  charges: TenantPortalCharges | null;
  onShowInvoices: () => void;
}) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const cost = subscriptionCostRp(subscription);
  const addonCount = subscription.features.filter((feature) => !feature.included_in_plan && !feature.read_only).length;
  const yearly = subscription.billing_cycle === "yearly";

  return (
    <section className={`card tenant-usage-summary${charges ? " tenant-usage-summary-3" : ""}`}>
      <div className="tenant-usage-summary-cell">
        <span className="tenant-usage-stat-label">{t("currentPlanEyebrow")}</span>
        <div className="tenant-usage-plan-title">
          <h2 className="tenant-usage-plan-name">{subscription.plan_name ?? t("noPlanAssigned")}</h2>
          <span className="pill">{yearly ? t("billingYearly") : t("billingMonthly")}</span>
        </div>
        {subscription.plan_code === "legacy" ? <p className="muted tenant-usage-legacy">{t("legacyPlanNote")}</p> : null}
      </div>
      <div className="tenant-usage-summary-cell">
        <span className="tenant-usage-stat-label">{yearly ? t("abo.totalPerYear") : t("abo.totalPerMonth")}</span>
        {cost === null ? (
          <span className="tenant-usage-summary-value">{t("costNotSet")}</span>
        ) : (
          <span className="tenant-usage-summary-inline">
            <span className="tenant-usage-summary-value">{formatRappen(cost, locale)}</span>
            <span className="muted tenant-usage-summary-unit">{addonCount ? t("abo.planWithAddons", { count: addonCount }) : t("abo.planOnly")}</span>
          </span>
        )}
        <SubscriptionDiscountNote subscription={subscription} />
      </div>
      {charges ? (
        <button type="button" className="tenant-usage-summary-cell tenant-usage-summary-link" onClick={onShowInvoices}>
          <span className="tenant-usage-stat-label tenant-usage-summary-link-head">
            <span>{t("abo.tabs.invoices")}</span>
            <span className="tenant-usage-summary-link-more">{t("abo.showInvoices")}</span>
          </span>
          <span className="tenant-usage-summary-inline">
            <span className={`tenant-usage-summary-value${charges.overdue.count ? " tenant-charges-overdue" : ""}`}>{formatRappen(charges.open.amount_rp, locale)}</span>
            <span className={charges.overdue.count ? "tenant-usage-summary-unit tenant-charges-overdue" : "muted tenant-usage-summary-unit"}>{openChargesLabel(charges, t)}</span>
          </span>
        </button>
      ) : null}
    </section>
  );
}

/** Zusatzmodule nach Produktmodul (permissions/features.json) gruppiert, in Katalogreihenfolge. */
function groupAddons(features: TenantSubscriptionFeature[]): { module: string; items: TenantSubscriptionFeature[] }[] {
  const moduleOf = new Map<string, string>(FEATURES.map((feature) => [feature.code, feature.module]));
  const groups = new Map<string, TenantSubscriptionFeature[]>();
  for (const feature of features) {
    const productModule = moduleOf.get(feature.code) ?? "other";
    groups.set(productModule, [...(groups.get(productModule) ?? []), feature]);
  }
  const order: string[] = [...new Set<string>(FEATURES.map((feature) => feature.module)), "other"];
  return [...groups.entries()].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b)).map(([productModule, items]) => ({ module: productModule, items }));
}

/**
 * Kostenaufstellung «Plan & Module»: Grundplan mit den enthaltenen Funktionen, gebuchte
 * Zusatzmodule je Produktmodul, Rabatt und Total - dieselbe Rechnung wie die Kostenvorschau im
 * Backend (Zusatzmodule bei jährlicher Abrechnung Monatspreis x 12, Nur-Lesen-Module kostenlos).
 */
function PlanBreakdown({ subscription }: { subscription: TenantSubscription }) {
  const t = useTranslations("tenantSettings");
  const locale = useLocale();
  const yearly = subscription.billing_cycle === "yearly";
  const factor = yearly ? 12 : 1;
  const planRp = yearly ? subscription.plan_price_yearly_rp : subscription.plan_price_monthly_rp;
  const included = subscription.features.filter((feature) => feature.included_in_plan);
  const addons = subscription.features.filter((feature) => !feature.included_in_plan);
  const activeAddons = addons.filter((feature) => !feature.read_only).length;
  const addonRp = (feature: TenantSubscriptionFeature) => (feature.read_only || !feature.standalone_price_monthly_rp ? 0 : feature.standalone_price_monthly_rp * factor);
  const discount = subscriptionDiscount(subscription);
  const cost = subscriptionCostRp(subscription);

  return (
    <section className="card tenant-plan-card">
      <div className="tenant-plan-head">
        <div className="tenant-plan-title">
          <span className="eyebrow">{t("abo.breakdownEyebrow")}</span>
          <h2 className="tenant-charges-heading">
            {t("abo.breakdownTitle")}{" "}
            <HelpPopover topic={t("abo.breakdownTitle")} docs={{ page: "einstellungen", anchor: "abo" }}>
              {t("help.modules")}
            </HelpPopover>
          </h2>
        </div>
        <Badge variant="success" dot>
          {activeAddons ? t("abo.addonsActive", { count: activeAddons }) : t("abo.planActive")}
        </Badge>
      </div>

      <div className="tenant-plan-row tenant-plan-base">
        <div className="tenant-plan-copy">
          <strong>{subscription.plan_name ? t("abo.basePlan", { name: subscription.plan_name }) : t("noPlanAssigned")}</strong>
          <span className="muted">{t("abo.basePlanHint")}</span>
        </div>
        <span className="tenant-plan-price">{formatRappen(planRp, locale)}</span>
        {included.length > 0 ? (
          <ul className="tenant-plan-chips" aria-label={t("abo.includedLabel")}>
            {included.map((feature) => (
              <li key={feature.code} className="tenant-plan-chip">
                <span className="tenant-plan-chip-check" aria-hidden="true">✓</span>
                {feature.name}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="tenant-plan-section">
        <span className="tenant-usage-stat-label">{t("abo.addonsEyebrow")}</span>
        {addons.length === 0 ? (
          <div className="tenant-plan-row tenant-plan-row-flush">
            <span className="muted">{t("abo.noAddons")}</span>
            <span className="tenant-plan-price muted">{formatRappen(0, locale)}</span>
          </div>
        ) : null}
      </div>
      {groupAddons(addons).map((group) => (
        <div key={group.module} className="tenant-plan-group">
          <div className="tenant-plan-group-head">
            <span>{t(`abo.modules.${group.module}`)}</span>
            <span>{formatGroupSum(group.items.reduce((sum, feature) => sum + addonRp(feature), 0), locale)}</span>
          </div>
          {group.items.map((feature) => (
            <div key={feature.code} className="tenant-plan-row">
              <div className="tenant-plan-copy tenant-plan-copy-inline">
                <strong>{feature.name}</strong>
                <FeatureHint text={feature.read_only ? t("moduleReadOnlyHint") : feature.description} />
              </div>
              {feature.read_only ? (
                <Badge variant="warning" dot>{t("moduleReadOnly")}</Badge>
              ) : addonRp(feature) ? (
                <span className="tenant-plan-price">{t("abo.addonPrice", { price: formatRappen(addonRp(feature), locale) })}</span>
              ) : (
                <span className="tenant-plan-price muted">{t("abo.priceIncluded")}</span>
              )}
            </div>
          ))}
        </div>
      ))}

      {discount ? (
        <div className="tenant-plan-row tenant-plan-discount">
          <span>{t("abo.discountLine", { percent: formatPercentNumber(discount.percent, locale) })}</span>
          <span className="tenant-plan-price">{formatSignedRappen(-discount.savedRp, locale)}</span>
        </div>
      ) : null}

      <div className="tenant-plan-row tenant-plan-total">
        <span>{yearly ? t("abo.totalPerYear") : t("abo.totalPerMonth")}</span>
        <span className="tenant-plan-price">{cost === null ? t("costNotSet") : formatRappen(cost, locale)}</span>
      </div>
      <p className="field-help tenant-plan-foot">
        {t("changePlanHint")} <DocsLink page="einstellungen" anchor="abo">{t("docsLink")}</DocsLink>
      </p>
    </section>
  );
}

/** Summe einer Modulgruppe; nur Nur-Lesen-Module (kostenlos) zeigen keine Summe. */
function formatGroupSum(rp: number, locale: string): string {
  return rp ? formatRappen(rp, locale) : "";
}

function FeatureHint({ text }: { text: string | null }) {
  return text ? <span className="muted">{text}</span> : null;
}

function UsersCard({ subscription, tenantUsers }: { subscription: TenantSubscription; tenantUsers: UserSummary[] }) {
  const t = useTranslations("tenantSettings");
  const userLimit = subscription.effective_user_limit ?? null;
  const pendingInvites = subscription.pending_invite_count ?? 0;
  return (
    <section className="card grid">
      <div className="tenant-usage-card-head">
        <div className="eyebrow">{t("usersEyebrow")}</div>
        <Link href="/users" className="tenant-usage-link">
          {t("manageUsersLink")}
        </Link>
      </div>
      <div>
        <span className="tenant-usage-big-number">{subscription.user_count}</span>
        <span className="tenant-usage-big-number-unit">{userLimit !== null ? t("seatsOf", { limit: userLimit }) : t("seatsUnlimited")}</span>
      </div>
      {userLimit !== null ? <UsageBar value={subscription.user_count} max={userLimit} /> : null}
      <div className="tenant-avatar-row">
        {tenantUsers.length > 0 ? (
          <div className="tenant-user-avatars">
            {tenantUsers.slice(0, 8).map((u) => (
              <span key={u.id} className="tenant-user-avatar" style={{ backgroundColor: colorForUser(u.id) }} title={u.display_name}>
                {initials(u.display_name)}
              </span>
            ))}
            {tenantUsers.length > 8 ? <span className="tenant-user-avatar tenant-user-avatar-overflow">+{tenantUsers.length - 8}</span> : null}
          </div>
        ) : null}
        {userLimit !== null ? (
          <span className="muted tenant-usage-note">
            {t("seatsFree", { count: Math.max(0, userLimit - subscription.user_count - pendingInvites) })}
            {pendingInvites > 0 ? ` · ${t("seatsPendingInvites", { count: pendingInvites })}` : null}
          </span>
        ) : null}
      </div>
    </section>
  );
}

function StorageCard({ subscription, storageUsage }: { subscription: TenantSubscription; storageUsage: StorageUsageRead | null }) {
  const t = useTranslations("tenantSettings");
  const tStorage = useTranslations("storage");
  const storageHints = categoryHints(tStorage);
  const storageLabels = categoryLabels(tStorage);
  const usedBytes = storageUsage?.total_bytes ?? subscription.storage_used_bytes ?? 0;
  const quotaBytes = storageUsage?.quota_bytes ?? null;
  return (
    <section className="card grid tenant-usage-storage-card">
      <div className="tenant-usage-card-head">
        <div className="eyebrow">{t("storageEyebrow")}</div>
        {quotaBytes !== null && usedBytes > quotaBytes ? (
          <Badge variant="danger">{t("quotaExceeded")}</Badge>
        ) : (
          <span className="muted tenant-usage-note">{quotaBytes !== null ? t("quotaLabel", { size: formatFileSize(quotaBytes) }) : t("noQuotaSet")}</span>
        )}
      </div>
      <div>
        <span className="tenant-usage-big-number">{formatFileSize(usedBytes)}</span>
        <span className="tenant-usage-big-number-unit">{t("used")}</span>
      </div>
      {storageUsage && storageUsage.categories.some((c) => c.bytes > 0) ? (
        <>
          <div className="storage-usage-bar">
            {storageUsage.categories
              .filter((c) => c.bytes > 0)
              .map((category) => (
                <div
                  key={category.key}
                  className="storage-usage-segment"
                  style={{ width: `${(category.bytes / Math.max(storageUsage.total_bytes, quotaBytes ?? 0)) * 100}%`, background: CATEGORY_COLORS[category.key] }}
                  title={`${storageLabels[category.key]}: ${formatFileSize(category.bytes)}`}
                />
              ))}
          </div>
          <div className="tenant-usage-note">
            <StorageQuotaComposition planStorageBytes={subscription.included_storage_bytes} packageStorageBytes={subscription.package_storage_bytes} />
          </div>
          <div className="grid tenant-storage-legend">
            {storageUsage.categories
              .filter((c) => c.bytes > 0)
              .map((category) => (
                <div key={category.key}>
                  <div className="tenant-storage-legend-row">
                    <span>
                      <span className="storage-legend-dot" style={{ background: CATEGORY_COLORS[category.key] }} />
                      {storageLabels[category.key]}
                    </span>
                    <span>{formatFileSize(category.bytes)}</span>
                  </div>
                  <div className="muted tenant-storage-legend-hint">{storageHints[category.key]}</div>
                </div>
              ))}
          </div>
        </>
      ) : (
        <>
          <UsageBar value={usedBytes} max={quotaBytes} />
          <div className="muted tenant-usage-note tenant-usage-inline-note">
            <StorageQuotaComposition planStorageBytes={subscription.included_storage_bytes} packageStorageBytes={subscription.package_storage_bytes} />
            {usedBytes === 0 ? <span className="tenant-usage-no-files">{t("noFilesYet")}</span> : null}
          </div>
        </>
      )}
    </section>
  );
}

/** Fortschrittsbalken für Nutzer und Speicher; ohne Limit bleibt er leer. */
function UsageBar({ value, max }: { value: number; max: number | null }) {
  const percent = max ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="tenant-usage-bar">
      <div className={`tenant-usage-bar-fill${max !== null && value > max ? " tenant-usage-bar-over" : ""}`} style={{ width: `${percent}%` }} />
    </div>
  );
}
