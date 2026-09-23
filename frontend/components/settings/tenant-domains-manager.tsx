"use client";

import { useEffect, useState } from "react";

import { ActionMenu } from "@/components/ui/action-menu";
import { DomainWizardModal } from "@/components/ui/domain-wizard-modal";
import { EmptyState } from "@/components/ui/empty-state";
import { domainStatus, TenantDomainRowContent } from "@/components/settings/tenant-domain-row";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { TenantDomain, TenantSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

export function TenantDomainsManager({ initialTenant }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const tenantId = initialTenant.id;
  const hasCustomDomainFeature = initialTenant.enabled_features.includes("custom_domain");

  const [domains, setDomains] = useState<TenantDomain[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardDomain, setWizardDomain] = useState<TenantDomain | null>(null);

  useEffect(() => {
    void loadDomains();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function loadDomains() {
    try {
      const rows = await browserApiFetch<TenantDomain[]>(`/api/tenants/${tenantId}/domains`);
      setDomains(rows);
    } catch {
      // keine Domains bzw. Fehler beim Laden — leere Liste anzeigen
    }
  }

  function openWizardForNewDomain() {
    setWizardDomain(null);
    setWizardOpen(true);
  }

  function openWizardToResume(domain: TenantDomain) {
    setWizardDomain(domain);
    setWizardOpen(true);
  }

  async function deleteDomain(domainId: string, hostname: string) {
    const ok = await confirm({
      message: `Domain "${hostname}" wirklich entfernen? Der Zugriff über diese Adresse endet sofort.`,
      tone: "danger",
      confirmLabel: "Entfernen",
    });
    if (!ok) return;
    try {
      await browserApiFetch<{ message: string }>(`/api/tenants/${tenantId}/domains/${domainId}`, { method: "DELETE" });
      await loadDomains();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Domain konnte nicht entfernt werden", "error");
    }
  }

  function renderRow(d: TenantDomain) {
    const status = domainStatus(d);
    return (
      <div key={d.id} className="tenant-domain-row">
        <TenantDomainRowContent domain={d} />
        <div className="tenant-domain-row-trailing">
          {d.status === "pending" ? (
            <button type="button" className="button-secondary" onClick={() => openWizardToResume(d)}>
              Einrichten
            </button>
          ) : null}
          <span className={`record-list-row-dot record-list-row-dot-${status.variant}`} />
          <ActionMenu
            ariaLabel={`Aktionen für ${d.domain}`}
            items={[{ label: "Entfernen", onClick: () => deleteDomain(d.id, d.domain), danger: true }]}
          />
        </div>
      </div>
    );
  }

  return (
    <>
      {domains.length === 0 ? (
        <EmptyState
          icon="document"
          title="Noch keine eigene Domain"
          description="Verbinde eine Domain wie app.dein-verein.ch, damit Mitglieder hocX unter eurer Adresse erreichen. Die Verifizierung erfolgt über einen DNS-Eintrag."
          actions={
            hasCustomDomainFeature ? (
              <button type="button" className="button-primary" onClick={openWizardForNewDomain}>
                + Domain hinzufügen
              </button>
            ) : undefined
          }
          hint="Bis dahin bleibt der Mandant unter der Standard-Adresse erreichbar."
        />
      ) : (
        <section className="card">
          <div className="eyebrow">Domains</div>
          <p className="muted">
            Eigene Domain für die hocX-App und/oder die Abgabebox. hocx.example.com bzw. die
            Standard-Abgabebox-Domain bleiben zusätzlich immer erreichbar.
          </p>

          <div className="grid tenant-domain-list">{domains.map((d) => renderRow(d))}</div>

          {hasCustomDomainFeature ? (
            <button type="button" className="domain-add-trigger" onClick={openWizardForNewDomain}>
              + Domain hinzufügen
            </button>
          ) : null}
        </section>
      )}

      <DomainWizardModal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        tenantId={tenantId}
        domain={wizardDomain}
        onChanged={loadDomains}
      />
    </>
  );
}
