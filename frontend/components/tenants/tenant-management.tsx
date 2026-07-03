"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { OidcConfigRead, OidcConfigWrite, TenantSummary } from "@/types/api";

type Props = {
  initialTenants: TenantSummary[];
  canCreateTenant: boolean;
};

type TenantFormState = {
  id?: number;
  name: string;
  profileImage: File | null;
};

const defaultOidcForm: OidcConfigWrite = {
  enabled: false,
  auto_redirect: false,
  issuer_url: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile",
};

export function TenantManagement({ initialTenants, canCreateTenant }: Props) {
  const showToast = useToast();
  const [tenants, setTenants] = useState(initialTenants);
  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [tenantForm, setTenantForm] = useState<TenantFormState>({ name: "", profileImage: null });
  const [search, setSearch] = useState("");

  const [oidcModalOpen, setOidcModalOpen] = useState(false);
  const [oidcTenantId, setOidcTenantId] = useState<number | null>(null);
  const [oidcTenantName, setOidcTenantName] = useState("");
  const [oidcForm, setOidcForm] = useState<OidcConfigWrite>(defaultOidcForm);
  const [oidcLoading, setOidcLoading] = useState(false);

  const filteredTenants = useMemo(
    () =>
      tenants.filter((tenant) => {
        const haystack = `${tenant.name} ${tenant.profile_image_url ? "bild" : ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      }),
    [search, tenants]
  );

  function openTenantModal(tenant?: TenantSummary) {
    setTenantForm({
      id: tenant?.id,
      name: tenant?.name ?? "",
      profileImage: null
    });
    setTenantModalOpen(true);
  }

  async function openOidcModal(tenant: TenantSummary) {
    setOidcTenantId(tenant.id);
    setOidcTenantName(tenant.name);
    setOidcForm(defaultOidcForm);
    setOidcModalOpen(true);
    try {
      const cfg = await browserApiFetch<OidcConfigRead>(`/api/tenants/${tenant.id}/oidc-config`);
      setOidcForm({
        enabled: cfg.enabled,
        auto_redirect: cfg.auto_redirect,
        issuer_url: cfg.issuer_url,
        client_id: cfg.client_id,
        client_secret: "",
        scopes: cfg.scopes,
      });
    } catch {
      // no config yet — defaults are fine
    }
  }

  async function submitTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      let updated: TenantSummary;
      if (tenantForm.id) {
        const formData = new FormData();
        formData.append("name", tenantForm.name);
        if (tenantForm.profileImage) {
          formData.append("profile_image", tenantForm.profileImage);
        }
        updated = await browserApiFetch<TenantSummary>(`/api/tenants/${tenantForm.id}`, {
          method: "PATCH",
          body: formData
        });
        setTenants((current) => current.map((tenant) => (tenant.id === updated.id ? updated : tenant)));
      } else {
        updated = await browserApiFetch<TenantSummary>("/api/tenants", {
          method: "POST",
          body: JSON.stringify({ name: tenantForm.name })
        });
        setTenants((current) => [...current, updated].sort((left, right) => left.name.localeCompare(right.name)));
      }

      setTenantModalOpen(false);
      showToast(tenantForm.id ? "Mandant gespeichert" : "Mandant erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht gespeichert werden", "error");
    }
  }

  async function submitOidc(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!oidcTenantId) return;
    setOidcLoading(true);
    try {
      await browserApiFetch<OidcConfigRead>(`/api/tenants/${oidcTenantId}/oidc-config`, {
        method: "PUT",
        body: JSON.stringify(oidcForm),
      });
      showToast("OIDC-Konfiguration gespeichert", "success");
      // Clear secret field after successful save
      setOidcForm((f) => ({ ...f, client_secret: "" }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Speichern", "error");
    } finally {
      setOidcLoading(false);
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Mandanten"
        description="Nur Mandanten, in denen du Admin bist, können hier bearbeitet werden."
        actions={
          canCreateTenant ? (
            <button type="button" className="button-inline" onClick={() => openTenantModal()}>
              Neuer Mandant
            </button>
          ) : null
        }
      />

      <article className="card">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Mandanten durchsuchen" />
          </label>
          <div className="card">
            <div className="eyebrow">Überblick</div>
            <div className="status-row">
              <span className="pill">{filteredTenants.length} sichtbar</span>
              <span className="pill">{tenants.length} gesamt</span>
            </div>
          </div>
        </div>
      </article>

      <DataTable columns={["Mandant", "Profilbild", "Aktionen"]} emptyMessage="Keine Mandanten für den aktuellen Filter gefunden.">
        {filteredTenants.map((tenant) => (
          <tr key={tenant.id}>
            <td>
              <strong>{tenant.name}</strong>
              <div className="muted">{tenant.profile_image_url ? "Mit Profilbild" : "Ohne Profilbild"}</div>
            </td>
            <td>{tenant.profile_image_url ? "Vorhanden" : "Kein Bild"}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button type="button" className="button-inline" onClick={() => openTenantModal(tenant)}>
                  Bearbeiten
                </button>
                <button type="button" className="button-inline" onClick={() => openOidcModal(tenant)}>
                  OIDC
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={tenantModalOpen}
        onClose={() => setTenantModalOpen(false)}
        title={tenantForm.id ? "Mandant bearbeiten" : "Mandant erstellen"}
        description="Name und Profilbild für genau diesen Mandanten verwalten."
      >
        <form className="grid" onSubmit={submitTenant}>
          <label className="field-stack">
            <span className="field-label">Mandantenname</span>
            <input value={tenantForm.name} onChange={(event) => setTenantForm((current) => ({ ...current, name: event.target.value }))} required />
          </label>
          <label className="field-stack">
            <span className="field-label">Profilbild</span>
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
      </Modal>

      <Modal
        open={oidcModalOpen}
        onClose={() => setOidcModalOpen(false)}
        title={`OIDC – ${oidcTenantName}`}
        description="OpenID Connect Provider für diesen Mandanten konfigurieren. Admins verwenden immer die lokale Anmeldung."
      >
        <form className="grid" onSubmit={submitOidc}>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">OIDC aktiviert</span>
              <select
                value={oidcForm.enabled ? "1" : "0"}
                onChange={(e) => setOidcForm((f) => ({ ...f, enabled: e.target.value === "1" }))}
              >
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
      </Modal>
    </div>
  );
}
