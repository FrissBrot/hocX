"use client";

import { FormEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { getRoleOptions } from "@/components/admin/admin-tenant-settings-modal";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { formatRoleLabel } from "@/components/ui/app-shell-nav";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { UserSummary } from "@/types/api";
import { emptyUserForm, isUserFormValid, userFormToPayload, UserFormState } from "@/components/users/user-form-shared";

type Props = {
  initialUsers: UserSummary[];
};

function getRoleDescriptions(t: (key: string) => string): { code: string; description: string }[] {
  return [
    { code: "admin", description: t("roleDescriptions.admin") },
    { code: "writer", description: t("roleDescriptions.writer") },
    { code: "kassier", description: t("roleDescriptions.kassier") },
    { code: "reader", description: t("roleDescriptions.reader") },
  ];
}

export function UserManagement({ initialUsers }: Props) {
  const tNav = useTranslations("nav");
  const t = useTranslations("users");
  const tAdmin = useTranslations("admin");
  const roleOptions = useMemo(() => getRoleOptions(tAdmin), [tAdmin]);
  const roleDescriptions = useMemo(() => getRoleDescriptions(t), [t]);
  const roleLabel = useMemo(() => {
    const byCode = new Map(roleOptions.map((role) => [role.code, role.label]));
    return (roleCode: string) => byCode.get(roleCode) ?? roleCode;
  }, [roleOptions]);
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
      showToast(t("toasts.loginEnabled"), "success");
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : t("toasts.loginEnableFailed"));
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
      showToast(userForm.id ? t("toasts.userSaved") : t("toasts.userCreated"), "success");
    } catch (error) {
      const msg = error instanceof Error ? error.message : t("toasts.userSaveFailed");
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  async function deleteUser(userId: string, displayName: string) {
    const ok = await confirm({
      message: t("toasts.deleteConfirm", { name: displayName }),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/users/${userId}`, { method: "DELETE" });
      setUsers((current) => current.filter((user) => user.id !== userId));
      showToast(t("toasts.userDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.userDeleteFailed"), "error");
    }
  }

  // Nur das eigene Konto und keine Teilnehmer ohne Login: die Liste hätte nichts zu zeigen.
  const hasOnlyOwnAccess = activeUsers.length <= 1 && usersWithoutLogin.length === 0;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{hasOnlyOwnAccess ? t("ownAccessOnlyHint") : t("pageHint")}</p>
        </div>
        {hasOnlyOwnAccess ? null : (
          <button type="button" className="button-primary" onClick={openNewUser}>
            {t("newUser")}
          </button>
        )}
      </div>

      {hasOnlyOwnAccess ? (
        <EmptyState
          title={t("emptyState.title")}
          description={t("emptyState.description")}
          actions={
            <>
              <button type="button" className="button-primary" onClick={openNewUser}>
                {t("emptyState.invite")}
              </button>
              <button type="button" className="button-secondary" onClick={() => setRolesModalOpen(true)}>
                {t("explainRoles")}
              </button>
            </>
          }
        />
      ) : (
      <>
      <div className="list-filter-row">
        <FilterTabs
          options={[
            { value: "active", label: t("tabs.active", { count: activeUsers.length }), count: activeUsers.length },
            { value: "nologin", label: t("tabs.participants", { count: usersWithoutLogin.length }), count: usersWithoutLogin.length },
          ]}
          value={userTab}
          onChange={setUserTab}
        />
        <div className="list-filter-search">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder={userTab === "active" ? t("searchUsers") : t("searchParticipants")}
          />
        </div>
      </div>

      {userTab === "active" ? (
        <DataTable className="data-table-lg" columns={[t("columns.displayName"), t("columns.name"), t("columns.email"), t("columns.role"), t("columns.actions")]}>
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
                    {t("mfaButton")}
                  </button>
                  <button
                    type="button"
                    className="button-secondary button-danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteUser(user.id, user.display_name);
                    }}
                  >
                    {t("delete")}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      ) : (
        <DataTable className="data-table-lg" columns={[t("columns.name"), t("columns.participantEmail"), t("columns.role"), t("columns.actions")]}>
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
                    {t("mfaButton")}
                  </button>
                  <button type="button" className="button-secondary" onClick={() => openEnableLogin(user)}>
                    {t("enableLogin")}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      )}
      </>
      )}

      <Modal open={rolesModalOpen} onClose={() => setRolesModalOpen(false)} title={t("explainRoles")} description={t("explainRolesDescription")}>
        <div className="grid">
          {roleDescriptions.map((role) => (
            <div key={role.code} className="field-stack">
              <span className="field-label">{formatRoleLabel(role.code, tNav)}</span>
              <span className="muted">{role.description}</span>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => setRolesModalOpen(false)}>{t("close")}</button>
        </div>
      </Modal>

      <Modal
        open={userModalOpen}
        onClose={() => setUserModalOpen(false)}
        title={userForm.id ? t("editUserTitle") : t("createUserTitle")}
        description={t("userModalDescription")}
        size="wide"
      >
        <ModalSaveForm className="grid" onSubmit={submitUser}>
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">{t("firstName")}</span>
              <input value={userForm.first_name} onChange={(event) => setUserForm((current) => ({ ...current, first_name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("lastName")}</span>
              <input value={userForm.last_name} onChange={(event) => setUserForm((current) => ({ ...current, last_name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("displayName")}</span>
              <input value={userForm.display_name} onChange={(event) => setUserForm((current) => ({ ...current, display_name: event.target.value }))} />
            </label>
          </div>

          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("email")}</span>
              <input value={userForm.email} onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{userForm.id ? t("newPassword") : t("password")}</span>
              <input type="password" autoComplete="new-password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} />
              <span className="field-help">
                {userForm.id
                  ? t("passwordHelpEdit")
                  : t("passwordHelpCreate")}
              </span>
            </label>
          </div>

          <div className="field-stack" role="radiogroup" aria-label={t("role")}>
            <span className="field-label">{t("role")}</span>
            <div className="role-picker">
              {roleOptions.map((role) => (
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
              {t("active")}
            </label>
            <label className="field-radio-option">
              <input type="checkbox" checked={userForm.login_enabled} onChange={(event) => setUserForm((current) => ({ ...current, login_enabled: event.target.checked }))} />
              {t("enableLogin")}
            </label>
          </div>

          {userForm.is_participant_account ? (
            <div className="info-note">
              {t("participantAutoNote")}
            </div>
          ) : null}

          {formError && (
            <div className="form-error-banner">{formError}</div>
          )}

          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setUserModalOpen(false)}>
              {t("cancel")}
            </button>
            <button data-modal-save type="submit" className="button-primary" disabled={!isUserFormValid(userForm)}>
              {t("save")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal
        open={loginModalOpen}
        onClose={() => setLoginModalOpen(false)}
        title={loginModalUser ? t("enableLoginForTitle", { name: loginModalUser.display_name }) : t("enableLoginTitle")}
        description={t("enableLoginDescription")}
      >
        <ModalSaveForm className="grid" onSubmit={submitEnableLogin}>
          <label className="field-stack">
            <span className="field-label">{t("email")}</span>
            <input type="email" value={loginEmail} onChange={(event) => setLoginEmail(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("password")}</span>
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
            <button data-modal-save type="submit" className="button-secondary">
              {t("enableLogin")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <MfaAdminModal
        open={!!mfaModalUser}
        onClose={() => setMfaModalUser(null)}
        title={mfaModalUser ? t("mfaTitle", { name: mfaModalUser.display_name }) : t("mfaTitleFallback")}
        loadPath={mfaModalUser ? `/api/users/${mfaModalUser.id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/users/${mfaModalUser.id}/mfa/factors` : null}
      />
    </div>
  );
}
