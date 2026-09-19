"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { formatFileSize } from "@/lib/utils/format";
import { StorageBreakdown } from "@/components/storage/storage-usage-view";
import { AdminTenantSummary, AdminTenantUser, StorageUsageRead, TenantCleanupCategory, TenantCleanupCounts } from "@/types/api";

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

export const ROLE_OPTIONS: { code: string; label: string }[] = [
  { code: "reader", label: "Reader" },
  { code: "kassier", label: "Kassier" },
  { code: "writer", label: "Writer" },
  { code: "admin", label: "Admin" }
];

const CLEANUP_CATEGORIES: { key: TenantCleanupCategory; title: string; description: string }[] = [
  {
    key: "protocols",
    title: "Protokolle",
    description: "Alle Protokolle – manuell erstellte und importierte – inklusive der Word-Import-Warteschlange."
  },
  {
    key: "list_entries",
    title: "Daten aus Listen",
    description: "Alle Einträge in allen Listen. Die Listen selbst (Name, Spalten) bleiben erhalten."
  },
  {
    key: "lists_full",
    title: "Listen komplett",
    description: "Listen inklusive ihrer Einträge. Löscht auch Abgabebox-Konfigurationen, die an eine dieser Listen gekoppelt sind."
  },
  {
    key: "events",
    title: "Termine",
    description: "Alle Termine/Anlässe."
  },
  {
    key: "todos",
    title: "Todos",
    description: "Eigenständige Todos. Todos, die an ein Protokoll gebunden sind, verschwinden bereits mit „Protokolle“."
  },
  {
    key: "participants",
    title: "Teilnehmer/Personen",
    description: "Alle angelegten Teilnehmer/Personen-Stammdaten."
  },
  {
    key: "documents",
    title: "Hochgeladene Dokumente",
    description: "Word-/PDF-Importe und Abgabebox-Uploads, inklusive dadurch verwaister Dateien."
  }
];

