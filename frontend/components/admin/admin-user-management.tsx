"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { ROLE_OPTIONS } from "@/components/admin/admin-tenant-settings-modal";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { AdminTenantSummary, AdminUserPage, UserSummary } from "@/types/api";
import { emptyUserForm, userFormToPayload, UserFormState } from "@/components/users/user-form-shared";

type Props = {
  initialPage: AdminUserPage;
  allTenants: AdminTenantSummary[];
};

const PAGE_SIZE = 50;

function roleLabel(roleCode: string) {
  return ROLE_OPTIONS.find((role) => role.code === roleCode)?.label ?? roleCode;
}

function isEligible(user: UserSummary) {
  // Nur Benutzer mit freigeschaltetem Login und echter (nicht automatisch generierter
  // Teilnehmer-Platzhalter-) E-Mail sind hier relevant - Schattenaccounts ohne Login
  // sind nur internes Implementierungsdetail der Teilnehmerverwaltung.
  return user.login_enabled && !user.email.endsWith("@participants.hocx.local");
}

export function AdminUserManagement({ initialPage, allTenants }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const users = page.items;
  const [search, setSearch] = useState("");
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm, setUserForm] = useState<UserFormState>(() => emptyUserForm(allTenants[0]?.id ?? ""));
  const [formError, setFormError] = useState<string | null>(null);
  const [mergeModalOpen, setMergeModalOpen] = useState(false);
  const [mergeSourceUserId, setMergeSourceUserId] = useState<string | null>(null);
  const [mergeTargetUserId, setMergeTargetUserId] = useState("");
  const [mfaModalUser, setMfaModalUser] = useState<UserSummary | null>(null);
  // The merge target can be any eligible user tenant-wide, not just one on the currently
  // displayed page, so it's loaded separately (unpaginated) when the merge modal opens.
  const [mergeCandidates, setMergeCandidates] = useState<UserSummary[]>([]);

  // eligibleUsers/visibleUsers: server now applies `search` before pagination (audit A1,
  // 2026-08-16 - fetchPage below sends it as `q`), so `page.items` is already the matching
  // set for the current page. Only the login_enabled/participant-placeholder filter stays
  // client-side (unrelated to search, always applied on top).
  const visibleUsers = useMemo(() => users.filter(isEligible), [users]);

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
      showToast(userForm.id ? "Benutzer gespeichert" : "Benutzer erstellt", "success");
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Benutzer konnte nicht gespeichert werden";
      setFormError(msg);
      showToast(msg, "error");
    }
  }

  async function openMerge(user: UserSummary) {
    setMergeSourceUserId(user.id);
    setMergeCandidates([]);
    setMergeTargetUserId("");
    setMergeModalOpen(true);
    try {
      const result = await browserApiFetch<AdminUserPage>("/api/admin/users");
      // Ein Konto gehört genau einem Mandanten - zusammenführen lässt sich nur innerhalb desselben.
      const eligible = result.items.filter((candidate) => isEligible(candidate) && candidate.tenant_id === user.tenant_id);
      setMergeCandidates(eligible);
      const fallbackTarget = eligible.find((candidate) => candidate.id !== user.id);
      setMergeTargetUserId(fallbackTarget ? String(fallbackTarget.id) : "");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzerliste konnte nicht geladen werden", "error");
    }
  }

  function openMfa(user: UserSummary) {
    setMfaModalUser(user);
  }

  async function mergeUsers() {
    if (!mergeSourceUserId || !mergeTargetUserId) return;
    const ok = await confirm({
      message: "Benutzer wirklich zusammenführen? Der Quellbenutzer wird danach unwiderruflich gelöscht.",
      tone: "danger",
      confirmLabel: "Jetzt mergen",
    });
    if (!ok) return;
    try {
      await browserApiFetch<UserSummary>("/api/admin/users/merge", {
        method: "POST",
        body: JSON.stringify({
          source_user_id: mergeSourceUserId,
          target_user_id: mergeTargetUserId,
        }),
      });
      await fetchPage(offset, search);
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
        description="Alle Benutzer über alle Mandanten hinweg. Jedes Konto gehört genau einem Mandanten."
        actions={
          <button type="button" className="button-secondary" onClick={openNewUser}>
            Neuer Benutzer
          </button>
        }
      />

      <article className="card">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <SearchInput value={search} onChange={setSearch} placeholder="Benutzer durchsuchen" />
        </label>
      </article>

      <DataTable
        columns={["Anzeigename", "E-Mail", "Mandant", "Rolle", "Login", "Aktionen"]}
        emptyMessage={loading ? "Wird geladen…" : "Keine Benutzer gefunden."}
      >
        {visibleUsers.map((user) => (
          <tr key={user.id} className="table-row-clickable" onClick={() => openEditUser(user)}>
            <td>
              <strong>{user.display_name}</strong>
              {user.is_participant_account ? <div className="muted">Teilnehmer-Konto</div> : null}
            </td>
            <td>{user.email}</td>
            <td>{user.tenant_name}</td>
            <td>
              <span className="pill">{roleLabel(user.role_code)}</span>
            </td>
            <td>{user.login_enabled ? "Aktiv" : "Deaktiviert"}</td>
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
                  MFA
                </button>
                <button
                  type="button"
                  className="button-secondary"
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

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />

      <Modal
        open={userModalOpen}
        onClose={() => setUserModalOpen(false)}
        title={userForm.id ? "Benutzer bearbeiten" : "Benutzer erstellen"}
        description=""
        size="wide"
      >
        <ModalSaveForm className="grid" onSubmit={submitUser} id="user-form">
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
              <input type="password" autoComplete="new-password" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} required={!userForm.id} minLength={8} />
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

          <div className="two-col">
            {userForm.id ? (
              <label className="field-stack">
                <span className="field-label">Mandant</span>
                <input value={users.find((user) => user.id === userForm.id)?.tenant_name ?? ""} readOnly />
                <span className="field-help">Der Mandant eines Kontos steht fest und lässt sich nicht ändern.</span>
              </label>
            ) : (
              <label className="field-stack">
                <span className="field-label">Mandant</span>
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
              <span className="field-label">Rolle</span>
              <select value={userForm.role_code} onChange={(event) => setUserForm((current) => ({ ...current, role_code: event.target.value }))}>
                {ROLE_OPTIONS.map((role) => (
                  <option key={role.code} value={role.code}>
                    {role.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {formError && <div className="form-error-banner">{formError}</div>}

          <div className="table-actions table-actions-start">
            <button data-modal-save type="submit" className="button-secondary">
              Speichern
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <MfaAdminModal
        open={!!mfaModalUser}
        onClose={() => setMfaModalUser(null)}
        title={mfaModalUser ? `MFA von ${mfaModalUser.display_name}` : "MFA"}
        loadPath={mfaModalUser ? `/api/admin/users/${mfaModalUser.id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/admin/users/${mfaModalUser.id}/mfa/factors` : null}
      />

      <Modal
        open={mergeModalOpen}
        onClose={() => setMergeModalOpen(false)}
        title="Benutzer zusammenführen"
        description="Der Quellbenutzer wird in den Zielbenutzer gemergt (inkl. Rolle und Teilnehmer-Links) und danach gelöscht. Möglich nur innerhalb desselben Mandanten."
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Quellbenutzer</span>
            <input value={users.find((user) => user.id === mergeSourceUserId)?.display_name ?? ""} readOnly />
          </label>
          <label className="field-stack">
            <span className="field-label">Zielbenutzer</span>
            <SearchableSelect
              options={mergeCandidates.filter((user) => user.id !== mergeSourceUserId)}
              getId={(user) => String(user.id)}
              getLabel={(user) => `${user.display_name} (${user.email})`}
              value={mergeTargetUserId || null}
              onChange={(user) => setMergeTargetUserId(user ? String(user.id) : "")}
            />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-secondary" onClick={() => void mergeUsers()} disabled={!mergeTargetUserId}>
              Jetzt mergen
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
