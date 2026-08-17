"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { ROLE_OPTIONS } from "@/components/admin/admin-tenant-settings-modal";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { Tabs } from "@/components/ui/tabs";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { AdminTenantSummary, AdminUserPage, UserSummary } from "@/types/api";
import {
  addOrUpsertMembership,
  buildTenantNameMap,
  emptyUserForm,
  removeMembershipEntry,
  userFormToPayload,
  UserFormState
} from "@/components/users/user-form-shared";

type Props = {
  initialPage: AdminUserPage;
  allTenants: AdminTenantSummary[];
};

const PAGE_SIZE = 50;

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
  const [userForm, setUserForm] = useState<UserFormState>(() => emptyUserForm(allTenants));
  const [formError, setFormError] = useState<string | null>(null);
  const [mergeModalOpen, setMergeModalOpen] = useState(false);
  const [mergeSourceUserId, setMergeSourceUserId] = useState<number | null>(null);
  const [mergeTargetUserId, setMergeTargetUserId] = useState("");
  const [mfaModalUser, setMfaModalUser] = useState<UserSummary | null>(null);
  // The merge target can be any eligible user tenant-wide, not just one on the currently
  // displayed page, so it's loaded separately (unpaginated) when the merge modal opens.
  const [mergeCandidates, setMergeCandidates] = useState<UserSummary[]>([]);

  const tenantNameById = useMemo(() => buildTenantNameMap(allTenants), [allTenants]);

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
    setUserForm(emptyUserForm(allTenants));
    setFormError(null);
    setUserModalOpen(true);
  }

  function openEditUser(user: UserSummary) {
    const remainingTenants = allTenants.filter((t) => !user.memberships.some((m) => m.tenant_id === t.id));
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
      pickerTenantId: remainingTenants[0] ? String(remainingTenants[0].id) : "",
      pickerRoleCode: "reader"
    });
    setFormError(null);
    setUserModalOpen(true);
  }

  function changeMembershipRole(tenantId: number, roleCode: string) {
    setUserForm((current) => ({
      ...current,
      memberships: current.memberships.map((membership) =>
        membership.tenant_id === tenantId ? { ...membership, role_code: roleCode } : membership
      )
    }));
  }

  function addMembership() {
    if (!userForm.pickerTenantId) return;
    const tenantId = Number(userForm.pickerTenantId);
    setUserForm((current) => ({
      ...current,
      memberships: addOrUpsertMembership(current.memberships, tenantId, current.pickerRoleCode, "add")
    }));
  }

  function removeMembership(tenantId: number) {
    setUserForm((current) => ({
      ...current,
      memberships: removeMembershipEntry(current.memberships, tenantId)
    }));
  }

  const remainingTenantsToAdd = allTenants.filter((t) => !userForm.memberships.some((m) => m.tenant_id === t.id));

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
      const eligible = result.items.filter(isEligible);
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
          target_user_id: Number(mergeTargetUserId),
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
          <SearchInput value={search} onChange={setSearch} placeholder="Benutzer durchsuchen" />
        </label>
      </article>

      <DataTable
        columns={["Anzeigename", "E-Mail", "Mandantenrollen", "Login", "Aktionen"]}
        emptyMessage={loading ? "Wird geladen…" : "Keine Benutzer gefunden."}
      >
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
                    openMfa(user);
                  }}
                >
                  MFA
                </button>
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

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />

      <Modal
        open={userModalOpen}
        onClose={() => setUserModalOpen(false)}
        title={userForm.id ? "Benutzer bearbeiten" : "Benutzer erstellen"}
        description=""
        size="wide"
      >
        <form className="grid" onSubmit={submitUser} id="user-form">
          <Tabs
            tabs={[
              {
                id: "konto",
                label: "Konto",
                content: (
                  <div className="grid">
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
                  </div>
                )
              },
              {
                id: "rollen",
                label: `Mandantenrollen (${userForm.memberships.length})`,
                content: (
                  <div className="grid">
                    <div className="table-shell">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Mandant</th>
                            <th>Rolle</th>
                            <th>Aktion</th>
                          </tr>
                        </thead>
                        <tbody>
                          {userForm.memberships.map((membership) => (
                            <tr key={membership.tenant_id}>
                              <td>{tenantNameById.get(membership.tenant_id) ?? `Tenant #${membership.tenant_id}`}</td>
                              <td>
                                <select value={membership.role_code} onChange={(event) => changeMembershipRole(membership.tenant_id, event.target.value)}>
                                  {ROLE_OPTIONS.map((r) => (
                                    <option key={r.code} value={r.code}>
                                      {r.label}
                                    </option>
                                  ))}
                                </select>
                              </td>
                              <td>
                                <button type="button" className="button-inline button-ghost" onClick={() => removeMembership(membership.tenant_id)}>
                                  Entfernen
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {userForm.memberships.length === 0 && <div className="table-empty muted">Noch keine Mandantenrollen zugewiesen.</div>}
                    </div>

                    {remainingTenantsToAdd.length > 0 && (
                      <div className="card">
                        <div className="eyebrow">Mandant hinzufügen</div>
                        <div className="role-picker">
                          <label className="field-stack">
                            <span className="field-label">Mandant</span>
                            <select value={userForm.pickerTenantId} onChange={(event) => setUserForm((current) => ({ ...current, pickerTenantId: event.target.value }))}>
                              {remainingTenantsToAdd.map((tenant) => (
                                <option key={tenant.id} value={tenant.id}>
                                  {tenant.name}
                                </option>
                              ))}
                            </select>
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
                            <button type="button" className="button-inline" onClick={addMembership}>
                              Hinzufügen
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )
              }
            ]}
          />

          {formError && <div className="form-error-banner">{formError}</div>}

          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Speichern
            </button>
          </div>
        </form>
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
              {mergeCandidates
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
