"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { getRoleOptions } from "@/components/admin/admin-tenant-settings-modal";
import { locales, localeConfig } from "@/i18n/locale-config.generated";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { AdminTenantSummary, AdminUserPage, UserSummary } from "@/types/api";
import { emptyUserForm, isUserFormValid, userFormToPayload, UserFormState } from "@/components/users/user-form-shared";

type Props = {
  initialPage: AdminUserPage;
  allTenants: AdminTenantSummary[];
};

const PAGE_SIZE = 50;

export function AdminUserManagement({ initialPage, allTenants }: Props) {
  const t = useTranslations("admin");
  const tUm = useTranslations("admin.userManagement");
  const roleOptions = useMemo(() => getRoleOptions(t), [t]);
  const roleLabel = useMemo(() => {
    const byCode = new Map(roleOptions.map((role) => [role.code, role.label]));
    return (roleCode: string) => byCode.get(roleCode) ?? roleCode;
  }, [roleOptions]);
  const showToast = useToast();
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const users = page.items;
  const [search, setSearch] = useState("");
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<UserFormState>(() => emptyUserForm(allTenants[0]?.id ?? ""));
  const [formError, setFormError] = useState<string | null>(null);
  const [mfaModalUser, setMfaModalUser] = useState<UserSummary | null>(null);
  const visibleUsers = users;

  async function fetchPage(nextOffset: number, query: string) {
    setLoading(true);
    try {
      const q = query.trim();
      const result = await browserApiFetch<AdminUserPage>(
        `/api/admin/users?limit=${PAGE_SIZE}&offset=${nextOffset}${q ? `&q=${encodeURIComponent(q)}` : ""}`
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

  // Debounced re-fetch from offset 0 whenever the search text changes - a fresh search
  // always restarts pagination, since "page 2 of the old query" is meaningless once the
  // filter changes.
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

  function openNewUser() {
    setUserForm(emptyUserForm(allTenants[0]?.id ?? ""));
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
      role_code: user.role_code
    });
    setFormError(null);
    setUserModalOpen(true);
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    try {
      const payload = userFormToPayload(userForm);

      const saved = userForm.id
        ? await browserApiFetch<UserSummary>(`/api/admin/users/${userForm.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload)
          })
        : await browserApiFetch<UserSummary>("/api/admin/users", {
            method: "POST",
            body: JSON.stringify(payload)
          });

      await fetchPage(offset, search);
      setUserModalOpen(false);
      showToast(userForm.id ? tUm("toasts.userSaved") : tUm("toasts.userCreated"), "success");
    } catch (error) {
      const msg = error instanceof Error ? error.message : tUm("toasts.userSaveFailed");
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  function openMfa(user: UserSummary) {
    setMfaModalUser(user);
  }

  return (
    <div className="grid">
      <DataToolbar
        title={tUm("toolbarTitle")}
        description={tUm("toolbarDescription")}
        actions={
          <button type="button" className="button-secondary" onClick={openNewUser}>
            {tUm("newUser")}
          </button>
        }
      />

      <article className="card">
        <label className="field-stack">
          <span className="field-label">{tUm("searchLabel")}</span>
          <SearchInput value={search} onChange={setSearch} placeholder={tUm("searchPlaceholder")} />
        </label>
      </article>

      <DataTable
        columns={[tUm("columns.displayName"), tUm("columns.email"), tUm("columns.tenant"), tUm("columns.role"), tUm("columns.login"), tUm("columns.actions")]}
        emptyMessage={loading ? tUm("loading") : tUm("emptyUsers")}
      >
        {visibleUsers.map((user) => (
          <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
            <td>
              <strong>{user.display_name}</strong>
            </td>
            <td>{user.email}</td>
            <td>{user.tenant_name}</td>
            <td>
              <span className="pill">{roleLabel(user.role_code)}</span>
            </td>
            <td>{user.login_enabled ? tUm("loginActive") : tUm("loginDisabled")}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className="button-secondary"
                  onClick={(event) => {
                    event.stopPropagation();
                    openMfa(user);
                  }}
                >
                  {tUm("mfaButton")}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />

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
              <input value={userForm.first_name} onChange={(event) => setUserForm((current) => ({ ...current, first_name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("lastName")}</span>
              <input value={userForm.last_name} onChange={(event) => setUserForm((current) => ({ ...current, last_name: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("displayName")}</span>
              <input value={userForm.display_name} onChange={(event) => setUserForm((current) => ({ ...current, display_name: event.target.value }))} />
            </label>
          </div>

          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">{tUm("email")}</span>
              <input value={userForm.email} onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))} />
            </label>
            <label className="field-stack">
              <span className="field-label">{userForm.id ? tUm("newPassword") : tUm("password")}</span>
              <input type="password" autoComplete="new-password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} />
              <span className="field-help">
                {userForm.id
                  ? tUm("passwordHelpEdit")
                  : tUm("passwordHelpCreate")}
              </span>
            </label>
            <label className="field-stack">
              <span className="field-label">{tUm("language")}</span>
              <select value={userForm.preferred_language} onChange={(event) => setUserForm((current) => ({ ...current, preferred_language: event.target.value }))}>
                {locales.map((code) => (
                  <option key={code} value={code}>
                    {localeConfig[code].nativeLabel}
                  </option>
                ))}
              </select>
            </label>
            <label className="checkbox-line">
              <input type="checkbox" checked={userForm.is_active} onChange={(event) => setUserForm((current) => ({ ...current, is_active: event.target.checked }))} />
              {tUm("active")}
            </label>
          </div>

          <div className="two-col">
            <label className="checkbox-line">
              <input type="checkbox" checked={userForm.login_enabled} onChange={(event) => setUserForm((current) => ({ ...current, login_enabled: event.target.checked }))} />
              {tUm("enableLogin")}
            </label>
          </div>

          <div className="two-col">
            {userForm.id ? (
              <label className="field-stack">
                <span className="field-label">{tUm("tenant")}</span>
                <input value={users.find((user) => user.id === userForm.id)?.tenant_name ?? ""} readOnly />
                <span className="field-help">{tUm("tenantFixedHelp")}</span>
              </label>
            ) : (
              <label className="field-stack">
                <span className="field-label">{tUm("tenant")}</span>
                <SearchableSelect
                  options={allTenants}
                  getId={(tenant) => String(tenant.id)}
                  getLabel={(tenant) => tenant.name}
                  value={userForm.tenant_id || null}
                  onChange={(tenant) => setUserForm((current) => ({ ...current, tenant_id: tenant ? String(tenant.id) : "" }))}
                />
              </label>
            )}
            <label className="field-stack">
              <span className="field-label">{tUm("role")}</span>
              <select value={userForm.role_code} onChange={(event) => setUserForm((current) => ({ ...current, role_code: event.target.value }))}>
                {roleOptions.map((role) => (
                  <option key={role.code} value={role.code}>
                    {role.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {formError && <div className="form-error-banner">{formError}</div>}

          <div className="table-actions table-actions-start">
            <button data-modal-save type="submit" className="button-secondary" disabled={!isUserFormValid(userForm, { requireTenant: true })}>
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
