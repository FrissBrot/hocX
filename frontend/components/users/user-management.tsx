"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { EffectivePermissions, RoleChecklist } from "@/components/users/role-fields";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DocsLink, HelpPopover } from "@/components/ui/help-popover";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { RoleRead, UserSummary } from "@/types/api";
import { roleName, rolesLabel } from "@/lib/permissions";
import { defaultRoleIds, emptyUserForm, isUserFormValid, userFormBlocker, userFormToPayload, UserFormState } from "@/components/users/user-form-shared";

type Props = {
  initialUsers: UserSummary[];
  roles: RoleRead[];
  // Eigene effektive Berechtigungen - Rollen darüber hinaus sind gesperrt (keine Rechteausweitung).
  actorPermissions: string[];
  enabledFeatures: string[];
};

export function UserManagement({ initialUsers, roles, actorPermissions, enabledFeatures }: Props) {
  const tNav = useTranslations("nav");
  const t = useTranslations("users");
  const tSecurity = useTranslations("security");
  const roleLabel = (user: UserSummary) => rolesLabel(user.roles, tNav);
  const showToast = useToast();
  const confirm = useConfirm();
  const [users, setUsers] = useState(initialUsers);
  // Diese Seite verwaltet Logins: Standard ist deshalb «Mit Login» (Bereichs-Audit 05).
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
  // Einladung per E-Mail ist der Standardweg; «Passwort direkt setzen» nur als Nebenoption.
  const [inviteAvailable, setInviteAvailable] = useState(false);
  const [loginMode, setLoginMode] = useState<"invite" | "password">("invite");
  const [loginBusy, setLoginBusy] = useState(false);
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
      const haystack = `${user.display_name} ${user.first_name} ${user.last_name} ${user.email} ${roleLabel(user)}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [search, tabUsers]);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<{ enabled: boolean }>("/api/auth/password-reset/available")
      .then((result) => { if (!cancelled) setInviteAvailable(Boolean(result?.enabled)); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const errorText = (error: unknown, fallback: string) => apiErrorMessage(error, tSecurity, "apiErrors", fallback);

  function openNewUser() {
    setUserForm(emptyUserForm("", defaultRoleIds(roles)));
    setFormError(null);
    setUserModalOpen(true);
  }

  function openEditUser(user: UserSummary) {
    setUserForm({
      id: user.id,
      first_name: user.first_name ?? "",
      last_name: user.last_name ?? "",
      display_name: user.display_name,
      email: user.email ?? "",
      password: "",
      preferred_language: user.preferred_language,
      is_active: user.is_active,
      login_enabled: user.login_enabled,

      tenant_id: user.tenant_id,
      role_ids: user.roles.map((role) => role.id),
      system_role: "reader"
    });
    setFormError(null);
    setUserModalOpen(true);
  }

  function openEnableLogin(user: UserSummary) {
    setLoginModalUser(user);
    setLoginEmail(user.email ?? "");
    setLoginPassword("");
    setLoginError(null);
    setLoginMode(inviteAvailable ? "invite" : "password");
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
    setLoginBusy(true);
    try {
      if (loginMode === "invite") {
        // Die Einladung geht an die gespeicherte Adresse: eine geänderte zuerst speichern.
        if (loginEmail.trim() !== (loginModalUser.email ?? "")) {
          const saved = await browserApiFetch<UserSummary>(`/api/users/${loginModalUser.id}`, {
            method: "PATCH",
            body: JSON.stringify({ email: loginEmail.trim() })
          });
          setUsers((current) => current.map((user) => user.id === saved.id ? saved : user));
        }
        await browserApiFetch(`/api/participants/${loginModalUser.id}/invite`, { method: "POST" });
        setLoginModalOpen(false);
        showToast(t("toasts.inviteSent", { email: loginEmail.trim() }), "success");
        return;
      }
      const updated = await browserApiFetch<UserSummary>(`/api/users/${loginModalUser.id}`, {
        method: "PATCH",
        body: JSON.stringify({ email: loginEmail, password: loginPassword, login_enabled: true })
      });
      setUsers((current) => current.map((user) => user.id === updated.id ? updated : user));
      setLoginModalOpen(false);
      showToast(t("toasts.loginEnabled"), "success");
    } catch (error) {
      setLoginError(errorText(error, t("toasts.loginEnableFailed")));
    } finally {
      setLoginBusy(false);
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
      const msg = errorText(error, t("toasts.userSaveFailed"));
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  // «Login entziehen» statt «Löschen»: die Person bleibt mit Anwesenheit, Bussen und Aufgaben
  // erhalten, nur die Anmeldung endet (alle Sitzungen werden beendet). Ganz löschen lässt sich
  // eine Person nur unter «Mitglieder», mit ausdrücklicher Rückfrage (Bereichs-Audit 05).
  async function revokeLogin(target: UserSummary) {
    const ok = await confirm({
      title: t("revokeLogin.confirmTitle", { name: target.display_name }),
      message: t("revokeLogin.confirmMessage", { name: target.display_name }),
      tone: "danger",
      confirmLabel: t("revokeLogin.action"),
    });
    if (!ok) return;
    try {
      const updated = await browserApiFetch<UserSummary>(`/api/users/${target.id}`, {
        method: "PATCH",
        body: JSON.stringify({ login_enabled: false })
      });
      setUsers((current) => current.map((user) => (user.id === updated.id ? updated : user)));
      showToast(t("revokeLogin.done", { name: target.display_name }), "success");
    } catch (error) {
      showToast(errorText(error, t("revokeLogin.failed")), "error");
    }
  }

  const loginBlocker: "email" | "password" | null = !loginEmail.trim()
    ? "email"
    : loginMode === "password" && loginPassword.length < 12
      ? "password"
      : null;

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
        <DataTable className="data-table-lg" emptyMessage={search.trim() ? t("emptySearch") : t("emptyWithLogin")} columns={[t("columns.displayName"), t("columns.name"), t("columns.email"), t("columns.role"), t("columns.actions")]}>
          {visibleUsers.map((user) => (
            <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
              <td>
                <strong>{user.display_name}</strong>
                {user.is_active ? null : <> <Badge variant="neutral">{t("inactiveBadge")}</Badge></>}
              </td>
              <td>{user.first_name} {user.last_name}</td>
              <td>{user.email}</td>
              <td>
                <span className="pill">{roleLabel(user)}</span>
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
                      void revokeLogin(user);
                    }}
                  >
                    {t("revokeLogin.action")}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
      ) : (
        <DataTable className="data-table-lg" emptyMessage={search.trim() ? t("emptySearch") : t("emptyWithoutLogin")} columns={[t("columns.name"), t("columns.participantEmail"), t("columns.role"), t("columns.actions")]}>
          {visibleUsers.map((user) => (
            <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
              <td>
                <strong>{user.display_name}</strong>
                {user.is_active ? null : <> <Badge variant="neutral">{t("inactiveBadge")}</Badge></>}
              </td>
              <td>{user.email ?? <span className="muted">–</span>}</td>
              <td>
                <span className="pill">{roleLabel(user)}</span>
              </td>
              <td>
                <div className="table-actions table-actions-start">

                  <button type="button" className="button-secondary" disabled={!user.is_active} title={user.is_active ? undefined : t("enableLoginInactive")} onClick={(event) => { event.stopPropagation(); openEnableLogin(user); }}>
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
          {roles.map((role) => (
            <div key={role.id} className="field-stack">
              <span className="field-label">{roleName(role, tNav)}</span>
              <span className="muted">{role.description ?? (role.system_key ? t(`roleDescriptions.${role.system_key}`) : "")}</span>
            </div>
          ))}
          <DocsLink page="rollen" anchor="standardrollen">{t("rolesDocs")}</DocsLink>
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

          <div className="field-stack">
            <span className="field-label">
              {t("rolesLabel")}{" "}
              <HelpPopover topic={t("rolesLabel")} docs={{ page: "rollen", anchor: "standardrollen" }}>{t("rolesHelp")}</HelpPopover>
            </span>
          </div>
          <div className="two-col">
            <RoleChecklist
              roles={roles}
              value={userForm.role_ids}
              actorPermissions={actorPermissions}
              onChange={(roleIds) => setUserForm((current) => ({ ...current, role_ids: roleIds }))}
            />
            <EffectivePermissions roles={roles} roleIds={userForm.role_ids} enabledFeatures={enabledFeatures} />
          </div>

          <div className="two-col">
            <label className="field-radio-option">
              <input type="checkbox" checked={userForm.is_active} onChange={(event) => setUserForm((current) => ({ ...current, is_active: event.target.checked }))} />
              {t("active")}
            </label>
            <label className="field-radio-option">
              <input type="checkbox" checked={userForm.login_enabled} onChange={(event) => setUserForm((current) => ({ ...current, login_enabled: event.target.checked }))} />
              {t("enableLogin")}
              <HelpPopover topic={t("enableLogin")} docs={{ page: "mitglieder", anchor: "login" }}>{t("loginHelp")}</HelpPopover>
            </label>
          </div>

          {formError && (
            <div className="form-error-banner">{formError}</div>
          )}

          <div className="modal-actions">
            {userFormBlocker(userForm) ? <span className="field-help">{t(`blockers.${userFormBlocker(userForm)}`)}</span> : null}
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
          {inviteAvailable ? (
            <div className="field-stack" role="radiogroup" aria-label={t("loginMode.label")}>
              <label className="field-radio-option">
                <input type="radio" name="login-mode" checked={loginMode === "invite"} onChange={() => setLoginMode("invite")} />
                {t("loginMode.invite")}
              </label>
              <span className="field-help">{t("loginMode.inviteHelp")}</span>
              <label className="field-radio-option">
                <input type="radio" name="login-mode" checked={loginMode === "password"} onChange={() => setLoginMode("password")} />
                {t("loginMode.password")}
              </label>
            </div>
          ) : (
            <span className="field-help">{t("loginMode.mailOff")}</span>
          )}
          {loginMode === "password" ? (
            <label className="field-stack">
              <span className="field-label">{t("password")}</span>
              <input
                type="password"
                autoComplete="new-password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
                minLength={12}
              />
              <span className="field-help">{t("passwordHelpSet")}</span>
            </label>
          ) : null}

          {loginError && <div className="form-error-banner">{loginError}</div>}

          <div className="modal-actions">
            {loginBlocker ? <span className="field-help">{t(`blockers.${loginBlocker}`)}</span> : null}
            <button type="button" className="button-ghost" onClick={() => setLoginModalOpen(false)}>
              {t("cancel")}
            </button>
            <button data-modal-save type="submit" className="button-primary" disabled={loginBusy || loginBlocker !== null}>
              {loginMode === "invite" ? t("loginMode.inviteSubmit") : t("enableLogin")}
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
