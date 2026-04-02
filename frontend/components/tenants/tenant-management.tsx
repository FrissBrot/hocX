"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { TenantSummary } from "@/types/api";

type Props = {
  initialTenants: TenantSummary[];
  canCreateTenant: boolean;
};

type TenantFormState = {
  id?: number;
  name: string;
  profileImage: File | null;
};

export function TenantManagement({ initialTenants, canCreateTenant }: Props) {
  const [tenants, setTenants] = useState(initialTenants);
  const [status, setStatus] = useState("Bereit");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [tenantForm, setTenantForm] = useState<TenantFormState>({ name: "", profileImage: null });
  const [search, setSearch] = useState("");

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

  async function submitTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(tenantForm.id ? "Mandant wird gespeichert..." : "Mandant wird erstellt...");
    setStatusTone("neutral");

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
      setStatus(tenantForm.id ? "Mandant gespeichert" : "Mandant erstellt");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Mandant konnte nicht gespeichert werden");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <StatusBanner tone={statusTone} message={status} />

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
          <tr key={tenant.id} className="table-row-clickable" onClick={() => openTenantModal(tenant)}>
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
    </div>
  );
}
