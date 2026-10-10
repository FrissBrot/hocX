"use client";

import { useRouter } from "next/navigation";
import { ChangeEvent, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileActionSheet, MobileCard, MobileCardHeader, MobileEmpty, MobileFab, MobileGroupCard, MobileListRow, MobileProgress, MobileStat } from "@/components/mobile/mobile-ui";
import { initials } from "@/components/protocol/collaboration-presence";
import { domainStatus } from "@/components/settings/tenant-domain-row";
import { useTenantDomains } from "@/components/settings/tenant-domains-manager";
import { useTenantGeneralForm } from "@/components/settings/tenant-general-settings";
import { FEATURE_ICONS, subscriptionCostRp, useTenantSubscriptionData } from "@/components/settings/tenant-subscription-view";
import { CATEGORY_COLORS, categoryHints, StorageQuotaComposition } from "@/components/storage/storage-usage-view";
import { Badge } from "@/components/ui/badge";
import { CopyField } from "@/components/ui/copy-field";
import { DomainWizardModal } from "@/components/ui/domain-wizard-modal";
import { NavIcon } from "@/components/ui/nav-icons";
import type { Locale } from "@/i18n/locale-config.generated";
import { formatFileSize, formatRappen } from "@/lib/utils/format";
import type { TenantDomain, TenantSummary } from "@/types/api";

// Inhalte der drei Mandanten-Seiten in der Mobile-Shell (Rahmen: MobileTenantSettings in
// mobile-admin.tsx). Laden/Speichern kommt aus denselben Hooks wie am Desktop.

function DomainRow({ domain, onClick }: { domain: TenantDomain; onClick?: () => void }) {
  const t = useTranslations("tenantSettings");
  const status = domainStatus(domain, t);
  return (
    <MobileListRow
      onClick={onClick}
      label={
        <span className="mobile-row-stack">
          <span className="mobile-row-title mobile-tenant-domain-host">{domain.domain}</span>
          <span className={`mobile-row-meta tenant-domain-row-status-${status.variant}`} title={status.title}>
            {domain.purpose === "app" ? t("purposeApp") : t("purposeAbgabebox")} · {status.label}
          </span>
        </span>
      }
      trailing={<span className={`record-list-row-dot record-list-row-dot-${status.variant}`} />}
    />
  );
}

// ── Allgemein ───────────────────────────────────────────────────────────

export function MobileTenantGeneral({ initialTenant }: { initialTenant: TenantSummary }) {
  const t = useTranslations("tenantSettings");
  const tNav = useTranslations("nav");
  const tMobile = useTranslations("mobile");
  const router = useRouter();
  const { tenantForm, setTenantForm, submitTenant, saving, primaryDomain } = useTenantGeneralForm(initialTenant);
  const profileImageInputRef = useRef<HTMLInputElement>(null);
  const previewName = tenantForm.name || initialTenant.name;

  return (
    <form className="mobile-section mobile-tenant-form" onSubmit={submitTenant}>
      <MobileCard className="mobile-tenant-identity">
        <div className="identity-avatar mobile-tenant-avatar">
          {tenantForm.profileImageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={tenantForm.profileImageUrl} alt={previewName} />
          ) : (
            <span>{initials(previewName)}</span>
          )}
        </div>
        <div className="mobile-row-stack">
          <span className="mobile-row-title">{previewName}</span>
          {tenantForm.profileImage ? <span className="mobile-row-meta">{tenantForm.profileImage.name}</span> : null}
          <button type="button" className="mobile-text-button mobile-tenant-avatar-button" onClick={() => profileImageInputRef.current?.click()}>
            {t("changeProfileImage")}
          </button>
        </div>
        <input
          ref={profileImageInputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(event: ChangeEvent<HTMLInputElement>) => setTenantForm((current) => ({ ...current, profileImage: event.target.files?.[0] ?? null }))}
        />
      </MobileCard>

      <MobileCard className="mobile-tenant-fields">
        <span className="mobile-eyebrow">{t("masterDataEyebrow")}</span>
        <label className="field-stack">
          <span className="field-label">{t("tenantNameLabel")}</span>
          <input value={tenantForm.name} onChange={(event) => setTenantForm((current) => ({ ...current, name: event.target.value }))} required />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("publicSlugLabel")}</span>
          <input
            value={tenantForm.publicSlug}
            onChange={(event) => setTenantForm((current) => ({ ...current, publicSlug: event.target.value.toLowerCase() }))}
            placeholder={t("publicSlugPlaceholder")}
            pattern="[a-z0-9-]+"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <div className="field-stack">
          <span className="field-label">{t("tenantIdLabel")}</span>
          <CopyField label={t("tenantIdLabel")} value={initialTenant.id} />
          <span className="field-help">{t("tenantIdHelp")}</span>
        </div>
      </MobileCard>

      {primaryDomain ? (
        <MobileGroupCard label={tNav("domains")}>
          <DomainRow domain={primaryDomain} onClick={() => router.push("/tenant-settings/domains")} />
        </MobileGroupCard>
      ) : null}

      <button type="submit" className="button-primary mobile-button-block" disabled={saving}>
        {tMobile("common.save")}
      </button>
    </form>
  );
}

