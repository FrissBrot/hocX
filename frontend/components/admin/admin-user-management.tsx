"use client";

import { FormEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { ColumnPicker, useColumnVisibility, type ColumnDef } from "@/components/admin/column-picker";
import { getRoleOptions } from "@/components/admin/admin-tenant-settings-modal";
import { TenantPicker } from "@/components/admin/tenant-picker";
import { locales, localeConfig } from "@/i18n/locale-config.generated";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import { useServerTable, type ServerTableConfig } from "@/lib/admin/use-server-table";
import { rolesLabel } from "@/lib/permissions";
import { AdminUserPage, UserSummary } from "@/types/api";
import { emptyUserForm, primarySystemRole, UserFormState } from "@/components/users/user-form-shared";

const PAGE_SIZE = 50;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type UserFilters = { tenant_id: string; q: string };

// Benutzer enthalten Personendaten: in der URL steht nur die Mandanten-ID, der Suchbegriff bleibt
// im Zustand der Seite (Plan §8.3).
export const USER_TABLE: ServerTableConfig<UserFilters> = {
  path: "/api/admin/users",
  pageSize: PAGE_SIZE,
  defaults: { tenant_id: "", q: "" },
  textKey: "q",
  syncTextToUrl: false,
  validate: { tenant_id: (value) => UUID.test(value) },
};

type AccessLinkResult = { purpose: "password_reset" | "invite" };

/** Formular ohne Passwort (1.5.1): Logins entstehen nur über einen Einladungs- bzw.
 * Zurücksetzungslink, den die Person selbst einlöst. */
type AdminUserForm = Omit<UserFormState, "password"> & { send_invite: boolean };

function emptyForm(): AdminUserForm {
  const { password: _password, ...rest } = emptyUserForm("");
  void _password;
  return { ...rest, send_invite: false };
}

export function AdminUserManagement({ initialPage }: { initialPage: AdminUserPage }) {
  const t = useTranslations("admin");
  const tUm = useTranslations("admin.userManagement");
  const tNav = useTranslations("nav");
  const roleOptions = useMemo(() => getRoleOptions(t), [t]);
  const roleLabel = (user: UserSummary) => rolesLabel(user.roles, tNav);
  const showToast = useToast();
  const confirm = useConfirm();
  const table = useServerTable<UserFilters, AdminUserPage>(USER_TABLE, initialPage);
  const page = table.data ?? initialPage;
  const [originalSystemRole, setOriginalSystemRole] = useState<string | null>(null);
  const [originalLogin, setOriginalLogin] = useState(false);
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<AdminUserForm>(emptyForm);
  const [editTenantName, setEditTenantName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [mfaModalUser, setMfaModalUser] = useState<UserSummary | null>(null);

  const columns: ColumnDef[] = [
    { key: "name", label: tUm("columns.displayName"), required: true },
    { key: "email", label: tUm("columns.email") },
    { key: "tenant", label: tUm("columns.tenant") },
    { key: "role", label: tUm("columns.role") },
    { key: "login", label: tUm("columns.login") },
    { key: "mfa", label: tUm("columns.mfa"), hidden: true },
    { key: "actions", label: tUm("columns.actions"), required: true },
  ];
  const cols = useColumnVisibility("users", columns);
  const shown = columns.filter((column) => cols.isVisible(column.key));

  function update(next: Partial<AdminUserForm>) {
    setUserForm((current) => ({ ...current, ...next }));
  }

  function openNewUser() {
    setUserForm({ ...emptyForm(), tenant_id: table.filters.tenant_id });
    setOriginalSystemRole(null);
    setOriginalLogin(false);
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
      preferred_language: user.preferred_language,
      is_active: user.is_active,
      login_enabled: user.login_enabled,
      tenant_id: user.tenant_id,
      role_ids: user.roles.map((role) => role.id),
      system_role: primarySystemRole(user.roles),
      send_invite: false,
    });
    setEditTenantName(user.tenant_name ?? "");
    setOriginalSystemRole(primarySystemRole(user.roles));
    setOriginalLogin(user.login_enabled);
    setFormError(null);
    setUserModalOpen(true);
  }

  const formValid =
    userForm.display_name.trim() !== "" &&
    (userForm.id ? true : userForm.tenant_id !== "") &&
    (!userForm.send_invite || userForm.email.trim() !== "");

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const base = {
      first_name: userForm.first_name,
      last_name: userForm.last_name,
      display_name: userForm.display_name,
      email: userForm.email.trim() || null,
      preferred_language: userForm.preferred_language,
      is_active: userForm.is_active,
    };
    try {
      if (userForm.id) {
        // Login nur abschalten; einschalten geht über die Einladung (Person setzt ihr Passwort selbst)
        const payload = {
          ...base,
          ...(userForm.system_role !== originalSystemRole ? { system_role: userForm.system_role } : {}),
          ...(originalLogin && !userForm.login_enabled ? { login_enabled: false } : {}),
        };
        await stepUpFetch<UserSummary>("user-manage", `/api/admin/users/${userForm.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        const payload = { ...base, tenant_id: userForm.tenant_id, system_role: userForm.system_role, send_invite: userForm.send_invite };
        await stepUpFetch<UserSummary>("user-manage", "/api/admin/users", { method: "POST", body: JSON.stringify(payload) });
      }
      table.reload();
      setUserModalOpen(false);
      showToast(userForm.id ? tUm("toasts.userSaved") : userForm.send_invite ? tUm("toasts.userInvited") : tUm("toasts.userCreated"), "success");
    } catch (error) {
      const msg = error instanceof Error ? error.message : tUm("toasts.userSaveFailed");
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  async function sendAccessLink(user: UserSummary) {
    const ok = await confirm({
      message: user.login_enabled ? tUm("accessLink.confirmReset", { name: user.display_name }) : tUm("accessLink.confirmInvite", { name: user.display_name }),
      confirmLabel: user.login_enabled ? tUm("accessLink.reset") : tUm("accessLink.invite"),
    });
    if (!ok) return;
    try {
      const result = await stepUpFetch<AccessLinkResult>("user-credentials", `/api/admin/users/${user.id}/password-reset`, { method: "POST" });
      showToast(result.purpose === "invite" ? tUm("accessLink.inviteSent") : tUm("accessLink.resetSent"), "success");
      table.reload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : tUm("toasts.userSaveFailed"), "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title={tUm("toolbarTitle")}
        description={tUm("toolbarDescription")}
        actions={
          <>
            <ColumnPicker columns={columns} isVisible={cols.isVisible} onToggle={cols.toggle} />
            <button type="button" className="button-secondary" onClick={openNewUser}>
              {tUm("newUser")}
            </button>
          </>
        }
      />

      <article className="card admin-filter-grid">
        <label className="field-stack">
          <span className="field-label">{tUm("searchLabel")}</span>
          <SearchInput value={table.filters.q} onChange={(value) => table.setFilter("q", value)} placeholder={tUm("searchPlaceholder")} />
        </label>
        <label className="field-stack">
          <span className="field-label">{tUm("tenant")}</span>
          <TenantPicker value={table.filters.tenant_id || null} onChange={(tenant) => table.setFilter("tenant_id", tenant?.id ?? "")} nullLabel={tUm("allTenants")} />
        </label>
      </article>
      {table.failed ? <StatusBanner tone="error" message={tUm("loadFailed")} /> : null}

      <DataTable columns={shown.map((column) => column.label)} emptyMessage={table.loading ? tUm("loading") : tUm("emptyUsers")}>
        {page.items.map((user) => (
          <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)} /* a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Name) */>
            <td>
              <button type="button" className="table-row-link" onClick={(event) => { event.stopPropagation(); openEditUser(user); }}>
                {user.display_name}
              </button>
            </td>
            {cols.isVisible("email") ? <td>{user.email}</td> : null}
            {cols.isVisible("tenant") ? <td>{user.tenant_name}</td> : null}
            {cols.isVisible("role") ? (
              <td>
                <span className="pill">{roleLabel(user)}</span>
              </td>
            ) : null}
            {cols.isVisible("login") ? <td>{user.login_enabled ? tUm("loginActive") : tUm("loginDisabled")}</td> : null}
            {cols.isVisible("mfa") ? (
              <td>{user.mfa_enabled ? <Badge variant="success">{tUm("mfaOn")}</Badge> : <Badge variant="neutral">{tUm("mfaOff")}</Badge>}</td>
            ) : null}
            <td onClick={(event) => event.stopPropagation()}>
              <div className="table-actions table-actions-start">
                <button type="button" className="button-secondary" onClick={() => setMfaModalUser(user)}>
                  {tUm("mfaButton")}
                </button>
                <button type="button" className="button-secondary" disabled={!user.email || !user.is_active} onClick={() => void sendAccessLink(user)}>
                  {user.login_enabled ? tUm("accessLink.reset") : tUm("accessLink.invite")}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Pagination offset={table.offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={table.setOffset} />

      <Modal
        open={userModalOpen}
        onClose={() => setUserModalOpen(false)}
        title={userForm.id ? tUm("editUserTitle") : tUm("createUserTitle")}
        description=""
        size="wide"
      >
        <ModalSaveForm className="grid" onSubmit={submitUser} id="user-form">
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">{tUm("firstName")}</span>
              <input value={userForm.first_name} onChange={(event) => update({ first_name: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("lastName")}</span>
              <input value={userForm.last_name} onChange={(event) => update({ last_name: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("displayName")}</span>
              <input value={userForm.display_name} onChange={(event) => update({ display_name: event.target.value })} />
            </label>
          </div>

          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">{tUm("email")}</span>
              <input value={userForm.email} onChange={(event) => update({ email: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("language")}</span>
              <Select value={userForm.preferred_language} onChange={(event) => update({ preferred_language: event.target.value })}>
                {locales.map((code) => (
                  <option key={code} value={code}>
                    {localeConfig[code].nativeLabel}
                  </option>
                ))}
              </Select>
            </label>
            <label className="checkbox-line">
              <input type="checkbox" checked={userForm.is_active} onChange={(event) => update({ is_active: event.target.checked })} />
              {tUm("active")}
            </label>
          </div>

          <div className="two-col">
            {userForm.id ? (
              originalLogin ? (
                <label className="checkbox-line">
                  <input type="checkbox" checked={userForm.login_enabled} onChange={(event) => update({ login_enabled: event.target.checked })} />
                  {tUm("enableLogin")}
                </label>
              ) : (
                <span className="field-help">{tUm("loginViaInviteHelp")}</span>
              )
            ) : (
              <label className="checkbox-line">
                <input type="checkbox" checked={userForm.send_invite} onChange={(event) => update({ send_invite: event.target.checked })} />
                {tUm("sendInvite")}
              </label>
            )}
            <span className="field-help">{tUm("noPasswordHelp")}</span>
          </div>

          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{tUm("tenant")}</span>
              {userForm.id ? (
                <>
                  <input value={editTenantName} readOnly />
                  <span className="field-help">{tUm("tenantFixedHelp")}</span>
                </>
              ) : (
                <TenantPicker value={userForm.tenant_id || null} onChange={(tenant) => update({ tenant_id: tenant?.id ?? "" })} />
              )}
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("role")}</span>
              <Select value={userForm.system_role} onChange={(event) => update({ system_role: event.target.value as UserFormState["system_role"] })}>
                {roleOptions.map((role) => (
                  <option key={role.code} value={role.code}>
                    {role.label}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          {formError && <div className="form-error-banner">{formError}</div>}

          <div className="table-actions table-actions-start">
            <button data-modal-save type="submit" className="button-secondary" disabled={!formValid}>
              {tUm("save")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <MfaAdminModal
        open={!!mfaModalUser}
        onClose={() => setMfaModalUser(null)}
        title={mfaModalUser ? t("tenantModal.mfaTitle", { name: mfaModalUser.display_name }) : t("tenantModal.mfaTitleFallback")}
        loadPath={mfaModalUser ? `/api/admin/users/${mfaModalUser.id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/admin/users/${mfaModalUser.id}/mfa/factors` : null}
      />
    </div>
  );
}