export function AdminTenantSettingsModal({ open, onClose, tenant, onSaved }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [tenantForm, setTenantForm] = useState<TenantFormState>(emptyTenantForm);

  const [tenantUsers, setTenantUsers] = useState<AdminTenantUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [mfaModalUser, setMfaModalUser] = useState<AdminTenantUser | null>(null);

  const [cleanupCounts, setCleanupCounts] = useState<TenantCleanupCounts | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupSelected, setCleanupSelected] = useState<Set<TenantCleanupCategory>>(new Set());
  const [cleanupConfirmName, setCleanupConfirmName] = useState("");
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [cleanupLastResult, setCleanupLastResult] = useState<TenantCleanupCounts | null>(null);

  const [storageUsage, setStorageUsage] = useState<StorageUsageRead | null>(null);
  const [storageLoading, setStorageLoading] = useState(false);
  const [quotaMbInput, setQuotaMbInput] = useState("");
  const [quotaBusy, setQuotaBusy] = useState(false);

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

    void loadTenantUsers(tenant.id);

    setCleanupSelected(new Set());
    setCleanupConfirmName("");
    setCleanupLastResult(null);
    void loadCleanupPreview(tenant.id);

    setQuotaMbInput(tenant.storage_quota_bytes !== null ? String(Math.round(tenant.storage_quota_bytes / (1024 * 1024))) : "");
    void loadStorageUsage(tenant.id);
  }, [open, tenant]);

  async function loadStorageUsage(tenantId: string) {
    setStorageLoading(true);
    try {
      const result = await browserApiFetch<StorageUsageRead>(`/api/admin/tenants/${tenantId}/storage`);
      setStorageUsage(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Speicherverbrauch konnte nicht geladen werden", "error");
    } finally {
      setStorageLoading(false);
    }
  }

  async function submitQuota(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    const trimmed = quotaMbInput.trim();
    const quotaMb = trimmed === "" ? null : Number(trimmed);
    if (quotaMb !== null && (!Number.isFinite(quotaMb) || quotaMb < 1)) {
      showToast("Kontingent muss eine Zahl grösser 0 sein", "error");
      return;
    }
    setQuotaBusy(true);
    try {
      const updated = await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${tenant.id}/storage-quota`, {
        method: "PATCH",
        body: JSON.stringify({ quota_mb: quotaMb }),
      });
      onSaved(updated);
      setStorageUsage((current) => (current ? { ...current, quota_bytes: updated.storage_quota_bytes } : current));
      showToast("Speicherkontingent gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Speicherkontingent konnte nicht gespeichert werden", "error");
    } finally {
      setQuotaBusy(false);
    }
  }

  async function loadCleanupPreview(tenantId: string) {
    setCleanupLoading(true);
    try {
      const result = await browserApiFetch<TenantCleanupCounts>(`/api/admin/tenants/${tenantId}/cleanup/preview`);
      setCleanupCounts(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Vorschau konnte nicht geladen werden", "error");
    } finally {
      setCleanupLoading(false);
    }
  }

  function toggleCleanupCategory(key: TenantCleanupCategory) {
    setCleanupSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  const allCleanupSelected = CLEANUP_CATEGORIES.every((category) => cleanupSelected.has(category.key));

  function toggleAllCleanupCategories() {
    setCleanupSelected(allCleanupSelected ? new Set() : new Set(CLEANUP_CATEGORIES.map((category) => category.key)));
  }

  const cleanupNameMatches = !!tenant && cleanupConfirmName.trim() === tenant.name;

  async function submitCleanup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant || cleanupSelected.size === 0 || !cleanupNameMatches) return;
    if (
      !(await confirm({
        message: `${cleanupSelected.size} Datenkategorie(n) von "${tenant.name}" werden unwiderruflich gelöscht. Fortfahren?`,
        tone: "danger",
        confirmLabel: "Endgültig löschen"
      }))
    )
      return;
    setCleanupBusy(true);
    try {
      const result = await browserApiFetch<TenantCleanupCounts>(`/api/admin/tenants/${tenant.id}/cleanup`, {
        method: "POST",
        body: JSON.stringify({ categories: Array.from(cleanupSelected), confirm_name: cleanupConfirmName.trim() })
      });
      setCleanupLastResult(result);
      setCleanupSelected(new Set());
      setCleanupConfirmName("");
      showToast("Mandant aufgeräumt", "success");
      void loadCleanupPreview(tenant.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Aufräumen fehlgeschlagen", "error");
    } finally {
      setCleanupBusy(false);
    }
  }

  async function loadTenantUsers(tenantId: string) {
    setUsersLoading(true);
    try {
      const result = await browserApiFetch<AdminTenantUser[]>(`/api/admin/tenants/${tenantId}/users`);
      setTenantUsers(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzer konnten nicht geladen werden", "error");
    } finally {
      setUsersLoading(false);
    }
  }

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

  async function changeUserRole(userId: string, roleCode: string) {
    if (!tenant) return;
    const previous = tenantUsers;
    setTenantUsers((current) => current.map((u) => (u.user_id === userId ? { ...u, role_code: roleCode } : u)));
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}/users/${userId}`, {
        method: "PUT",
        body: JSON.stringify({ role_code: roleCode })
      });
      showToast("Rolle geändert", "success");
    } catch (error) {
      setTenantUsers(previous);
      showToast(error instanceof Error ? error.message : "Rolle konnte nicht geändert werden", "error");
    }
  }

  async function removeUser(userId: string, displayName: string) {
    if (!tenant) return;
    if (
      !(await confirm({
        message: `Benutzer "${displayName}" endgültig löschen? Das Konto gehört nur zu diesem Mandanten und ist danach weg.`,
        tone: "danger",
        confirmLabel: "Löschen"
      }))
    )
      return;
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}/users/${userId}`, { method: "DELETE" });
      setTenantUsers((current) => current.filter((u) => u.user_id !== userId));
      showToast("Benutzer gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzer konnte nicht gelöscht werden", "error");
    }
  }

  if (!tenant) {
    return null;
  }

  return (
    <Modal open={open} onClose={onClose} title={`Mandant-Einstellungen – ${tenant.name}`} description="" size="wide">
      <Tabs
        tabs={[
          {
            id: "stammdaten",
            label: "Stammdaten",
            content: (
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
                  <button type="submit" className="button-secondary">
                    Speichern
                  </button>
                </div>
              </form>
            )
          },
          {
            id: "benutzer",
            label: `Benutzer (${tenantUsers.length})`,
            content: (
              <div className="grid">
                <div className="table-shell">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>E-Mail</th>
                        <th>Rolle</th>
                        <th>MFA</th>
                        <th>Aktion</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tenantUsers.map((u) => (
                        <tr key={u.user_id}>
                          <td>
                            {u.display_name}
                            {!u.login_enabled && <div className="muted">Login deaktiviert</div>}
                          </td>
                          <td className="muted">{u.email}</td>
                          <td>
                            <select value={u.role_code} onChange={(event) => changeUserRole(u.user_id, event.target.value)}>
                              {ROLE_OPTIONS.map((r) => (
                                <option key={r.code} value={r.code}>
                                  {r.label}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <button type="button" className="button-secondary button-ghost" onClick={() => setMfaModalUser(u)}>
                              Anzeigen
                            </button>
                          </td>
                          <td>
                            <button type="button" className="button-secondary button-ghost" onClick={() => removeUser(u.user_id, u.display_name)}>
                              Löschen
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!usersLoading && tenantUsers.length === 0 && <div className="table-empty muted">Dieser Mandant hat noch keine Benutzer.</div>}
                </div>
                <p className="muted">Jedes Konto gehört genau einem Mandanten. Neue Benutzer legst du unter „Benutzer“ an und wählst dort den Mandanten.</p>

              </div>
            )
          },
          {
            id: "aufraeumen",
            label: "Aufräumen",
            content: (
              <form className="grid" onSubmit={submitCleanup}>
                <div className="form-error-banner">
                  Diese Aktion löscht Daten endgültig aus der Datenbank – es gibt kein Zurück. Der Mandant selbst, Vorlagen,
                  Formularfelder und Benutzerzugriffe bleiben in jedem Fall erhalten.
                </div>

                <div className="field-stack">
                  <span className="field-label">Was soll gelöscht werden?</span>
                  <label className="field-radio-option">
                    <input type="checkbox" checked={allCleanupSelected} onChange={toggleAllCleanupCategories} />
                    <span>
                      <strong>Alle Daten löschen</strong>
                      <div className="muted">Wählt alle Kategorien unten auf einmal aus.</div>
                    </span>
                  </label>
                  {CLEANUP_CATEGORIES.map((category) => (
                    <label key={category.key} className="field-radio-option">
                      <input
                        type="checkbox"
                        checked={cleanupSelected.has(category.key)}
                        onChange={() => toggleCleanupCategory(category.key)}
                      />
                      <span>
                        <strong>
                          {category.title}
                          {cleanupCounts ? <span className="muted"> – {cleanupCounts[category.key]} vorhanden</span> : null}
                        </strong>
                        <div className="muted">{category.description}</div>
                      </span>
                    </label>
                  ))}
                </div>

                {cleanupLastResult ? (
                  <div className="muted">
                    Zuletzt gelöscht: {Object.entries(cleanupLastResult)
                      .filter(([, count]) => count > 0)
                      .map(([key, count]) => `${CLEANUP_CATEGORIES.find((c) => c.key === key)?.title ?? key}: ${count}`)
                      .join(", ") || "nichts (0 Treffer in den gewählten Kategorien)"}
                  </div>
                ) : null}

                <label className="field-stack">
                  <span className="field-label">Zur Bestätigung Mandantenname eintippen: „{tenant.name}“</span>
                  <input
                    value={cleanupConfirmName}
                    onChange={(event) => setCleanupConfirmName(event.target.value)}
                    placeholder={tenant.name}
                    autoComplete="off"
                  />
                </label>

                <div className="table-actions table-actions-start">
                  <button
                    type="submit"
                    className="button-danger"
                    disabled={cleanupSelected.size === 0 || !cleanupNameMatches || cleanupBusy || cleanupLoading}
                  >
                    {cleanupBusy ? "Wird gelöscht…" : "Ausgewählte Daten löschen"}
                  </button>
                </div>
              </form>
            )
          },
          {
            id: "speicher",
            label: "Speicher",
            content: (
              <div className="grid">
                {storageUsage ? (
                  <>
                    {/* Shared with the tenant-facing Speicher page (audit fix,
                        2026-09-17) - this used to hand-roll its own bar/table with a
                        divergent quota denominator and no free-space segment. */}
                    <StorageBreakdown {...storageUsage} />
                    <div className="muted">Gesamt belegt: {formatFileSize(storageUsage.total_bytes)}</div>
                  </>
                ) : (
                  <div className="muted">{storageLoading ? "Wird geladen…" : "Keine Daten verfügbar."}</div>
                )}

                <form className="grid" onSubmit={submitQuota}>
                  <label className="field-stack">
                    <span className="field-label">Speicherkontingent (MB, leer = kein Limit)</span>
                    <input
                      type="number"
                      min={1}
                      value={quotaMbInput}
                      onChange={(event) => setQuotaMbInput(event.target.value)}
                      placeholder="z.B. 5120"
                    />
                  </label>
                  <div className="table-actions table-actions-start">
                    <button type="submit" className="button-secondary" disabled={quotaBusy}>
                      {quotaBusy ? "Wird gespeichert…" : "Kontingent speichern"}
                    </button>
                  </div>
                </form>
              </div>
            )
          }
        ]}
      />

      <MfaAdminModal
        open={!!mfaModalUser}
        onClose={() => setMfaModalUser(null)}
        title={mfaModalUser ? `MFA von ${mfaModalUser.display_name}` : "MFA"}
        loadPath={mfaModalUser ? `/api/admin/users/${mfaModalUser.user_id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/admin/users/${mfaModalUser.user_id}/mfa/factors` : null}
      />
    </Modal>
  );
}
