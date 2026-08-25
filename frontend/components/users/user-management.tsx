"use client";

import { FormEvent, useMemo, useState } from "react";

import { ROLE_OPTIONS } from "@/components/admin/admin-tenant-settings-modal";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { TenantSummary, UserSummary } from "@/types/api";
import {
  addOrUpsertMembership,
  buildTenantNameMap,
  emptyUserForm,
  removeMembershipEntry,
  userFormToPayload,
  UserFormState
} from "@/components/users/user-form-shared";

type Props = {
  initialUsers: UserSummary[];
  manageableTenants: TenantSummary[];
};

function buildInitialMemberships(user: UserSummary, manageableTenants: TenantSummary[]) {
  const manageableIds = new Set(manageableTenants.map((tenant) => tenant.id));
  return user.memberships
    .filter((membership) => manageableIds.has(membership.tenant_id))
    .map((membership) => ({
      tenant_id: membership.tenant_id,
      role_code: membership.role_code
    }));
}

export function UserManagement({ initialUsers, manageableTenants }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [users, setUsers] = useState(initialUsers);
  const [userTab, setUserTab] = useState<"active" | "nologin">("active");
  const [search, setSearch] = useState("");
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<UserFormState>(() =>
    emptyUserForm(manageableTenants, { prefillMembership: true })
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [loginModalUser, setLoginModalUser] = useState<UserSummary | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [mfaModalUser, setMfaModalUser] = useState<UserSummary | null>(null);

  const tenantNameById = useMemo(() => buildTenantNameMap(manageableTenants), [manageableTenants]);
  const activeUsers = useMemo(() => users.filter((user) => user.login_enabled), [users]);
  const usersWithoutLogin = useMemo(() => users.filter((user) => !user.login_enabled), [users]);
  const tabUsers = userTab === "active" ? activeUsers : usersWithoutLogin;
  const visibleUsers = useMemo(() => {
    const query = search.trim().toLowerCase();
    return tabUsers.filter((user) => {
      if (!query) {
        return true;
      }
      const membershipText = user.memberships.map((membership) => `${membership.tenant_name} ${membership.role_code}`).join(" ");
      const haystack = `${user.display_name} ${user.first_name} ${user.last_name} ${user.email} ${membershipText}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [search, tabUsers]);

  function openNewUser() {
    setUserForm(emptyUserForm(manageableTenants));
    setFormError(null);
    setUserModalOpen(true);
  }

  function openEditUser(user: UserSummary) {
    const memberships = buildInitialMemberships(user, manageableTenants);
    setUserForm({
      id: user.id,
      first_name: user.first_name,
      last_name: user.last_name,
      display_name: user.display_name,
      email: user.email,
      password: "",
      preferred_language: user.preferred_language,
      is_active: user.is_active,
      login_enabled: user.login_enabled,
      is_participant_account: user.is_participant_account,
      memberships,
      pickerTenantId: manageableTenants[0] ? String(manageableTenants[0].id) : "",
      pickerRoleCode: "reader"
    });
    setFormError(null);
    setUserModalOpen(true);
  }

  function openEnableLogin(user: UserSummary) {
    setLoginModalUser(user);
    setLoginEmail(user.email ?? "");
    setLoginPassword("");
    setLoginError(null);
    setLoginModalOpen(true);
  }

  function openMfa(user: UserSummary) {
    setMfaModalUser(user);
  }

  async function submitEnableLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!loginModalUser) {
      return;
    }
    setLoginError(null);
    try {
      const updated = await browserApiFetch<UserSummary>(`/api/users/${loginModalUser.id}`, {
        method: "PATCH",
        body: JSON.stringify({ email: loginEmail, password: loginPassword, login_enabled: true })
      });
      // Enabling login can merge this participant's shadow account into an already-existing
      // user with the same real email (see backend _link_or_promote_participant_login) - the
      // id we PATCHed might no longer exist, and `updated` might collide with an entry already
      // in the list, so replace both possibilities rather than just swapping the old id in place.
      setUsers((current) => {
        const withoutOldAndTarget = current.filter((user) => user.id !== loginModalUser.id && user.id !== updated.id);
        return [updated, ...withoutOldAndTarget];
      });
      setLoginModalOpen(false);
      showToast("Login aktiviert", "success");
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Login konnte nicht aktiviert werden");
    }
  }

  function upsertMembership() {
    if (!userForm.pickerTenantId) {
      return;
    }
    const tenantId = Number(userForm.pickerTenantId);
    setUserForm((current) => ({
      ...current,
      memberships: addOrUpsertMembership(current.memberships, tenantId, current.pickerRoleCode, "upsert")
    }));
  }

  function removeMembership(tenantId: number) {
    setUserForm((current) => ({
      ...current,
      memberships: removeMembershipEntry(current.memberships, tenantId)
    }));
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    try {
      const payload = userFormToPayload(userForm);

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
      showToast(userForm.id ? "Benutzer gespeichert" : "Benutzer erstellt", "success");
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Benutzer konnte nicht gespeichert werden";
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  async function deleteUser(userId: number, displayName: string) {
    const ok = await confirm({
      message: `Benutzer "${displayName}" endgültig löschen? Der Zugriff auf alle Mandanten geht sofort verloren.`,
      tone: "danger",
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/users/${userId}`, { method: "DELETE" });
      setUsers((current) => current.filter((user) => user.id !== userId));
      showToast("Benutzer gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzer konnte nicht gelöscht werden", "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Benutzer</h1>
          <p className="muted">Systemweite Konten mit genau den Mandantenrollen, die du verwalten darfst.</p>
        </div>
        <button type="button" className="button-inline" onClick={openNewUser}>
          Neuer Benutzer
        </button>
      </div>

      <div className="list-filter-row">
        <FilterTabs
          options={[
            { value: "active", label: "Aktive Benutzer", count: activeUsers.length },
            { value: "nologin", label: "Teilnehmer", count: usersWithoutLogin.length },
          ]}
          value={userTab}
          onChange={setUserTab}
        />
        <div className="list-filter-search">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder={userTab === "active" ? "Benutzer durchsuchen" : "Teilnehmer durchsuchen"}
          />
        </div>
      </div>

      <div className="status-row">
        <span className="pill">{visibleUsers.length} sichtbar</span>
        <span className="pill">{tabUsers.length} im Tab</span>
        <span className="pill">{users.length} gesamt</span>
      </div>

      {userTab === "active" ? (
        <DataTable className="data-table-lg" columns={["Anzeigename", "Name", "E-Mail", "Rollen", "Aktionen"]}>
          {visibleUsers.map((user) => (
            <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
              <td>
                <strong>{user.display_name}</strong>
              </td>
              <td>{user.first_name} {user.last_name}</td>
              <td>{user.email}</td>
              <td>
                <div className="stack-tight">
                  {user.memberships
                    .filter((membership) => tenantNameById.has(membership.tenant_id))
                    .map((membership) => (
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
                    className="button-inline button-ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      openMfa(user);
                    }}
                  >
                    MFA
                  </button>
                  <button
                    type="button"
                    className="button-inline button-danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteUser(user.id, user.display_name);
                    }}
                  >
                    Löschen
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      ) : (
        <DataTable className="data-table-lg" columns={["Name", "E-Mail (Teilnehmer)", "Rollen", "Aktionen"]}>
          {visibleUsers.map((user) => (
            <tr key={user.id}>
              <td>
                <strong>{user.display_name}</strong>
              </td>
              <td>{user.email ?? <span className="muted">–</span>}</td>
              <td>
                <div className="stack-tight">
                  {user.memberships
                    .filter((membership) => tenantNameById.has(membership.tenant_id))
                    .map((membership) => (
                      <span key={`${user.id}-${membership.tenant_id}`} className="pill">
                        {membership.tenant_name}: {membership.role_code}
                      </span>
                    ))}
                </div>
              </td>
              <td>
                <div className="table-actions table-actions-start">
                  <button type="button" className="button-inline button-ghost" onClick={() => openMfa(user)}>
                    MFA
                  </button>
                  <button type="button" className="button-inline" onClick={() => openEnableLogin(user)}>
                    Login aktivieren
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      )}

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
              <input type="password" autoComplete="new-password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} required={!userForm.id} />
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

          <div className="two-col">
            <label className="checkbox-line">
              <input type="checkbox" checked={userForm.login_enabled} onChange={(event) => setUserForm((current) => ({ ...current, login_enabled: event.target.checked }))} />
              Login aktivieren
            </label>
            {userForm.is_participant_account ? (
              <div className="info-note">
                Dieses Konto wurde automatisch aus einem Teilnehmer erstellt. Fuer den ersten Login bitte Login aktivieren
                und ein neues Passwort setzen.
              </div>
            ) : null}
          </div>

          <div className="grid">
            <div className="field-label">Mandantenrollen</div>
            <div className="role-picker">
              <label className="field-stack">
                <span className="field-label">Mandant</span>
                <SearchableSelect
                  options={manageableTenants}
                  getId={(tenant) => String(tenant.id)}
                  getLabel={(tenant) => tenant.name}
                  value={userForm.pickerTenantId || null}
                  onChange={(tenant) => setUserForm((current) => ({ ...current, pickerTenantId: tenant ? String(tenant.id) : "" }))}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Rolle</span>
                <select value={userForm.pickerRoleCode} onChange={(event) => setUserForm((current) => ({ ...current, pickerRoleCode: event.target.value }))}>
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="role-picker-action">
                <button type="button" className="button-inline" onClick={upsertMembership} disabled={!userForm.pickerTenantId}>
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

          {formError && (
            <div className="form-error-banner">{formError}</div>
          )}

          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Speichern
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={loginModalOpen}
        onClose={() => setLoginModalOpen(false)}
        title={`Login aktivieren${loginModalUser ? ` für ${loginModalUser.display_name}` : ""}`}
        description="Vergib E-Mail und Passwort, damit sich dieser Teilnehmer einloggen kann. Er bleibt weiterhin als Teilnehmer verknüpft."
      >
        <form className="grid" onSubmit={submitEnableLogin}>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input type="email" value={loginEmail} onChange={(event) => setLoginEmail(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">Passwort</span>
            <input
              type="password"
              autoComplete="new-password"
              value={loginPassword}
              onChange={(event) => setLoginPassword(event.target.value)}
              required
              minLength={8}
            />
          </label>

          {loginError && <div className="form-error-banner">{loginError}</div>}

          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Login aktivieren
            </button>
          </div>
        </form>
      </Modal>

      <MfaAdminModal
        open={!!mfaModalUser}
        onClose={() => setMfaModalUser(null)}
        title={mfaModalUser ? `MFA von ${mfaModalUser.display_name}` : "MFA"}
        loadPath={mfaModalUser ? `/api/users/${mfaModalUser.id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/users/${mfaModalUser.id}/mfa/factors` : null}
      />
    </div>
  );
}
