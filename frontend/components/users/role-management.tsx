"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { HelpPopover } from "@/components/ui/help-popover";
import { roleNeedsMfa } from "@/components/users/access-helpers";
import { Select } from "@/components/ui/select";
import { SCOPED_PERMISSIONS, expandPermissions, minimalPermissions, resolveScopes, roleName, type PermissionScope } from "@/lib/permissions";
import { PERMISSION_AREAS, PERMISSIONS, type PermissionKey } from "@/lib/permissions.generated";
import type { RoleRead } from "@/types/api";

type Props = {
  initialRoles: RoleRead[];
  // Eigene effektive Berechtigungen: nur diese lassen sich vergeben (keine Rechteausweitung).
  actorPermissions: string[];
  // Eigene Rechte, die nur für zugewiesene Objekte gelten: diese lassen sich nicht «für alle» vergeben.
  actorAssignedOnly?: string[];
  enabledFeatures: string[];
  // Eigene Rollen anlegen/ändern (Abo-Feature custom_roles); sonst nur ansehen und zuweisen
  canCustomize: boolean;
  // Deep-Link ?role=<id>: diese Rolle beim Laden im Editor öffnen (unbekannte IDs: nichts)
  initialRoleId?: string | null;
};

// Ausdrücklich gewählte Reichweite je Recht mit Reichweite
type ScopeMap = Partial<Record<PermissionKey, PermissionScope>>;

type RoleForm = {
  id?: string;
  name: string;
  description: string;
  // Explizit gewählte Berechtigungen; Implikationen setzt das Formular selbst.
  selected: Set<PermissionKey>;
  // Ausdrücklich gewählte Reichweiten (Migration 0195); implizierte Rechte erben sonst.
  scopes: ScopeMap;
  systemKey: RoleRead["system_key"];
  locked: boolean;
  // MFA für alle Konten mit dieser Rolle (Migration 0192)
  requireMfa: boolean;
};

const IMPLIED_BY = new Map<PermissionKey, PermissionKey[]>();
for (const permission of PERMISSIONS) {
  for (const implied of expandPermissions(permission.implies)) {
    IMPLIED_BY.set(implied, [...(IMPLIED_BY.get(implied) ?? []), permission.key]);
  }
}

function RoleBadge({ role }: { role: RoleRead }) {
  const t = useTranslations("roles");
  if (role.locked) return <Badge variant="info">{t("badges.locked")}</Badge>;
  if (role.system_key) return <Badge variant="neutral">{t("badges.standard")}</Badge>;
  return null;
}

function emptyForm(): RoleForm {
  return { name: "", description: "", selected: new Set(), scopes: {}, systemKey: null, locked: false, requireMfa: false };
}

/** Ausdrückliche Reichweiten für das Formular: die der gewählten Rechte, dazu die eines
 * implizierten Rechts nur, wo sie von der geerbten abweicht (sonst ginge z. B. «Abgaben ansehen:
 * alle» neben «Abgaben prüfen: nur zugewiesene» beim Öffnen verloren). */
function explicitScopes(selected: Set<PermissionKey>, stored: RoleRead["scopes"]): ScopeMap {
  const scopes: ScopeMap = {};
  for (const [key, value] of Object.entries(stored ?? {})) {
    if (selected.has(key as PermissionKey)) scopes[key as PermissionKey] = value;
  }
  const inherited = resolveScopes(selected, scopes);
  for (const [key, value] of Object.entries(stored ?? {})) {
    if (inherited.get(key as PermissionKey) !== value) scopes[key as PermissionKey] = value;
  }
  return scopes;
}

/** Rollen des Mandanten: anlegen, benennen, Berechtigungen zuordnen, löschen. Die Bereiche sind
 * nur Anzeige-Kategorien (permissions/catalog.json), keine eigenen Objekte. */
