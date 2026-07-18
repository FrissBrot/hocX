"use client";

import { FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { AdminTenantSummary, UserSummary } from "@/types/api";

type Props = {
  initialUsers: UserSummary[];
  allTenants: AdminTenantSummary[];
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
  login_enabled: boolean;
  is_participant_account: boolean;
  memberships: MembershipEntry[];
  selectedTenantId: string;
  selectedRoleCode: string;
};

function emptyUserForm(allTenants: AdminTenantSummary[]): UserFormState {
  return {
    first_name: "",
    last_name: "",
    display_name: "",
    email: "",
    password: "",
    preferred_language: "de",
    is_active: true,
    login_enabled: true,
    is_participant_account: false,
    memberships: [],
    selectedTenantId: allTenants[0] ? String(allTenants[0].id) : "",
    selectedRoleCode: "reader"
  };
}

export function AdminUserManagement({ initialUsers, allTenants }: Props) {
  const showToast = useToast();
  const [users, setUsers] = useState(initialUsers);
  const [search, setSearch] = useState("");
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<UserFormState>(() => emptyUserForm(allTenants));
  const [formError, setFormError] = useState<string | null>(null);
  const [mergeModalOpen, setMergeModalOpen] = useState(false);
  const [mergeSourceUserId, setMergeSourceUserId] = useState<number | null>(null);
  const [mergeTargetUserId, setMergeTargetUserId] = useState("");

  const tenantNameById = useMemo(() => new Map(allTenants.map((tenant) => [tenant.id, tenant.name])), [allTenants]);

  // Nur Benutzer mit freigeschaltetem Login und echter (nicht automatisch generierter
  // Teilnehmer-Platzhalter-) E-Mail sind hier relevant - Schattenaccounts ohne Login
  // sind nur internes Implementierungsdetail der Teilnehmerverwaltung.
  const eligibleUsers = useMemo(
    () => users.filter((user) => user.login_enabled && !user.email.endsWith("@participants.hocx.local")),
    [users]
  );

  const visibleUsers = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return eligibleUsers;
    return eligibleUsers.filter((user) => {
      const membershipText = user.memberships.map((m) => `${m.tenant_name} ${m.role_code}`).join(" ");
      const haystack = `${user.display_name} ${user.first_name} ${user.last_name} ${user.email} ${membershipText}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [eligibleUsers, search]);

  function openNewUser() {
    setUserForm(emptyUserForm(allTenants));
    setFormError(null);
    setUserModalOpen(true);
  }

  function openEditUser(user: UserSummary) {
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
      memberships: user.memberships.map((membership) => ({ tenant_id: membership.tenant_id, role_code: membership.role_code })),
      selectedTenantId: allTenants[0] ? String(allTenants[0].id) : "",
      selectedRoleCode: "reader"
    });
    setFormError(null);
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
    setFormError(null);

    try {
      const payload = {
        first_name: userForm.first_name,
        last_name: userForm.last_name,
        display_name: userForm.display_name,
        email: userForm.email,
        preferred_language: userForm.preferred_language,
        is_active: userForm.is_active,
        login_enabled: userForm.login_enabled,
        memberships: userForm.memberships.map((membership) => ({
          tenant_id: membership.tenant_id,
          role_code: membership.role_code,
          is_active: true
        })),
        ...(userForm.password ? { password: userForm.password } : {})
      };

      const saved = userForm.id
        ? await browserApiFetch<UserSummary>(`/api/admin/users/${userForm.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload)
          })
        : await browserApiFetch<UserSummary>("/api/admin/users", {
            method: "POST",
            body: JSON.stringify(payload)
          });

      setUsers((current) => (userForm.id ? current.map((user) => (user.id === saved.id ? saved : user)) : [saved, ...current]));
      setUserModalOpen(false);
      showToast(userForm.id ? "Benutzer gespeichert" : "Benutzer erstellt", "success");
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Benutzer konnte nicht gespeichert werden";
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  function openMerge(user: UserSummary) {
    setMergeSourceUserId(user.id);
    const fallbackTarget = eligibleUsers.find((candidate) => candidate.id !== user.id);
    setMergeTargetUserId(fallbackTarget ? String(fallbackTarget.id) : "");
    setMergeModalOpen(true);
  }

  async function mergeUsers() {
    if (!mergeSourceUserId || !mergeTargetUserId) return;
    try {
      const merged = await browserApiFetch<UserSummary>("/api/admin/users/merge", {
        method: "POST",
        body: JSON.stringify({
          source_user_id: mergeSourceUserId,
          target_user_id: Number(mergeTargetUserId),
        }),
      });
      setUsers((current) =>
        current.filter((user) => user.id !== mergeSourceUserId).map((user) => (user.id === merged.id ? merged : user))
      );
      setMergeModalOpen(false);
      showToast("Benutzer zusammengeführt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzer konnten nicht zusammengeführt werden", "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Benutzer"
        description="Alle zentralen Benutzer über alle Mandanten hinweg."
        actions={
          <button type="button" className="button-inline" onClick={openNewUser}>
            Neuer Benutzer
          </button>
        }
      />

      <article className="card">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Benutzer durchsuchen" />
        </label>
      </article>

      <DataTable columns={["Anzeigename", "E-Mail", "Mandantenrollen", "Login", "Aktionen"]} emptyMessage="Keine Benutzer gefunden.">
        {visibleUsers.map((user) => (
          <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
            <td>
              <strong>{user.display_name}</strong>
              {user.is_participant_account ? <div className="muted">Teilnehmer-Konto</div> : null}
            </td>
            <td>{user.email}</td>
            <td>
              <div className="stack-tight">
                {user.memberships.map((membership) => (
                  <span key={`${user.id}-${membership.tenant_id}`} className="pill">
                    {membership.tenant_name}: {membership.role_code}
                  </span>
                ))}
              </div>
            </td>
            <td>{user.login_enabled ? "Aktiv" : "Deaktiviert"}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-inline"
                  onClick={(event) => {
                    event.stopPropagation();
                    openMerge(user);
                  }}
                >
                  Merge
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
        description="Kontodaten pflegen und Mandantenrollen über beliebige Mandanten hinweg zuweisen."
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
              <input type="password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} required={!userForm.id} minLength={8} />
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
                Dieses Konto wurde automatisch aus einem Teilnehmer erstellt. Für den ersten Login bitte Login aktivieren
                und ein neues Passwort setzen.
              </div>
            ) : null}
          </div>

          <div className="grid">
            <div className="field-label">Mandantenrollen</div>
            <div className="role-picker">
              <label className="field-stack">
                <span className="field-label">Mandant</span>
                <select value={userForm.selectedTenantId} onChange={(event) => setUserForm((current) => ({ ...current, selectedTenantId: event.target.value }))}>
                  {allTenants.map((tenant) => (
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
                  <option value="kassier">Kassier</option>
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
                <div className="selection-card muted">Noch keine Mandantenrollen zugewiesen.</div>
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

          {formError && <div className="form-error-banner">{formError}</div>}

          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Speichern
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={mergeModalOpen}
        onClose={() => setMergeModalOpen(false)}
        title="Benutzer zusammenführen"
        description="Der Quellbenutzer wird in den Zielbenutzer gemergt (inkl. Mandantenrollen und Teilnehmer-Links) und danach gelöscht."
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Quellbenutzer</span>
            <input value={users.find((user) => user.id === mergeSourceUserId)?.display_name ?? ""} readOnly />
          </label>
          <label className="field-stack">
            <span className="field-label">Zielbenutzer</span>
            <select value={mergeTargetUserId} onChange={(event) => setMergeTargetUserId(event.target.value)}>
              {eligibleUsers
                .filter((user) => user.id !== mergeSourceUserId)
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name} ({user.email})
                  </option>
                ))}
            </select>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-inline" onClick={() => void mergeUsers()} disabled={!mergeTargetUserId}>
              Jetzt mergen
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
