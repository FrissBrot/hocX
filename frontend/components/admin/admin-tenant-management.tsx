"use client";

import { FormEvent, useState } from "react";

import { AdminTenantSettingsModal } from "@/components/admin/admin-tenant-settings-modal";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { AdminTenantSummary } from "@/types/api";

type Props = {
  initialTenants: AdminTenantSummary[];
};

export function AdminTenantManagement({ initialTenants }: Props) {
  const showToast = useToast();
  const [tenants, setTenants] = useState(initialTenants);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const [settingsTenant, setSettingsTenant] = useState<AdminTenantSummary | null>(null);
  const [cloneModalOpen, setCloneModalOpen] = useState(false);
  const [cloneTenant, setCloneTenant] = useState<AdminTenantSummary | null>(null);
  const [cloneName, setCloneName] = useState("");
  const [cloneMode, setCloneMode] = useState<"structure" | "full">("structure");
  const [cloneBusy, setCloneBusy] = useState(false);

  const visibleTenants = tenants.filter((tenant) =>
    !search.trim() || tenant.name.toLowerCase().includes(search.trim().toLowerCase())
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<AdminTenantSummary>("/api/admin/tenants", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setTenants((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      setModalOpen(false);
      setName("");
      showToast("Mandant erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht erstellt werden", "error");
    }
  }

  function openSettings(tenant: AdminTenantSummary) {
    setSettingsTenant(tenant);
    setSettingsModalOpen(true);
  }

  function handleTenantSaved(updated: AdminTenantSummary) {
    setTenants((current) => current.map((tenant) => (tenant.id === updated.id ? updated : tenant)));
    setSettingsTenant(updated);
  }

  function openClone(tenant: AdminTenantSummary) {
    setCloneTenant(tenant);
    setCloneName(`${tenant.name} (Kopie)`);
    setCloneMode("structure");
    setCloneModalOpen(true);
  }

  async function submitClone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!cloneTenant) return;
    setCloneBusy(true);
    try {
      const cloned = await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${cloneTenant.id}/clone`, {
        method: "POST",
        body: JSON.stringify({ new_name: cloneName, mode: cloneMode }),
      });
      setTenants((current) => [...current, cloned].sort((a, b) => a.name.localeCompare(b.name)));
      setCloneModalOpen(false);
      showToast("Mandant geklont", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht geklont werden", "error");
    } finally {
      setCloneBusy(false);
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Mandanten"
        description="Alle Mandanten im System. Neue Mandanten werden hier zentral angelegt."
        actions={
          <button type="button" className="button-inline" onClick={() => setModalOpen(true)}>
            Neuer Mandant
          </button>
        }
      />

      <article className="card">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Mandanten durchsuchen" />
        </label>
      </article>

      <DataTable columns={["Bild", "Mandant", "Teilnehmer", "Benutzer", "Erstellt am", "Aktionen"]} emptyMessage="Keine Mandanten gefunden.">
        {visibleTenants.map((tenant) => (
          <tr key={tenant.id} className="table-row-clickable" onClick={() => openSettings(tenant)}>
            <td>
              <div className="identity-avatar">
                {tenant.profile_image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={tenant.profile_image_url} alt={tenant.name} />
                ) : (
                  <span>{tenant.name.slice(0, 1) || "T"}</span>
                )}
              </div>
            </td>
            <td>
              <strong>{tenant.name}</strong>
              {tenant.public_slug ? <div className="muted">/{tenant.public_slug}</div> : null}
            </td>
            <td>{tenant.participant_count}</td>
            <td>{tenant.user_count}</td>
            <td>{new Date(tenant.created_at).toLocaleDateString("de-CH")}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline"
                  onClick={(event) => {
                    event.stopPropagation();
                    openSettings(tenant);
                  }}
                >
                  Einstellungen
                </button>
                <button
                  type="button"
                  className="button-inline button-ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    openClone(tenant);
                  }}
                >
                  Klonen
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Neuer Mandant" description="Legt einen neuen Mandanten mit Standard-Dokumentvorlage an.">
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">Mandantenname</span>
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Erstellen
            </button>
          </div>
        </form>
      </Modal>

      <AdminTenantSettingsModal
        open={settingsModalOpen}
        onClose={() => setSettingsModalOpen(false)}
        tenant={settingsTenant}
        onSaved={handleTenantSaved}
      />

      <Modal
        open={cloneModalOpen}
        onClose={() => setCloneModalOpen(false)}
        title={cloneTenant ? `"${cloneTenant.name}" klonen` : "Mandant klonen"}
        description="Legt einen neuen Mandanten an, der auf diesem hier basiert."
      >
        <form className="grid" onSubmit={submitClone}>
          <label className="field-stack">
            <span className="field-label">Name des neuen Mandanten</span>
            <input value={cloneName} onChange={(event) => setCloneName(event.target.value)} required />
          </label>
          <div className="field-stack">
            <span className="field-label">Umfang</span>
            <label className="field-radio-option">
              <input
                type="radio"
                name="clone-mode"
                value="structure"
                checked={cloneMode === "structure"}
                onChange={() => setCloneMode("structure")}
              />
              <span>
                <strong>Nur Struktur &amp; Konfiguration</strong>
                <div className="muted">Vorlagen, Formularfelder, Dokumentvorlagen, Zyklen, Konten. Keine Teilnehmer, Termine, Protokolle oder Benutzer.</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="clone-mode"
                value="full"
                checked={cloneMode === "full"}
                onChange={() => setCloneMode("full")}
              />
              <span>
                <strong>Alles (vollständige Kopie)</strong>
                <div className="muted">Zusätzlich Teilnehmer, Termine, Protokolle, Bussen, Todos, Abgaben und Benutzerzugriffe — z.B. für Tests.</div>
              </span>
            </label>
          </div>
          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline" disabled={cloneBusy}>
              {cloneBusy ? "Wird geklont…" : "Klonen"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
