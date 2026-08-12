"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { DomainWizardModal } from "@/components/ui/domain-wizard-modal";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { TenantDomain, TenantSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

type Tab = "general" | "domains";

type TenantFormState = {
  name: string;
  publicSlug: string;
  profileImage: File | null;
  profileImageUrl: string | null;
};

export function TenantSettingsManager({ initialTenant }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const tenantId = initialTenant.id;

  const [activeTab, setActiveTab] = useState<Tab>("general");
  const [tenantName, setTenantName] = useState(initialTenant.name);

  const [tenantForm, setTenantForm] = useState<TenantFormState>({
    name: initialTenant.name,
    publicSlug: initialTenant.public_slug ?? "",
    profileImage: null,
    profileImageUrl: initialTenant.profile_image_url,
  });

  const [domains, setDomains] = useState<TenantDomain[]>([]);
  const [domainBusyId, setDomainBusyId] = useState<number | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardDomain, setWizardDomain] = useState<TenantDomain | null>(null);

  useEffect(() => {
    void loadDomains();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function submitTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const formData = new FormData();
      formData.append("name", tenantForm.name);
      if (tenantForm.publicSlug.trim()) {
        formData.append("public_slug", tenantForm.publicSlug.trim());
      }
      if (tenantForm.profileImage) {
        formData.append("profile_image", tenantForm.profileImage);
      }
      const updated = await browserApiFetch<TenantSummary>(`/api/tenants/${tenantId}`, {
        method: "PATCH",
        body: formData
      });
      setTenantForm((current) => ({ ...current, profileImage: null, profileImageUrl: updated.profile_image_url }));
      setTenantName(updated.name);
      showToast("Mandant gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht gespeichert werden", "error");
    }
  }

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

  async function deleteDomain(domainId: number, hostname: string) {
    const ok = await confirm({
      message: `Domain "${hostname}" wirklich entfernen? Der Zugriff über diese Adresse endet sofort.`,
      tone: "danger",
      confirmLabel: "Entfernen",
    });
    if (!ok) return;
    setDomainBusyId(domainId);
    try {
      await browserApiFetch<{ message: string }>(`/api/tenants/${tenantId}/domains/${domainId}`, { method: "DELETE" });
      await loadDomains();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Domain konnte nicht entfernt werden", "error");
    } finally {
      setDomainBusyId(null);
    }
  }

  return (
    <div className="section-stack">
      <div className="page-header">
        <div>
          <h1 className="page-title">Mandant-Einstellungen</h1>
          <p className="muted">Stammdaten und Domains für {tenantName} verwalten.</p>
        </div>
      </div>

      <FilterTabs
        options={[
          { value: "general", label: "Allgemein" },
          { value: "domains", label: `Domains${domains.some((d) => d.status === "pending") ? " ·" : ""}` },
        ]}
        value={activeTab}
        onChange={setActiveTab}
      />

      {activeTab === "general" && (
        <section className="card">
          <div className="eyebrow">Stammdaten</div>
          <form className="grid" onSubmit={submitTenant}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Mandantenname</span>
                <input value={tenantForm.name} onChange={(event) => setTenantForm((current) => ({ ...current, name: event.target.value }))} required />
              </label>
              <label className="field-stack">
                <span className="field-label">Öffentlicher Slug (Abgabebox-URL)</span>
                <input
                  value={tenantForm.publicSlug}
                  onChange={(event) => setTenantForm((current) => ({ ...current, publicSlug: event.target.value.toLowerCase() }))}
                  placeholder="z.B. musterverein"
                  pattern="[a-z0-9-]+"
                />
              </label>
            </div>
            <label className="field-stack">
              <span className="field-label">Profilbild</span>
              {tenantForm.profileImageUrl ? (
                <div className="identity-avatar">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={tenantForm.profileImageUrl} alt={tenantForm.name} />
                </div>
              ) : null}
              <input
                type="file"
                accept="image/*"
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setTenantForm((current) => ({ ...current, profileImage: event.target.files?.[0] ?? null }))
                }
              />
            </label>
            <div className="table-actions table-actions-start">
              <button type="submit" className="button-inline">
                Speichern
              </button>
            </div>
          </form>
        </section>
      )}

      {activeTab === "domains" && (
        <section className="card">
          <div className="eyebrow">Domains</div>
          <p className="muted">
            Eigene Domain für die hocX-App und/oder die Abgabebox. hocx.tweber.ch bzw. die
            Standard-Abgabebox-Domain bleiben zusätzlich immer erreichbar.
          </p>

          {domains.length > 0 && (
            <DataTable className="data-table-lg" columns={["Zweck", "Domain", "Status", ""]}>
              {domains.map((d) => (
                <tr key={d.id}>
                  <td>{d.purpose === "app" ? "hocX-App" : "Abgabebox"}</td>
                  <td className="domain-row-domain">{d.domain}</td>
                  <td>
                    {d.status === "pending" ? (
                      <Badge variant="neutral">Ausstehend</Badge>
                    ) : d.is_healthy ? (
                      <Badge variant="success">Aktiv</Badge>
                    ) : (
                      <Badge variant="danger">
                        <span title="Domain zeigt bei der letzten Prüfung nicht mehr auf hocX — DNS-Einträge prüfen">Nicht erreichbar</span>
                      </Badge>
                    )}
                  </td>
                  <td>
                    <div className="table-actions">
                      {d.status === "pending" && (
                        <button type="button" className="button-inline" onClick={() => openWizardToResume(d)}>
                          Einrichten
                        </button>
                      )}
                      <button
                        type="button"
                        className="button-inline button-danger"
                        disabled={domainBusyId === d.id}
                        onClick={() => deleteDomain(d.id, d.domain)}
                      >
                        {domainBusyId === d.id ? "…" : "Entfernen"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </DataTable>
          )}

          <button type="button" className="domain-add-trigger" onClick={openWizardForNewDomain}>
            + Domain hinzufügen
          </button>
        </section>
      )}

      <DomainWizardModal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        tenantId={tenantId}
        domain={wizardDomain}
        onChanged={loadDomains}
      />
    </div>
  );
}