export function RoleManagement({ initialRoles, actorPermissions, actorAssignedOnly = [], enabledFeatures, canCustomize, initialRoleId = null }: Props) {
  const t = useTranslations("roles");
  const tNav = useTranslations("nav");
  const tUsers = useTranslations("users");
  const tSecurity = useTranslations("security");
  const showToast = useToast();
  const confirm = useConfirm();
  const [roles, setRoles] = useState(initialRoles);
  const [form, setForm] = useState<RoleForm | null>(null);
  const [saving, setSaving] = useState(false);
  const own = useMemo(() => new Set(actorPermissions), [actorPermissions]);
  const ownAssignedOnly = useMemo(() => new Set(actorAssignedOnly), [actorAssignedOnly]);

  const effective = form ? expandPermissions(form.selected) : new Set<PermissionKey>();
  const scopes = form ? resolveScopes(form.selected, form.scopes) : new Map<PermissionKey, PermissionScope>();
  // Keine Rechteausweitung, auch nicht über die Reichweite (Backend: role_service._ensure_subset)
  const exceedsOwn = form
    ? [...effective].some((key) => !own.has(key) || (ownAssignedOnly.has(key) && scopes.get(key) === "all"))
    : false;
  const nameMissing = !!form && !form.systemKey && form.name.trim() === "";

  function openRole(role: RoleRead) {
    const selected = minimalPermissions(role.permissions);
    setForm({
      id: role.id,
      name: role.name ?? "",
      description: role.description ?? "",
      selected,
      scopes: explicitScopes(selected, role.scopes),
      systemKey: role.system_key,
      locked: role.locked || !canCustomize,
      requireMfa: Boolean(role.require_mfa),
    });
  }

  const openedDeepLink = useRef<string | null>(null);
  useEffect(() => {
    if (!initialRoleId || openedDeepLink.current === initialRoleId) return;
    openedDeepLink.current = initialRoleId;
    const role = roles.find((item) => item.id === initialRoleId);
    if (role) openRole(role);
    // Nur beim Laden bzw. bei geändertem Parameter, nicht bei jeder Änderung der Rollenliste
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRoleId]);

  function toggle(key: PermissionKey, checked: boolean) {
    setForm((current) => {
      if (!current) return current;
      const selected = new Set(current.selected);
      if (checked) selected.add(key);
      else selected.delete(key);
      // Wer ein Recht selbst nur für zugewiesene hat, vergibt es standardmässig ebenso
      const scopes = checked && SCOPED_PERMISSIONS.has(key) && ownAssignedOnly.has(key) && !current.scopes[key]
        ? { ...current.scopes, [key]: "assigned" as PermissionScope }
        : current.scopes;
      return { ...current, selected: minimalPermissions(selected), scopes };
    });
  }

  function setScope(key: PermissionKey, scope: PermissionScope) {
    setForm((current) => (current ? { ...current, scopes: { ...current.scopes, [key]: scope } } : current));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || form.locked || nameMissing || saving) return;
    setSaving(true);
    const body = JSON.stringify({
      name: form.name.trim(),
      description: form.description.trim() || null,
      permissions: [...form.selected],
      // Aufgelöste Reichweite aller Rechte mit Reichweite der Rolle (eindeutig, auch für implizierte)
      scopes: Object.fromEntries(scopes),
      require_mfa: form.requireMfa,
    });
    try {
      const saved = form.id
        ? await browserApiFetch<RoleRead>(`/api/roles/${form.id}`, { method: "PATCH", body })
        : await browserApiFetch<RoleRead>("/api/roles", { method: "POST", body });
      setRoles((current) => (form.id ? current.map((role) => (role.id === saved.id ? saved : role)) : [...current, saved]));
      setForm(null);
      showToast(form.id ? t("toasts.saved") : t("toasts.created"), "success");
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("toasts.saveFailed")), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(role: RoleRead) {
    const ok = await confirm({ message: t("deleteConfirm", { name: roleName(role, tNav) }), tone: "danger", confirmLabel: t("delete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/roles/${role.id}`, { method: "DELETE" });
      setRoles((current) => current.filter((item) => item.id !== role.id));
      showToast(t("toasts.deleted"), "success");
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("toasts.deleteFailed")), "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageHint")}</p>
        </div>
        {canCustomize ? (
          <button type="button" className="button-primary" onClick={() => setForm(emptyForm())}>
            {t("newRole")}
          </button>
        ) : null}
      </div>

      <DataTable
        className="data-table-lg"
        columns={[t("columns.name"), t("columns.permissions"), t("columns.users"), t("columns.actions")]}
        emptyMessage={t("empty")}
      >
        {roles.map((role) => (
          <tr key={role.id} className="table-row-clickable" onClick={() => openRole(role)}>
            <td>
              <span className="roles-table-name">
                <strong>{roleName(role, tNav)}</strong>
                <RoleBadge role={role} />
                {roleNeedsMfa(role) ? <Badge variant="warning">{t("badges.mfa")}</Badge> : null}
              </span>
              <span className="field-help">{role.description ?? (role.system_key ? tUsers(`roleDescriptions.${role.system_key}`) : "")}</span>
            </td>
            <td>{t("permissionCount", { count: role.permissions.length })}</td>
            <td>{role.user_count}</td>
            <td onClick={(event) => event.stopPropagation()}>
              <ActionMenu
                items={[
                  { label: role.locked || !canCustomize ? t("view") : t("edit"), onClick: () => openRole(role) },
                  ...(role.system_key ? [] : [{ label: t("delete"), onClick: () => void remove(role), danger: true }]),
                ]}
              />
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id ? (form.locked ? t("viewTitle") : t("editTitle")) : t("createTitle")}
        description={t("modalDescription")}
        size="wide"
      >
        {form ? (
          <ModalSaveForm className="grid" onSubmit={save}>
            {form.locked ? <StatusBanner tone="neutral" message={t("lockedHint")} /> : null}
            {!form.locked && exceedsOwn ? <StatusBanner tone="error" message={t("exceedsOwn")} /> : null}
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("fields.name")}</span>
                <input
                  value={form.name}
                  disabled={form.locked}
                  placeholder={form.systemKey ? tNav(`roles.${form.systemKey}`) : undefined}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                />
                {form.systemKey && !form.locked ? <span className="field-help">{t("fields.nameHelpSystem")}</span> : null}
              </label>
              <label className="field-stack">
                <span className="field-label">{t("fields.description")}</span>
                <input value={form.description} disabled={form.locked} onChange={(event) => setForm({ ...form, description: event.target.value })} />
              </label>
            </div>

            <label className="profile-toggle">
              <span className="profile-toggle-text">
                <span>{t("fields.requireMfa")}</span>
                <span className="field-help">{t("fields.requireMfaHelp")}</span>
              </span>
              <input type="checkbox" role="switch" checked={form.requireMfa} disabled={form.locked} onChange={(event) => setForm({ ...form, requireMfa: event.target.checked })} />
              <span className="album-picker-switch-track" aria-hidden="true" />
            </label>

            <div className="field-stack">
              <span className="field-label">
                {t("fields.permissions")}{" "}
                <HelpPopover topic={t("fields.permissions")} docs={{ page: "rollen", anchor: "berechtigungen" }}>{t("permissionsHelp")}</HelpPopover>
              </span>
              <div className="roles-permission-areas">
                {PERMISSION_AREAS.map((area) => (
                  <fieldset key={area} className="roles-permission-area">
                    <legend className="roles-area-title">{t(`areas.${area}`)}</legend>
                    {PERMISSIONS.filter((permission) => permission.area === area).map((permission) => {
                      const implied = !form.selected.has(permission.key) && effective.has(permission.key);
                      const checked = form.locked || effective.has(permission.key);
                      const disabled = form.locked || implied || (!checked && !own.has(permission.key));
                      const impliers = (IMPLIED_BY.get(permission.key) ?? []).filter((key) => form.selected.has(key));
                      const scoped = SCOPED_PERMISSIONS.has(permission.key) && checked;
                      // Ein implizierendes Recht mit «alle» lässt sich hier nicht einschränken
                      const scopeFixed = (IMPLIED_BY.get(permission.key) ?? []).some(
                        (key) => effective.has(key) && (!SCOPED_PERMISSIONS.has(key) || scopes.get(key) === "all"),
                      );
                      return (
                        <div key={permission.key} className="roles-permission-entry">
                        <label className="roles-permission-option">
                          <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => toggle(permission.key, event.target.checked)} />
                          <span className="roles-checklist-text">
                            <span className="roles-checklist-name">
                              {t(`permissions.${permission.key}.label`)}
                              {permission.requiresMfa ? <Badge variant="warning">{t("badges.mfa")}</Badge> : null}
                              {permission.feature && !enabledFeatures.includes(permission.feature) ? <Badge variant="neutral">{t("featureMissing")}</Badge> : null}
                            </span>
                            <span className="field-help">{t(`permissions.${permission.key}.description`)}</span>
                            {!form.locked && !checked && !own.has(permission.key) ? <span className="field-help">{t("notOwnPermission")}</span> : null}
                            {implied && impliers.length > 0 ? (
                              <span className="field-help">{t("impliedBy", { permissions: impliers.map((key) => t(`permissions.${key}.label`)).join(", ") })}</span>
                            ) : null}
                          </span>
                        </label>
                        {scoped ? (
                          <label className="field-stack roles-scope-field">
                            <span className="field-label">{t("scopes.label")}</span>
                            <Select
                              value={scopes.get(permission.key) ?? "all"}
                              disabled={form.locked || scopeFixed}
                              onChange={(event) => setScope(permission.key, event.target.value as PermissionScope)}
                            >
                              <option value="all" disabled={ownAssignedOnly.has(permission.key)}>{t("scopes.all")}</option>
                              <option value="assigned">{t("scopes.assigned")}</option>
                            </Select>
                            {scopeFixed ? <span className="field-help">{t("scopes.fixedHelp")}</span> : null}
                          </label>
                        ) : null}
                        </div>
                      );
                    })}
                  </fieldset>
                ))}
              </div>
            </div>

            <div className="modal-actions">
              {!form.locked && nameMissing ? <span className="field-help">{t("nameMissing")}</span> : null}
              <button type="button" className="button-ghost" onClick={() => setForm(null)}>
                {form.locked ? t("close") : t("cancel")}
              </button>
              {form.locked ? null : (
                <button data-modal-save type="submit" className="button-primary" disabled={nameMissing || exceedsOwn || saving}>
                  {t("save")}
                </button>
              )}
            </div>
          </ModalSaveForm>
        ) : null}
      </Modal>
    </div>
  );
}
