"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { AdminTenantSummary, OidcConfigRead, OidcConfigWrite } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  tenant: AdminTenantSummary | null;
  onSaved: (tenant: AdminTenantSummary) => void;
};

type TenantFormState = {
  name: string;
  publicSlug: string;
  profileImage: File | null;
  profileImageUrl: string | null;
};

const emptyTenantForm: TenantFormState = { name: "", publicSlug: "", profileImage: null, profileImageUrl: null };

const defaultOidcForm: OidcConfigWrite = {
  enabled: false,
  auto_redirect: false,
  issuer_url: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile"
};

export function AdminTenantSettingsModal({ open, onClose, tenant, onSaved }: Props) {
  const showToast = useToast();
  const [tenantForm, setTenantForm] = useState<TenantFormState>(emptyTenantForm);
  const [oidcForm, setOidcForm] = useState<OidcConfigWrite>(defaultOidcForm);
  const [oidcLoading, setOidcLoading] = useState(false);

  useEffect(() => {
    if (!open || !tenant) {
      return;
    }
    setTenantForm({
      name: tenant.name,
      publicSlug: tenant.public_slug ?? "",
      profileImage: null,
      profileImageUrl: tenant.profile_image_url
    });
    setOidcForm(defaultOidcForm);

    (async () => {
      try {
        const cfg = await browserApiFetch<OidcConfigRead>(`/api/admin/tenants/${tenant.id}/oidc-config`);
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
  }, [open, tenant]);

  async function submitTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    try {
      const formData = new FormData();
      formData.append("name", tenantForm.name);
      if (tenantForm.publicSlug.trim()) {
        formData.append("public_slug", tenantForm.publicSlug.trim());
      }
      if (tenantForm.profileImage) {
        formData.append("profile_image", tenantForm.profileImage);
      }
      const updated = await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${tenant.id}`, {
        method: "PATCH",
        body: formData
      });
      setTenantForm((current) => ({ ...current, profileImage: null, profileImageUrl: updated.profile_image_url }));
      showToast("Mandant gespeichert", "success");
      onSaved(updated);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht gespeichert werden", "error");
    }
  }

  async function submitOidc(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    setOidcLoading(true);
    try {
      await browserApiFetch<OidcConfigRead>(`/api/admin/tenants/${tenant.id}/oidc-config`, {
        method: "PUT",
        body: JSON.stringify(oidcForm)
      });
      showToast("OIDC-Konfiguration gespeichert", "success");
      setOidcForm((f) => ({ ...f, client_secret: "" }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Fehler beim Speichern", "error");
    } finally {
      setOidcLoading(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Mandant-Einstellungen – ${tenant?.name ?? ""}`}
      description="Stammdaten und OpenID-Connect-Anmeldung für diesen Mandanten verwalten."
      size="wide"
    >
      <div className="grid">
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

        <section className="card">
          <div className="eyebrow">OIDC</div>
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
      </div>
    </Modal>
  );
}