// ── Domains ─────────────────────────────────────────────────────────────

export function MobileTenantDomains({ initialTenant }: { initialTenant: TenantSummary }) {
  const t = useTranslations("tenantSettings");
  const tMobile = useTranslations("mobile");
  const hasCustomDomainFeature = initialTenant.enabled_features.includes("custom_domain");
  const { domains, loadDomains, deleteDomain } = useTenantDomains(initialTenant.id);
  const [actionsFor, setActionsFor] = useState<TenantDomain | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardDomain, setWizardDomain] = useState<TenantDomain | null>(null);

  function openWizard(domain: TenantDomain | null) {
    setWizardDomain(domain);
    setWizardOpen(true);
  }

  return (
    <>
      {domains.length === 0 ? (
        <MobileEmpty
          title={t("emptyDomainTitle")}
          hint={`${t("emptyDomainDescription")} ${hasCustomDomainFeature ? t("emptyDomainHintWithFeature") : t("emptyDomainHintWithoutFeature")}`}
        />
      ) : (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {domains.map((domain) => (
              <DomainRow key={domain.id} domain={domain} onClick={() => setActionsFor(domain)} />
            ))}
          </div>
          <p className="mobile-hint-box">{t("domainsDescription")}</p>
        </div>
      )}

      {hasCustomDomainFeature ? <MobileFab label={tMobile("tenant.fab")} onClick={() => openWizard(null)} /> : null}

      {actionsFor ? (
        <MobileActionSheet
          title={actionsFor.domain}
          onClose={() => setActionsFor(null)}
          actions={[
            ...(actionsFor.status === "pending" ? [{ label: tMobile("tenant.resumeSetup"), onClick: () => openWizard(actionsFor) }] : []),
            { label: tMobile("common.delete"), onClick: () => void deleteDomain(actionsFor.id, actionsFor.domain), danger: true },
          ]}
        />
      ) : null}

      <DomainWizardModal open={wizardOpen} onClose={() => setWizardOpen(false)} tenantId={initialTenant.id} domain={wizardDomain} onChanged={loadDomains} />
    </>
  );
}

// ── Abo & Nutzung ───────────────────────────────────────────────────────

