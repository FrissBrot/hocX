"use client";

import { FormEvent, useEffect, useState } from "react";

import { AdminTenantSettingsModal } from "@/components/admin/admin-tenant-settings-modal";
import { ActionMenu } from "@/components/ui/action-menu";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { formatFileSize } from "@/lib/utils/format";
import { AdminTenantPage, AdminTenantSummary } from "@/types/api";

type Props = {
  initialPage: AdminTenantPage;
};

const PAGE_SIZE = 50;

export function AdminTenantManagement({ initialPage }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const tenants = page.items;
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
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTenant, setExportTenant] = useState<AdminTenantSummary | null>(null);
  const [exportScope, setExportScope] = useState<"structure" | "structure_lists" | "full" | "full_abgabebox">("structure");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importName, setImportName] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [loading, setLoading] = useState(false);

  // Server now applies `search` before pagination (audit A1, 2026-08-16 - fetchPage below
  // sends it as `q`), so page.items is already the matching set for the current page.
  const visibleTenants = tenants;

  async function fetchPage(nextOffset: number, query: string) {
    setLoading(true);
    try {
      const q = query.trim();
      const result = await browserApiFetch<AdminTenantPage>(
        `/api/admin/tenants?limit=${PAGE_SIZE}&offset=${nextOffset}${q ? `&q=${encodeURIComponent(q)}` : ""}`
      );
      setPage(result);
    } catch {
      // keep showing the previous page rather than blanking the table on a transient error
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void fetchPage(offset, search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  // Debounced re-fetch from offset 0 whenever the search text changes - see the identical
  // pattern in admin-user-management.tsx.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (offset !== 0) {
        setOffset(0);
      } else {
        void fetchPage(0, search);
      }
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await browserApiFetch<AdminTenantSummary>("/api/admin/tenants", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      await fetchPage(offset, search);
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
    setPage((current) => ({
      ...current,
      items: current.items.map((tenant) => (tenant.id === updated.id ? updated : tenant)),
    }));
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
      await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${cloneTenant.id}/clone`, {
        method: "POST",
        body: JSON.stringify({ new_name: cloneName, mode: cloneMode }),
      });
      await fetchPage(offset, search);
      setCloneModalOpen(false);
      showToast("Mandant geklont", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht geklont werden", "error");
    } finally {
      setCloneBusy(false);
    }
  }

  function openExport(tenant: AdminTenantSummary) {
    setExportTenant(tenant);
    setExportScope("structure");
    setExportModalOpen(true);
  }

  function submitExport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!exportTenant) return;
    const a = document.createElement("a");
    a.href = `/api/admin/tenants/${exportTenant.id}/export?scope=${exportScope}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setExportModalOpen(false);
  }

  async function deleteTenant(tenant: AdminTenantSummary) {
    const confirmed = await confirm({
      title: `"${tenant.name}" löschen?`,
      message: `${tenant.participant_count} Teilnehmer, ${tenant.user_count} Benutzerzugriffe und alle Protokolle, Termine und Dateien dieses Mandanten gehen dabei verloren. Das kann nicht rückgängig gemacht werden.`,
      tone: "danger",
      confirmLabel: "Endgültig löschen"
    });
    if (!confirmed) return;
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}`, { method: "DELETE" });
      // Deleting the last item on a page would strand the view past the new end - fall
      // back a page first if that's about to happen (changing offset re-triggers the load).
      if (tenants.length === 1 && offset > 0) {
        setOffset(offset - PAGE_SIZE);
      } else {
        await fetchPage(offset, search);
      }
      showToast("Mandant gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht gelöscht werden", "error");
    }
  }

  function openImport() {
    setImportName("");
    setImportFile(null);
    setImportModalOpen(true);
  }

  async function submitImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!importFile) return;
    setImportBusy(true);
    try {
      const formData = new FormData();
      formData.append("new_name", importName);
      formData.append("file", importFile);
      const result = await browserApiFetch<{ tenant: AdminTenantSummary; warnings: string[] }>(
        "/api/admin/tenants/import",
        { method: "POST", body: formData }
      );
      await fetchPage(offset, search);
      setImportModalOpen(false);
      if (result.warnings.length > 0) {
        showToast(`Mandant importiert mit ${result.warnings.length} Hinweis(en) - siehe Konsole`, "success");
        console.warn("Import-Hinweise:", result.warnings);
      } else {
        showToast("Mandant importiert", "success");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht importiert werden", "error");
    } finally {
      setImportBusy(false);
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Mandanten"
        description="Alle Mandanten im System. Neue Mandanten werden hier zentral angelegt."
        actions={
          <>
            <button type="button" className="button-inline button-ghost" onClick={openImport}>
              Mandant importieren
            </button>
            <button type="button" className="button-inline" onClick={() => setModalOpen(true)}>
              Neuer Mandant
            </button>
          </>
        }
      />

      <article className="card">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <SearchInput value={search} onChange={setSearch} placeholder="Mandanten durchsuchen" />
        </label>
      </article>

      <DataTable
        columns={["Bild", "Mandant", "Teilnehmer", "Benutzer", "Speicher", "Erstellt am", "Aktionen"]}
        emptyMessage={loading ? "Wird geladen…" : "Keine Mandanten gefunden."}
      >
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
            <td>
              {tenant.storage_quota_bytes ? (
                <>
                  <div
                    className={`storage-usage-bar-mini${tenant.storage_used_bytes > tenant.storage_quota_bytes ? " storage-usage-bar-mini-over" : ""}`}
                  >
                    <div
                      className="storage-usage-segment-fill"
                      style={{ width: `${Math.min((tenant.storage_used_bytes / tenant.storage_quota_bytes) * 100, 100)}%` }}
                    />
                  </div>
                  <div className="muted">
                    {formatFileSize(tenant.storage_used_bytes)} / {formatFileSize(tenant.storage_quota_bytes)}
                  </div>
                </>
              ) : (
                <span className="muted">{formatFileSize(tenant.storage_used_bytes)} (kein Limit)</span>
              )}
            </td>
            <td>{new Date(tenant.created_at).toLocaleDateString("de-CH")}</td>
            <td>
              <ActionMenu
                items={[
                  { label: "Einstellungen", onClick: () => openSettings(tenant) },
                  { label: "Klonen", onClick: () => openClone(tenant) },
                  { label: "Exportieren", onClick: () => openExport(tenant) },
                  { label: "Löschen", onClick: () => deleteTenant(tenant), danger: true },
                ]}
              />
            </td>
          </tr>
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />

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

      <Modal
        open={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
        title={exportTenant ? `"${exportTenant.name}" exportieren` : "Mandant exportieren"}
        description="Erstellt eine ZIP-Datei zum Herunterladen, die später im Adminpanel wieder als neuer Mandant importiert werden kann."
      >
        <form className="grid" onSubmit={submitExport}>
          <div className="field-stack">
            <span className="field-label">Umfang</span>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="structure"
                checked={exportScope === "structure"}
                onChange={() => setExportScope("structure")}
              />
              <span>
                <strong>Nur Struktur</strong>
                <div className="muted">Zyklen, Formularfelder, Dokumentvorlagen, Listen (nur Definition, ohne Inhalt), Konten, Benutzerrollen und verifizierte Domains (inkl. Prüfcode).</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="structure_lists"
                checked={exportScope === "structure_lists"}
                onChange={() => setExportScope("structure_lists")}
              />
              <span>
                <strong>Struktur + Listeninhalt</strong>
                <div className="muted">Wie oben, zusätzlich die Einträge in den Listen. Ohne Teilnehmer/Termine - Listeneinträge, die auf einen Teilnehmer oder Termin verweisen, werden dabei ohne diesen Verweis übernommen.</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="full"
                checked={exportScope === "full"}
                onChange={() => setExportScope("full")}
              />
              <span>
                <strong>Struktur + alle Protokolle</strong>
                <div className="muted">Zusätzlich Teilnehmer, Termine, Protokolle, Bussen, Todos und Dateien (inkl. Fotos-Galerie). Ohne Abgabebox.</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="full_abgabebox"
                checked={exportScope === "full_abgabebox"}
                onChange={() => setExportScope("full_abgabebox")}
              />
              <span>
                <strong>Alles inklusive Abgabebox</strong>
                <div className="muted">Wie oben, zusätzlich Abgabebox-Konfiguration und hochgeladene Dateien.</div>
              </span>
            </label>
          </div>
          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Exportieren
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        title="Mandant importieren"
        description="Legt anhand einer zuvor exportierten ZIP-Datei einen neuen Mandanten an."
      >
        <form className="grid" onSubmit={submitImport}>
          <label className="field-stack">
            <span className="field-label">Name des neuen Mandanten</span>
            <input value={importName} onChange={(event) => setImportName(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">Export-Datei (.zip)</span>
            <input
              type="file"
              accept=".zip"
              onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline" disabled={importBusy || !importFile}>
              {importBusy ? "Wird importiert…" : "Importieren"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
