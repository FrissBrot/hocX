"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { DomainWizardModal } from "@/components/ui/domain-wizard-modal";
import { DataTable } from "@/components/ui/data-table";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { OidcConfigRead, OidcConfigWrite, TenantDomain, TenantSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

type Tab = "general" | "credentials" | "domains";

type TenantFormState = {
  name: string;
  publicSlug: string;
  profileImage: File | null;
  profileImageUrl: string | null;
};

const defaultOidcForm: OidcConfigWrite = {
  enabled: false,
  auto_redirect: false,
  issuer_url: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile",
};

export function TenantSettingsManager({ initialTenant }: Props) {
  const showToast = useToast();
  const tenantId = initialTenant.id;

  const [activeTab, setActiveTab] = useState<Tab>("general");
  const [tenantName, setTenantName] = useState(initialTenant.name);

  const [tenantForm, setTenantForm] = useState<TenantFormState>({
    name: initialTenant.name,
    publicSlug: initialTenant.public_slug ?? "",
    profileImage: null,
    profileImageUrl: initialTenant.profile_image_url,
  });

  const [oidcForm, setOidcForm] = useState<OidcConfigWrite>(defaultOidcForm);
  const [oidcLoading, setOidcLoading] = useState(false);

  const [domains, setDomains] = useState<TenantDomain[]>([]);
  const [domainBusyId, setDomainBusyId] = useState<number | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardDomain, setWizardDomain] = useState<TenantDomain | null>(null);

  useEffect(() => {
    void loadDomains();

    (async () => {
      try {
        const cfg = await browserApiFetch<OidcConfigRead>(`/api/tenants/${tenantId}/oidc-config`);
        setOidcForm({
          enabled: cfg.enabled,
          auto_redirect: cfg.auto_redirect,
          issuer_url: cfg.issuer_url,
          client_id: cfg.client_id,
          client_secret: "",
          scopes: cfg.scopes
        });
      } catch {
        // no config yet — defaults are fine
      }
    })();
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

  async function submitOidc(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOidcLoading(true);
    try {
      await browserApiFetch<OidcConfigRead>(`/api/tenants/${tenantId}/oidc-config`, {
        method: "PUT",
        body: JSON.stringify(oidcForm)
      });
      showToast("Zugangsdaten gespeichert", "success");
      setOidcForm((f) => ({ ...f, client_secret: "" }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Speichern", "error");
    } finally {
      setOidcLoading(false);
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

  async function deleteDomain(domainId: number) {
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
        <h1 className="page-title">Mandant-Einstellungen – {tenantName}</h1>
        <p className="page-description">Stammdaten, Zugangsdaten und Domains für diesen Mandanten verwalten.</p>
      </div>

      <div className="segment-control">
        <button type="button" className={`segment-button${activeTab === "general" ? " segment-button-active" : ""}`} onClick={() => setActiveTab("general")}>
          Allgemein
        </button>
        <button type="button" className={`segment-button${activeTab === "credentials" ? " segment-button-active" : ""}`} onClick={() => setActiveTab("credentials")}>
          Zugangsdaten
        </button>
        <button type="button" className={`segment-button${activeTab === "domains" ? " segment-button-active" : ""}`} onClick={() => setActiveTab("domains")}>
          Domains {domains.some((d) => d.status === "pending") ? "·" : ""}
        </button>
      </div>

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

      {activeTab === "credentials" && (
        <section className="card">
          <div className="eyebrow">Zugangsdaten · OpenID Connect</div>
          <p className="muted">Externe Anmeldung (SSO) für Mitglieder dieses Mandanten konfigurieren.</p>
          <form className="grid" onSubmit={submitOidc}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">OIDC aktiviert</span>
                <select value={oidcForm.enabled ? "1" : "0"} onChange={(e) => setOidcForm((f) => ({ ...f, enabled: e.target.value === "1" }))}>
                  <option value="0">Nein</option>
                  <option value="1">Ja</option>
                </select>
              </label>
              <label className="field-stack">
                <span className="field-label">Auto-Redirect (Nicht-Admins)</span>
                <select
                  value={oidcForm.auto_redirect ? "1" : "0"}
                  onChange={(e) => setOidcForm((f) => ({ ...f, auto_redirect: e.target.value === "1" }))}
                  disabled={!oidcForm.enabled}
                >
                  <option value="0">Nein</option>
                  <option value="1">Ja</option>
                </select>
              </label>
            </div>

            <label className="field-stack">
              <span className="field-label">Issuer URL</span>
              <input
                value={oidcForm.issuer_url}
                onChange={(e) => setOidcForm((f) => ({ ...f, issuer_url: e.target.value }))}
                placeholder="https://accounts.example.com"
                disabled={!oidcForm.enabled}
              />
            </label>

            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Client ID</span>
                <input
                  value={oidcForm.client_id}
                  onChange={(e) => setOidcForm((f) => ({ ...f, client_id: e.target.value }))}
                  placeholder="my-app"
                  disabled={!oidcForm.enabled}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Client Secret</span>
                <input
                  type="password"
                  value={oidcForm.client_secret}
                  onChange={(e) => setOidcForm((f) => ({ ...f, client_secret: e.target.value }))}
                  placeholder="Leer lassen = unverändert"
                  autoComplete="new-password"
                  disabled={!oidcForm.enabled}
                />
              </label>
            </div>

            <label className="field-stack">
              <span className="field-label">Scopes</span>
              <input
                value={oidcForm.scopes}
                onChange={(e) => setOidcForm((f) => ({ ...f, scopes: e.target.value }))}
                placeholder="openid email profile"
                disabled={!oidcForm.enabled}
              />
            </label>

            <div className="table-actions table-actions-start">
              <button type="submit" className="button-inline" disabled={oidcLoading}>
                {oidcLoading ? "…" : "Speichern"}
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
            <DataTable columns={["Zweck", "Domain", "Status", ""]}>
              {domains.map((d) => (
                <tr key={d.id}>
                  <td>{d.purpose === "app" ? "hocX-App" : "Abgabebox"}</td>
                  <td className="domain-row-domain">{d.domain}</td>
                  <td>
                    {d.status === "pending" ? (
                      <span className="pill">Ausstehend</span>
                    ) : d.is_healthy ? (
                      <span className="pill pill-success">Aktiv</span>
                    ) : (
                      <span className="pill pill-error" title="Domain zeigt bei der letzten Prüfung nicht mehr auf hocX — DNS-Einträge prüfen">
                        Nicht erreichbar
                      </span>
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
                        onClick={() => deleteDomain(d.id)}
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
