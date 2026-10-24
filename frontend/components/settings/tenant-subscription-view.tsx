"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ChargeFilter, TenantBillingCard, TenantOverdueBanner, useTenantCharges } from "@/components/settings/tenant-charges";
import { Badge } from "@/components/ui/badge";
import { NavIcon, NavIconKey } from "@/components/ui/nav-icons";
import { colorForUser, initials } from "@/components/protocol/collaboration-presence";
import { CATEGORY_COLORS, categoryHints, StorageQuotaComposition } from "@/components/storage/storage-usage-view";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize, formatRappen } from "@/lib/utils/format";
import type { Locale } from "@/i18n/locale-config.generated";
import { StorageUsageRead, TenantSubscription, TenantSummary, UserSummary } from "@/types/api";

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

export function TenantSubscriptionView({ initialTenant }: Props) {
  const t = useTranslations("tenantSettings");
  const storageHints = categoryHints(useTranslations("storage"));
  const locale = useLocale();
  const { subscription, subscriptionLoading, storageUsage, tenantUsers } = useTenantSubscriptionData(initialTenant.id);
  const charges = useTenantCharges(initialTenant.id);
  const [chargeFilter, setChargeFilter] = useState<ChargeFilter>("all");
  const billingRef = useRef<HTMLDivElement | null>(null);
  const hasCharges = Boolean(charges && charges.items.length > 0);
  const billingLabel = subscription?.billing_cycle === "yearly" ? t("billingYearly") : t("billingMonthly");
  const cost = subscription ? subscriptionCostRp(subscription) : null;
  const userLimit = subscription?.effective_user_limit ?? null;
  const usedBytes = storageUsage?.total_bytes ?? subscription?.storage_used_bytes ?? 0;
  const quotaBytes = storageUsage?.quota_bytes ?? null;

  function showOpenCharges() {
    setChargeFilter("open");
    billingRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <>
      {subscriptionLoading && !subscription ? (
        <section className="card">
          <div className="eyebrow">{t("currentPlanEyebrow")}</div>
          <div className="muted">{t("loadingPlan")}</div>
        </section>
      ) : !subscription ? (
        <section className="card">
          <div className="eyebrow">{t("currentPlanEyebrow")}</div>
          <div className="muted">{t("subscriptionLoadFailed")}</div>
        </section>
      ) : (
        <>
          {charges ? <TenantOverdueBanner charges={charges} onShow={showOpenCharges} /> : null}

          <section className={`card tenant-usage-summary${hasCharges ? " tenant-usage-summary-3" : ""}`}>
            <div className="tenant-usage-summary-cell">
              <span className="tenant-usage-stat-label">{t("currentPlanEyebrow")}</span>
              <div className="tenant-usage-plan-title">
                <h2 className="tenant-usage-plan-name">{subscription.plan_name ?? t("noPlanAssigned")}</h2>
                <span className="pill">{billingLabel}</span>
              </div>
              {subscription.plan_code === "legacy" ? <p className="muted tenant-usage-legacy">{t("legacyPlanNote")}</p> : null}
            </div>
            <div className="tenant-usage-summary-cell">
              <span className="tenant-usage-stat-label">{t("costLabel")}</span>
              {cost === null ? (
                <span className="tenant-usage-summary-value">{t("costNotSet")}</span>
              ) : (
                <span className="tenant-usage-summary-stack">
                  <span className="tenant-usage-summary-value">{formatRappen(cost, locale as Locale)}</span>
                  <span className="muted tenant-usage-summary-unit">{subscription.billing_cycle === "monthly" ? t("perMonthUnit") : t("perYearUnit")}</span>
                </span>
              )}
            </div>
            {charges && hasCharges ? (
              <div className="tenant-usage-summary-cell">
                <span className="tenant-usage-stat-label">{t("charges.openLabel")}</span>
                <span className="tenant-usage-summary-inline">
                  <span className="tenant-usage-summary-value">{formatRappen(charges.open.amount_rp, locale as Locale)}</span>
                  <span className={charges.overdue.count ? "tenant-usage-summary-unit tenant-charges-overdue" : "muted tenant-usage-summary-unit"}>
                    {charges.open.count === 0
                      ? t("charges.allPaidShort")
                      : charges.overdue.count
                        ? t("charges.openCountOverdue", { count: charges.open.count, overdue: charges.overdue.count })
                        : t("charges.openCount", { count: charges.open.count })}
                  </span>
                </span>
              </div>
            ) : null}
          </section>

          {charges && hasCharges ? (
            <div ref={billingRef}>
              <TenantBillingCard charges={charges} filter={chargeFilter} onFilterChange={setChargeFilter} />
            </div>
          ) : null}

          <div className="tenant-usage-cards">
            <section className="card grid">
              <div className="tenant-usage-card-head">
                <div className="eyebrow">{t("usersEyebrow")}</div>
                <Link href="/users" className="tenant-usage-link">
                  {t("manageUsersLink")}
                </Link>
              </div>
              <div>
                <span className="tenant-usage-big-number">{subscription.user_count}</span>
                <span className="tenant-usage-big-number-unit">
                  {userLimit !== null ? t("seatsOf", { limit: userLimit }) : t("seatsUnlimited")}
                </span>
              </div>
              <UsageBar value={subscription.user_count} max={userLimit} />
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
                  <span className="muted tenant-usage-note">{t("seatsFree", { count: Math.max(0, userLimit - subscription.user_count) })}</span>
                ) : null}
              </div>
            </section>

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
                          title={`${category.label}: ${formatFileSize(category.bytes)}`}
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
                              {category.label}
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
          </div>

          <section className="card">
            <div className="eyebrow">{t("includedModulesEyebrow")}</div>
            {subscription.features.length === 0 ? (
              <div className="muted">{t("noModulesBooked")}</div>
            ) : (
              <div className="grid tenant-module-list">
                {subscription.features.map((feature) => (
                  <div key={feature.code} className="tenant-module-card">
                    <span className="tenant-module-icon">
                      <NavIcon name={FEATURE_ICONS[feature.code] ?? "documents"} />
                    </span>
                    <div className="tenant-module-copy">
                      <strong>{feature.name}</strong>
                      {feature.description ? <div className="muted">{feature.description}</div> : null}
                      {!feature.included_in_plan && feature.standalone_price_monthly_rp !== null ? (
                        <div className="muted">{t("pricePerMonth", { price: formatRappen(feature.standalone_price_monthly_rp, locale as Locale) })}</div>
                      ) : null}
                    </div>
                    <Badge variant="success" dot className="tenant-module-status">
                      {t("moduleActive")}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </>
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