export function MobileTenantSubscription({ initialTenant }: { initialTenant: TenantSummary }) {
  const t = useTranslations("tenantSettings");
  const tMobile = useTranslations("mobile");
  const storageHints = categoryHints(useTranslations("storage"));
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { subscription, subscriptionLoading, storageUsage } = useTenantSubscriptionData(initialTenant.id);

  if (!subscription) {
    return <MobileEmpty title={subscriptionLoading ? t("loadingPlan") : t("subscriptionLoadFailed")} />;
  }

  const billingLabel = subscription.billing_cycle === "monthly" ? t("billingMonthly") : t("billingYearly");
  const cost = subscriptionCostRp(subscription);
  const usedBytes = storageUsage?.total_bytes ?? subscription.storage_used_bytes;
  const quotaBytes = storageUsage?.quota_bytes ?? null;
  const userLimit = subscription.effective_user_limit;
  const categories = storageUsage?.categories.filter((c) => c.bytes > 0) ?? [];
  const overQuota = quotaBytes !== null && usedBytes > quotaBytes;
  const hasQuotaComposition = subscription.included_storage_bytes !== null || subscription.package_storage_bytes > 0;

  return (
    <div className="mobile-section">
      <MobileCard className="mobile-tenant-plan">
        <MobileCardHeader label={t("currentPlanEyebrow")} badge={<span className="pill">{billingLabel}</span>} />
        <div className="mobile-tenant-plan-body">
          <div className="mobile-tenant-plan-name">{subscription.plan_name ?? t("noPlanAssigned")}</div>
          <div className="mobile-muted-sm">
            {t("costLabel")}: {cost === null ? t("costNotSet") : `${formatRappen(cost, locale)} · ${billingLabel}`}
          </div>
          {subscription.plan_code === "legacy" ? <p className="mobile-hint-box">{t("legacyPlanNote")}</p> : null}
        </div>
      </MobileCard>

      <div className="mobile-stat-grid">
        <MobileStat
          label={t("usersEyebrow")}
          value={subscription.user_count}
          sub={
            userLimit !== null ? (
              <MobileProgress value={subscription.user_count} max={userLimit} label={t("ofLimit", { limit: userLimit })} />
            ) : (
              t("ofLimit", { limit: t("unlimited") })
            )
          }
        />
        <MobileStat
          label={t("storageEyebrow")}
          value={formatFileSize(usedBytes)}
          sub={
            quotaBytes !== null ? (
              <MobileProgress value={usedBytes} max={quotaBytes} label={formatFileSize(quotaBytes)} />
            ) : (
              t("noQuotaSet")
            )
          }
        />
      </div>

      {overQuota || categories.length > 0 || hasQuotaComposition ? (
      <MobileGroupCard label={t("storageEyebrow")}>
        {overQuota ? <MobileListRow label={t("quotaExceeded")} trailing={<Badge variant="danger">{formatFileSize(usedBytes - quotaBytes!)}</Badge>} /> : null}
        {categories.map((category) => (
          <MobileListRow
            key={category.key}
            leading={<span className="storage-legend-dot" style={{ background: CATEGORY_COLORS[category.key] }} />}
            label={
              <span className="mobile-row-stack">
                <span className="mobile-row-title">{category.label}</span>
                <span className="mobile-row-meta mobile-row-meta-wrap">{storageHints[category.key]}</span>
              </span>
            }
            value={formatFileSize(category.bytes)}
          />
        ))}
        {hasQuotaComposition ? (
          <div className="mobile-tenant-quota-note">
            <StorageQuotaComposition planStorageBytes={subscription.included_storage_bytes} packageStorageBytes={subscription.package_storage_bytes} />
          </div>
        ) : null}
      </MobileGroupCard>
      ) : null}

      <MobileGroupCard label={t("includedModulesEyebrow")}>
        {subscription.features.length === 0 ? (
          <p className="mobile-card-empty">{t("noModulesBooked")}</p>
        ) : (
          subscription.features.map((feature) => (
            <MobileListRow
              key={feature.code}
              leading={
                <span className="mobile-list-row-navicon">
                  <NavIcon name={FEATURE_ICONS[feature.code] ?? "documents"} />
                </span>
              }
              label={
                <span className="mobile-row-stack">
                  <span className="mobile-row-title">{feature.name}</span>
                  {feature.description ? <span className="mobile-row-meta mobile-row-meta-wrap">{feature.description}</span> : null}
                  {!feature.included_in_plan && feature.standalone_price_monthly_rp !== null ? (
                    <span className="mobile-row-meta">{t("pricePerMonth", { price: formatRappen(feature.standalone_price_monthly_rp, locale) })}</span>
                  ) : null}
                </span>
              }
              trailing={
                <Badge variant="success" dot>
                  {t("moduleActive")}
                </Badge>
              }
            />
          ))
        )}
      </MobileGroupCard>

      <div className="mobile-card mobile-list-card">
        <MobileListRow label={tMobile("tenant.manageUsers")} onClick={() => router.push("/users")} />
      </div>
    </div>
  );
}
