"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { DomainWizardModal } from "@/components/ui/domain-wizard-modal";
import { EmptyState } from "@/components/ui/empty-state";
import {
  bookablePurposes,
  domainErrorMessage,
  domainsDescriptionText,
  domainStatus,
  TenantDomainRowContent,
  useMainAppDomain,
} from "@/components/settings/tenant-domain-row";
import { HelpPopover } from "@/components/ui/help-popover";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { TenantDomain, TenantSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

/** Domain-Liste eines Mandanten samt Löschen (mit Rückfrage) - geteilt zwischen Desktop und Mobile. */
export function useTenantDomains(tenantId: string) {
  const t = useTranslations("tenantSettings");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const confirm = useConfirm();
  const [domains, setDomains] = useState<TenantDomain[]>([]);
  // Ladefehler nicht als «noch keine Domain» zeigen (Audit 08): sonst legt jemand die
  // vermeintlich verschwundene Domain neu an.
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    void loadDomains();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function loadDomains() {
    try {
      const rows = await browserApiFetch<TenantDomain[]>(`/api/tenants/${tenantId}/domains`);
      setDomains(rows);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }

  async function deleteDomain(domainId: string, hostname: string) {
    const ok = await confirm({
      message: t("deleteDomainConfirm", { hostname }),
      tone: "danger",
      confirmLabel: tCommon("delete"),
    });
    if (!ok) return;
    try {
      await browserApiFetch<{ message: string }>(`/api/tenants/${tenantId}/domains/${domainId}`, { method: "DELETE" });
      await loadDomains();
    } catch (error) {
      showToast(domainErrorMessage(error, t, "deleteDomainFailed"), "error");
    }
  }

  return { domains, loadDomains, deleteDomain, loadError };
}

export function TenantDomainsManager({ initialTenant }: Props) {
  const t = useTranslations("tenantSettings");
  const tCommon = useTranslations("common");
  const tenantId = initialTenant.id;
  // Eigene App-/Abgabebox-Domain (custom_domain) und Prüf-Domain (verify_domain) sind getrennt buchbar
  const purposes = bookablePurposes(initialTenant.enabled_features);
  const hasCustomDomainFeature = purposes.length > 0;
  const { domains, loadDomains, deleteDomain, loadError } = useTenantDomains(tenantId);
  const mainDomain = useMainAppDomain();

  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardDomain, setWizardDomain] = useState<TenantDomain | null>(null);

  function openWizardForNewDomain() {
    setWizardDomain(null);
    setWizardOpen(true);
  }

  function openWizardToResume(domain: TenantDomain) {
    setWizardDomain(domain);
    setWizardOpen(true);
  }

  function renderRow(d: TenantDomain) {
    const status = domainStatus(d, t);
    return (
      <div key={d.id} className="tenant-domain-row">
        <TenantDomainRowContent domain={d} />
        <div className="tenant-domain-row-trailing">
          {d.status === "pending" ? (
            <button type="button" className="button-secondary" onClick={() => openWizardToResume(d)}>
              {t("setup")}
            </button>
          ) : !d.is_healthy ? (
            // Aktive, aber unerreichbare Domain: DNS-Ansicht und erneute Prüfung (Audit 08)
            <button type="button" className="button-secondary" onClick={() => openWizardToResume(d)}>
              {t("recheckDomain")}
            </button>
          ) : null}
          <span className={`record-list-row-dot record-list-row-dot-${status.variant}`} />
          <ActionMenu
            ariaLabel={t("domainActionsAriaLabel", { domain: d.domain })}
            items={[{ label: tCommon("delete"), onClick: () => deleteDomain(d.id, d.domain), danger: true }]}
          />
        </div>
      </div>
    );
  }

  return (
    <>
      {loadError ? (
        <section className="card">
          <StatusBanner tone="error" message={t("domainsLoadFailed")} />
          <div className="table-actions table-actions-start">
            <button type="button" className="button-secondary" onClick={() => void loadDomains()}>
              {t("retryLoad")}
            </button>
          </div>
        </section>
      ) : domains.length === 0 ? (
        <EmptyState
          icon="document"
          title={t("emptyDomainTitle")}
          description={t("emptyDomainDescription")}
          actions={
            hasCustomDomainFeature ? (
              <button type="button" className="button-primary" onClick={openWizardForNewDomain}>
                {t("addDomain")}
              </button>
            ) : undefined
          }
          hint={
            hasCustomDomainFeature
              ? t("emptyDomainHintWithFeature")
              : t("emptyDomainHintWithoutFeature")
          }
        />
      ) : (
        <section className="card">
          <div className="eyebrow">
            {t("domainsEyebrow")}{" "}
            <HelpPopover topic={t("domainsEyebrow")} docs={{ page: "einstellungen", anchor: "domains" }}>
              {t("help.domains")}
            </HelpPopover>
          </div>
          <p className="muted">
            {domainsDescriptionText(t, mainDomain)}
          </p>

          <div className="grid tenant-domain-list">{domains.map((d) => renderRow(d))}</div>

          {hasCustomDomainFeature ? (
            <button type="button" className="domain-add-trigger" onClick={openWizardForNewDomain}>
              {t("addDomain")}
            </button>
          ) : null}
        </section>
      )}

      <DomainWizardModal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        tenantId={tenantId}
        domain={wizardDomain}
        purposes={purposes}
        onChanged={loadDomains} domains={domains}
      />
    </>
  );
}
