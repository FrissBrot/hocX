"use client";

import { FormEvent, useMemo, useState } from "react";

import { ROLE_OPTIONS } from "@/components/admin/admin-tenant-settings-modal";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { formatRoleLabel } from "@/components/ui/app-shell-nav";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { UserSummary } from "@/types/api";
import { emptyUserForm, userFormToPayload, UserFormState } from "@/components/users/user-form-shared";

type Props = {
  initialUsers: UserSummary[];
};

const ROLE_DESCRIPTIONS: { code: string; description: string }[] = [
  { code: "admin", description: "Voller Zugriff innerhalb des Mandanten, inklusive Struktur (Vorlagen, Zyklen, Einstellungen) und Benutzerverwaltung." },
  { code: "writer", description: "Arbeitet im Protokoll-Bereich mit und pflegt operative Daten, ändert aber weder Struktur noch Finanzen." },
  { code: "kassier", description: "Wie Leser, zusätzlich voller Schreibzugriff auf Finanzen und Bussen." },
  { code: "reader", description: "Nur Lesezugriff, kann PDF-Exporte auslösen und sieht nur die eigenen Bussen." },
];

function roleLabel(roleCode: string) {
  return ROLE_OPTIONS.find((role) => role.code === roleCode)?.label ?? roleCode;
}

