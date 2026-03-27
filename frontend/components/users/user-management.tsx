"use client";

import { FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { SessionInfo, TenantSummary, UserSummary } from "@/types/api";

type Props = {
  initialUsers: UserSummary[];
  manageableTenants: TenantSummary[];
  session: SessionInfo;
};

type MembershipEntry = {
  tenant_id: number;
  role_code: string;
};

type UserFormState = {
  id?: number;
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  password: string;
  preferred_language: string;
  is_active: boolean;
  is_superadmin: boolean;
  memberships: MembershipEntry[];
  selectedTenantId: string;
  selectedRoleCode: string;
};

function buildInitialMemberships(user: UserSummary, manageableTenants: TenantSummary[], canSuperadmin: boolean) {
  if (canSuperadmin) {
    return user.memberships.map((membership) => ({
      tenant_id: membership.tenant_id,
      role_code: membership.role_code
    }));
  }
  const manageableIds = new Set(manageableTenants.map((tenant) => tenant.id));
  return user.memberships
    .filter((membership) => manageableIds.has(membership.tenant_id))
    .map((membership) => ({
      tenant_id: membership.tenant_id,
      role_code: membership.role_code
    }));
}

function emptyUserForm(manageableTenants: TenantSummary[]): UserFormState {
  return {
    first_name: "",
    last_name: "",
    display_name: "",
    email: "",
    password: "",
    preferred_language: "de",
    is_active: true,
    is_superadmin: false,
    memberships: manageableTenants[0] ? [{ tenant_id: manageableTenants[0].id, role_code: "reader" }] : [],
    selectedTenantId: manageableTenants[0] ? String(manageableTenants[0].id) : "",
    selectedRoleCode: "reader"
  };
}

export function UserManagement({ initialUsers, manageableTenants, session }: Props) {
  const [users, setUsers] = useState(initialUsers);
  const [status, setStatus] = useState("Bereit");
  const [statusTone, setStatusTone] = useState<"neutral" | "success" | "error">("neutral");
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<UserFormState>(() => emptyUserForm(manageableTenants));

  const canSuperadmin = !!session.user?.is_superadmin;
  const tenantNameById = useMemo(
    () => new Map(manageableTenants.map((tenant) => [tenant.id, tenant.name])),
    [manageableTenants]
  );

  function openNewUser() {
    setUserForm(emptyUserForm(manageableTenants));
    setUserModalOpen(true);
  }

  function openEditUser(user: UserSummary) {
    const memberships = buildInitialMemberships(user, manageableTenants, canSuperadmin);
    setUserForm({
      id: user.id,
      first_name: user.first_name,
      last_name: user.last_name,
      display_name: user.display_name,
      email: user.email,
      password: "",
      preferred_language: user.preferred_language,
      is_active: user.is_active,
      is_superadmin: user.is_superadmin,
      memberships,
      selectedTenantId: manageableTenants[0] ? String(manageableTenants[0].id) : "",
      selectedRoleCode: "reader"
    });
    setUserModalOpen(true);
  }

  function upsertMembership() {
    if (!userForm.selectedTenantId) {
      return;
    }
    const tenantId = Number(userForm.selectedTenantId);
    setUserForm((current) => {
      const nextMemberships = current.memberships.some((membership) => membership.tenant_id === tenantId)
        ? current.memberships.map((membership) =>
            membership.tenant_id === tenantId ? { tenant_id: tenantId, role_code: current.selectedRoleCode } : membership
          )
        : [...current.memberships, { tenant_id: tenantId, role_code: current.selectedRoleCode }];
      return {
        ...current,
        memberships: nextMemberships.sort((left, right) => left.tenant_id - right.tenant_id)
      };
    });
  }

  function removeMembership(tenantId: number) {
    setUserForm((current) => ({
      ...current,
      memberships: current.memberships.filter((membership) => membership.tenant_id !== tenantId)
    }));
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(userForm.id ? "Benutzer wird gespeichert..." : "Benutzer wird erstellt...");
    setStatusTone("neutral");

    try {
      const payload = {
        first_name: userForm.first_name,
        last_name: userForm.last_name,
        display_name: userForm.display_name,
        email: userForm.email,
        preferred_language: userForm.preferred_language,
        is_active: userForm.is_active,
        is_superadmin: canSuperadmin ? userForm.is_superadmin : false,
        memberships: userForm.memberships.map((membership) => ({
          tenant_id: membership.tenant_id,
          role_code: membership.role_code,
          is_active: true
        })),
        ...(userForm.password ? { password: userForm.password } : {})
      };

      const updated = userForm.id
        ? await browserApiFetch<UserSummary>(`/api/users/${userForm.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload)
          })
        : await browserApiFetch<UserSummary>("/api/users", {
            method: "POST",
            body: JSON.stringify(payload)
          });

      setUsers((current) =>
        userForm.id ? current.map((user) => (user.id === updated.id ? updated : user)) : [updated, ...current]
      );
      setUserModalOpen(false);
      setStatus(userForm.id ? "Benutzer gespeichert" : "Benutzer erstellt");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Benutzer konnte nicht gespeichert werden");
      setStatusTone("error");
    }
  }

  async function deleteUser(userId: number) {
    setStatus("Benutzer wird gelöscht...");
    setStatusTone("neutral");
    try {
      await browserApiFetch(`/api/users/${userId}`, { method: "DELETE" });
      setUsers((current) => current.filter((user) => user.id !== userId));
      setStatus("Benutzer gelöscht");
      setStatusTone("success");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Benutzer konnte nicht gelöscht werden");
      setStatusTone("error");
    }
  }

  return (
    <div className="grid">
      <StatusBanner tone={statusTone} message={status} />

      <DataToolbar
        title="Benutzer"
        description="Systemweite Konten mit genau den Mandantenrollen, die du verwalten darfst."
        actions={
          <button type="button" className="button-inline" onClick={openNewUser}>
            Neuer Benutzer
          </button>
        }
      />

      <DataTable columns={["Anzeigename", "Name", "E-Mail", "Rollen", "Aktionen"]}>
        {users.map((user) => (
          <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
            <td>
              <strong>{user.display_name}</strong>
              {user.is_superadmin ? <div className="muted">Superadmin</div> : null}
            </td>
            <td>{user.first_name} {user.last_name}</td>
            <td>{user.email}</td>
            <td>
              <div className="stack-tight">
                {(canSuperadmin
                  ? user.memberships
                  : user.memberships.filter((membership) => tenantNameById.has(membership.tenant_id))
                ).map((membership) => (
                  <span key={`${user.id}-${membership.tenant_id}`} className="pill">
                    {membership.tenant_name}: {membership.role_code}
                  </span>
                ))}
              </div>
            </td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline button-danger"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteUser(user.id);
                  }}
                >
                  Delete
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={userModalOpen}
        onClose={() => setUserModalOpen(false)}
        title={userForm.id ? "Benutzer bearbeiten" : "Benutzer erstellen"}
        description="Kontodaten pflegen und Mandantenrollen gezielt einzeln zuweisen."
        size="wide"
      >
        <form className="grid" onSubmit={submitUser}>
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">Vorname</span>
              <input value={userForm.first_name} onChange={(event) => setUserForm((current) => ({ ...current, first_name: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Nachname</span>
              <input value={userForm.last_name} onChange={(event) => setUserForm((current) => ({ ...current, last_name: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">Anzeigename</span>
              <input value={userForm.display_name} onChange={(event) => setUserForm((current) => ({ ...current, display_name: event.target.value }))} required />
            </label>
          </div>

          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">E-Mail</span>
              <input value={userForm.email} onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">{userForm.id ? "Neues Passwort" : "Passwort"}</span>
              <input type="password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} required={!userForm.id} />
            </label>
            <label className="field-stack">
              <span className="field-label">Sprache</span>
              <select value={userForm.preferred_language} onChange={(event) => setUserForm((current) => ({ ...current, preferred_language: event.target.value }))}>
                <option value="de">Deutsch</option>
                <option value="en">English</option>
                <option value="fr">Français</option>
                <option value="it">Italiano</option>
              </select>
            </label>
            <label className="checkbox-line">
              <input type="checkbox" checked={userForm.is_active} onChange={(event) => setUserForm((current) => ({ ...current, is_active: event.target.checked }))} />
              Aktiv
            </label>
          </div>

          {canSuperadmin ? (
            <label className="checkbox-line">
              <input type="checkbox" checked={userForm.is_superadmin} onChange={(event) => setUserForm((current) => ({ ...current, is_superadmin: event.target.checked }))} />
              Superadmin
            </label>
          ) : null}

          <div className="grid">
            <div className="field-label">Mandantenrollen</div>
            <div className="role-picker">
              <label className="field-stack">
                <span className="field-label">Mandant</span>
                <select value={userForm.selectedTenantId} onChange={(event) => setUserForm((current) => ({ ...current, selectedTenantId: event.target.value }))}>
                  {manageableTenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-stack">
                <span className="field-label">Rolle</span>
                <select value={userForm.selectedRoleCode} onChange={(event) => setUserForm((current) => ({ ...current, selectedRoleCode: event.target.value }))}>
                  <option value="reader">Reader</option>
                  <option value="writer">Writer</option>
                  <option value="admin">Admin</option>
                </select>
              </label>
              <div className="role-picker-action">
                <button type="button" className="button-inline" onClick={upsertMembership} disabled={!userForm.selectedTenantId}>
                  Rolle zuweisen
                </button>
              </div>
            </div>

            <div className="selection-list">
              {userForm.memberships.length === 0 ? (
                <div className="selection-card muted">Noch keine verwaltbaren Mandantenrollen zugewiesen.</div>
              ) : (
                userForm.memberships.map((membership) => (
                  <div key={membership.tenant_id} className="selection-card membership-row">
                    <div>
                      <strong>{tenantNameById.get(membership.tenant_id) ?? `Tenant #${membership.tenant_id}`}</strong>
                      <div className="muted">{membership.role_code}</div>
                    </div>
                    <button type="button" className="button-inline button-danger" onClick={() => removeMembership(membership.tenant_id)}>
                      Entfernen
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

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
