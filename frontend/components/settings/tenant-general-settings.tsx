"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { initials } from "@/components/protocol/collaboration-presence";
import { domainStatus, TenantDomainRowContent } from "@/components/settings/tenant-domain-row";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { TenantDomain, TenantSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

type TenantFormState = {
  name: string;
  publicSlug: string;
  profileImage: File | null;
  profileImageUrl: string | null;
};

export function TenantGeneralSettings({ initialTenant }: Props) {
  const router = useRouter();
  const showToast = useToast();
  const tenantId = initialTenant.id;

  const [tenantForm, setTenantForm] = useState<TenantFormState>({
    name: initialTenant.name,
    publicSlug: initialTenant.public_slug ?? "",
    profileImage: null,
    profileImageUrl: initialTenant.profile_image_url,
  });
  const [domains, setDomains] = useState<TenantDomain[]>([]);
  const profileImageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void loadDomains();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function loadDomains() {
    try {
      const rows = await browserApiFetch<TenantDomain[]>(`/api/tenants/${tenantId}/domains`);
      setDomains(rows);
    } catch {
      // keine Domains bzw. Fehler beim Laden — kein Vorschau-Eintrag
    }
  }

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
      router.refresh();
      showToast("Mandant gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht gespeichert werden", "error");
    }
  }

  const primaryDomain = domains.find((d) => d.purpose === "app") ?? domains[0] ?? null;

  return (
    <>
      <section className="card">
        <div className="eyebrow">Stammdaten</div>
        <form className="grid" onSubmit={submitTenant}>
          <div className="tenant-avatar-row">
            <div className="identity-avatar tenant-avatar-preview">
              {tenantForm.profileImageUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={tenantForm.profileImageUrl} alt={tenantForm.name} />
              ) : (
                <span>{initials(tenantForm.name || initialTenant.name)}</span>
              )}
            </div>
            <button type="button" className="button-secondary" onClick={() => profileImageInputRef.current?.click()}>
              Profilbild ändern
            </button>
            <input
              ref={profileImageInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setTenantForm((current) => ({ ...current, profileImage: event.target.files?.[0] ?? null }))
              }
            />
          </div>
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
          {primaryDomain ? (
            <div className="tenant-domain-row">
              <TenantDomainRowContent domain={primaryDomain} />
              <div className="tenant-domain-row-trailing">
                <span className={`record-list-row-dot record-list-row-dot-${domainStatus(primaryDomain).variant}`} />
              </div>
            </div>
          ) : null}
          <div className="table-actions table-actions-start">
            <button type="submit" className="button-primary">
              Speichern
            </button>
          </div>
        </form>
      </section>
    </>
  );
}
