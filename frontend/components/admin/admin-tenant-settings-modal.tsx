"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { AdminTenantSummary, AdminTenantUser, AdminUserPage, UserSummary } from "@/types/api";

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

export function AdminTenantSettingsModal({ open, onClose, tenant, onSaved }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [tenantForm, setTenantForm] = useState<TenantFormState>(emptyTenantForm);

  const [tenantUsers, setTenantUsers] = useState<AdminTenantUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [allUsers, setAllUsers] = useState<UserSummary[]>([]);
  const [addUserId, setAddUserId] = useState("");
  const [addUserRole, setAddUserRole] = useState("reader");
  const [addUserBusy, setAddUserBusy] = useState(false);

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
    // No limit param -> full (unpaginated) list, needed here for the "add user" picker.
    browserApiFetch<AdminUserPage>("/api/admin/users")
      .then((result) => setAllUsers(result.items))
      .catch(() => setAllUsers([]));
  }, [open, tenant]);

  async function loadTenantUsers(tenantId: number) {
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

  async function changeUserRole(userId: number, roleCode: string) {
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

  async function removeUser(userId: number, displayName: string) {
    if (!tenant) return;
    if (
      !(await confirm({
        message: `Zugriff von "${displayName}" auf diesen Mandanten entfernen? Der Benutzer-Account selbst bleibt bestehen.`,
        tone: "danger",
        confirmLabel: "Entfernen"
      }))
    )
      return;
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}/users/${userId}`, { method: "DELETE" });
      setTenantUsers((current) => current.filter((u) => u.user_id !== userId));
      showToast("Zugriff entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Zugriff konnte nicht entfernt werden", "error");
    }
  }

  async function addUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant || !addUserId) return;
    setAddUserBusy(true);
    try {
      const granted = await browserApiFetch<AdminTenantUser>(`/api/admin/tenants/${tenant.id}/users/${addUserId}`, {
        method: "PUT",
        body: JSON.stringify({ role_code: addUserRole })
      });
      setTenantUsers((current) => [...current.filter((u) => u.user_id !== granted.user_id), granted].sort((a, b) => a.display_name.localeCompare(b.display_name)));
      setAddUserId("");
      showToast("Benutzer hinzugefügt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzer konnte nicht hinzugefügt werden", "error");
    } finally {
      setAddUserBusy(false);
    }
  }

  const availableToAdd = allUsers.filter((u) => !tenantUsers.some((tu) => tu.user_id === u.id));

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
                  <button type="submit" className="button-inline">
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
                            <button type="button" className="button-inline button-ghost" onClick={() => removeUser(u.user_id, u.display_name)}>
                              Entfernen
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!usersLoading && tenantUsers.length === 0 && <div className="table-empty muted">Keine Benutzer mit Zugriff auf diesen Mandanten.</div>}
                </div>

                <div className="card">
                  <div className="eyebrow">Benutzer hinzufügen</div>
                  <form className="role-picker" onSubmit={addUser}>
                    <label className="field-stack">
                      <span className="field-label">Bestehender Benutzer</span>
                      <select value={addUserId} onChange={(event) => setAddUserId(event.target.value)} required>
                        <option value="" disabled>
                          Auswählen…
                        </option>
                        {availableToAdd.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.display_name} ({u.email})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Rolle</span>
                      <select value={addUserRole} onChange={(event) => setAddUserRole(event.target.value)}>
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r.code} value={r.code}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="role-picker-action">
                      <button type="submit" className="button-inline" disabled={!addUserId || addUserBusy}>
                        Hinzufügen
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )
          }
        ]}
      />
    </Modal>
  );
}