export function UserManagement({ initialUsers }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [users, setUsers] = useState(initialUsers);
  const [userTab, setUserTab] = useState<"active" | "nologin">("active");
  const [search, setSearch] = useState("");
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<UserFormState>(() => emptyUserForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [loginModalUser, setLoginModalUser] = useState<UserSummary | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [mfaModalUser, setMfaModalUser] = useState<UserSummary | null>(null);
  const [rolesModalOpen, setRolesModalOpen] = useState(false);

  const activeUsers = useMemo(() => users.filter((user) => user.login_enabled), [users]);
  const usersWithoutLogin = useMemo(() => users.filter((user) => !user.login_enabled), [users]);
  const tabUsers = userTab === "active" ? activeUsers : usersWithoutLogin;
  const visibleUsers = useMemo(() => {
    const query = search.trim().toLowerCase();
    return tabUsers.filter((user) => {
      if (!query) {
        return true;
      }
      const haystack = `${user.display_name} ${user.first_name} ${user.last_name} ${user.email} ${roleLabel(user.role_code)}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [search, tabUsers]);

  function openNewUser() {
    setUserForm(emptyUserForm());
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
      tenant_id: user.tenant_id,
      role_code: user.role_code
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

  async function deleteUser(userId: string, displayName: string) {
    const ok = await confirm({
      message: `Benutzer "${displayName}" endgültig löschen? Das Konto und der Zugriff gehen sofort verloren.`,
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

  // Nur das eigene Konto und keine Teilnehmer ohne Login: die Liste hätte nichts zu zeigen.
  const hasOnlyOwnAccess = activeUsers.length <= 1 && usersWithoutLogin.length === 0;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Benutzer</h1>
          <p className="muted">{hasOnlyOwnAccess ? "Zugänge und Rollen dieses Mandanten." : "Die Konten dieses Mandanten und ihre Rollen."}</p>
        </div>
        {hasOnlyOwnAccess ? null : (
          <button type="button" className="button-secondary" onClick={openNewUser}>
            Neuer Benutzer
          </button>
        )}
      </div>

      {hasOnlyOwnAccess ? (
        <EmptyState
          title="Nur dein eigener Zugang"
          description="Lade weitere Personen ein und weise ihnen eine Rolle zu: Admin, Schreiber, Kassier oder Leser."
          actions={
            <>
              <button type="button" className="button-primary" onClick={openNewUser}>
                + Benutzer einladen
              </button>
              <button type="button" className="button-secondary" onClick={() => setRolesModalOpen(true)}>
                Rollen erklären
              </button>
            </>
          }
        />
      ) : (
      <>
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
        <DataTable className="data-table-lg" columns={["Anzeigename", "Name", "E-Mail", "Rolle", "Aktionen"]}>
          {visibleUsers.map((user) => (
            <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
              <td>
                <strong>{user.display_name}</strong>
              </td>
              <td>{user.first_name} {user.last_name}</td>
              <td>{user.email}</td>
              <td>
                <span className="pill">{roleLabel(user.role_code)}</span>
              </td>
              <td>
                <div className="table-actions table-actions-start">
                  <button
                    type="button"
                    className="button-secondary button-ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      openMfa(user);
                    }}
                  >
                    MFA
                  </button>
                  <button
                    type="button"
                    className="button-secondary button-danger"
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
        <DataTable className="data-table-lg" columns={["Name", "E-Mail (Teilnehmer)", "Rolle", "Aktionen"]}>
          {visibleUsers.map((user) => (
            <tr key={user.id}>
              <td>
                <strong>{user.display_name}</strong>
              </td>
              <td>{user.email ?? <span className="muted">–</span>}</td>
              <td>
                <span className="pill">{roleLabel(user.role_code)}</span>
              </td>
              <td>
                <div className="table-actions table-actions-start">
                  <button type="button" className="button-secondary button-ghost" onClick={() => openMfa(user)}>
                    MFA
                  </button>
                  <button type="button" className="button-secondary" onClick={() => openEnableLogin(user)}>
                    Login aktivieren
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      )}
      </>
      )}

      <Modal open={rolesModalOpen} onClose={() => setRolesModalOpen(false)} title="Rollen erklären" description="Jedes Konto hat pro Mandant genau eine Rolle.">
        <div className="grid">
          {ROLE_DESCRIPTIONS.map((role) => (
            <div key={role.code} className="field-stack">
              <span className="field-label">{formatRoleLabel(role.code)}</span>
              <span className="muted">{role.description}</span>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => setRolesModalOpen(false)}>Schliessen</button>
        </div>
      </Modal>

      <Modal
        open={userModalOpen}
        onClose={() => setUserModalOpen(false)}
        title={userForm.id ? "Benutzer bearbeiten" : "Benutzer erstellen"}
        description="Kontodaten und Rolle pflegen."
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

          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">E-Mail</span>
              <input value={userForm.email} onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))} required />
            </label>
            <label className="field-stack">
              <span className="field-label">{userForm.id ? "Neues Passwort" : "Passwort"}</span>
              <input type="password" autoComplete="new-password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} required={!userForm.id} />
            </label>
          </div>

          <div className="field-stack" role="radiogroup" aria-label="Rolle">
            <span className="field-label">Rolle</span>
            <div className="role-picker">
              {ROLE_OPTIONS.map((role) => (
                <label key={role.code} className="role-picker-option">
                  <input
                    type="radio"
                    name="role_code"
                    value={role.code}
                    checked={userForm.role_code === role.code}
                    onChange={(event) => setUserForm((current) => ({ ...current, role_code: event.target.value }))}
                  />
                  {role.label}
                </label>
              ))}
            </div>
          </div>

          <div className="two-col">
            <label className="field-radio-option">
              <input type="checkbox" checked={userForm.is_active} onChange={(event) => setUserForm((current) => ({ ...current, is_active: event.target.checked }))} />
              Aktiv
            </label>
            <label className="field-radio-option">
              <input type="checkbox" checked={userForm.login_enabled} onChange={(event) => setUserForm((current) => ({ ...current, login_enabled: event.target.checked }))} />
              Login aktivieren
            </label>
          </div>

          {userForm.is_participant_account ? (
            <div className="info-note">
              Dieses Konto wurde automatisch aus einem Teilnehmer erstellt. Fuer den ersten Login bitte Login aktivieren
              und ein neues Passwort setzen.
            </div>
          ) : null}

          {formError && (
            <div className="form-error-banner">{formError}</div>
          )}

          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setUserModalOpen(false)}>
              Abbrechen
            </button>
            <button type="submit" className="button-primary">
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
            <button type="submit" className="button-secondary">
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
