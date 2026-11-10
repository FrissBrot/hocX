"use client";

import { FormEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { expandPermissions, minimalPermissions, roleName } from "@/lib/permissions";
import { PERMISSION_AREAS, PERMISSIONS, type PermissionKey } from "@/lib/permissions.generated";
import type { RoleRead } from "@/types/api";

type Props = {
  initialRoles: RoleRead[];
  // Eigene effektive Berechtigungen: nur diese lassen sich vergeben (keine Rechteausweitung).
  actorPermissions: string[];
  enabledFeatures: string[];
  // Eigene Rollen anlegen/ändern (Abo-Feature custom_roles); sonst nur ansehen und zuweisen
  canCustomize: boolean;
};

type RoleForm = {
  id?: string;
  name: string;
  description: string;
  // Explizit gewählte Berechtigungen; Implikationen setzt das Formular selbst.
  selected: Set<PermissionKey>;
  systemKey: RoleRead["system_key"];
  locked: boolean;
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
  return { name: "", description: "", selected: new Set(), systemKey: null, locked: false };
}

/** Rollen des Mandanten: anlegen, benennen, Berechtigungen zuordnen, löschen. Die Bereiche sind
 * nur Anzeige-Kategorien (permissions/catalog.json), keine eigenen Objekte. */
export function RoleManagement({ initialRoles, actorPermissions, enabledFeatures, canCustomize }: Props) {
  const t = useTranslations("roles");
  const tNav = useTranslations("nav");
  const tUsers = useTranslations("users");
  const showToast = useToast();
  const confirm = useConfirm();
  const [roles, setRoles] = useState(initialRoles);
  const [form, setForm] = useState<RoleForm | null>(null);
  const [saving, setSaving] = useState(false);
  const own = useMemo(() => new Set(actorPermissions), [actorPermissions]);

  const effective = form ? expandPermissions(form.selected) : new Set<PermissionKey>();
  const exceedsOwn = form ? [...effective].some((key) => !own.has(key)) : false;
  const nameMissing = !!form && !form.systemKey && form.name.trim() === "";

  function openRole(role: RoleRead) {
    setForm({
      id: role.id,
      name: role.name ?? "",
      description: role.description ?? "",
      selected: minimalPermissions(role.permissions),
      systemKey: role.system_key,
      locked: role.locked || !canCustomize,
    });
  }

  function toggle(key: PermissionKey, checked: boolean) {
    setForm((current) => {
      if (!current) return current;
      const selected = new Set(current.selected);
      if (checked) selected.add(key);
      else selected.delete(key);
      return { ...current, selected: minimalPermissions(selected) };
    });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || form.locked || nameMissing || saving) return;
    setSaving(true);
    const body = JSON.stringify({
      name: form.name.trim(),
      description: form.description.trim() || null,
      permissions: [...form.selected],
    });
    try {
      const saved = form.id
        ? await browserApiFetch<RoleRead>(`/api/roles/${form.id}`, { method: "PATCH", body })
        : await browserApiFetch<RoleRead>("/api/roles", { method: "POST", body });
      setRoles((current) => (form.id ? current.map((role) => (role.id === saved.id ? saved : role)) : [...current, saved]));
      setForm(null);
      showToast(form.id ? t("toasts.saved") : t("toasts.created"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.saveFailed"), "error");
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
      showToast(error instanceof Error ? error.message : t("toasts.deleteFailed"), "error");
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

            <div className="field-stack">
              <span className="field-label">{t("fields.permissions")}</span>
              <div className="roles-permission-areas">
                {PERMISSION_AREAS.map((area) => (
                  <fieldset key={area} className="roles-permission-area">
                    <legend className="roles-area-title">{t(`areas.${area}`)}</legend>
                    {PERMISSIONS.filter((permission) => permission.area === area).map((permission) => {
                      const implied = !form.selected.has(permission.key) && effective.has(permission.key);
                      const checked = form.locked || effective.has(permission.key);
                      const disabled = form.locked || implied || (!checked && !own.has(permission.key));
                      const impliers = (IMPLIED_BY.get(permission.key) ?? []).filter((key) => form.selected.has(key));
                      return (
                        <label key={permission.key} className="roles-permission-option">
                          <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => toggle(permission.key, event.target.checked)} />
                          <span className="roles-checklist-text">
                            <span className="roles-checklist-name">
                              {t(`permissions.${permission.key}.label`)}
                              {permission.requiresMfa ? <Badge variant="warning">{t("badges.mfa")}</Badge> : null}
                              {permission.feature && !enabledFeatures.includes(permission.feature) ? <Badge variant="neutral">{t("featureMissing")}</Badge> : null}
                            </span>
                            <span className="field-help">{t(`permissions.${permission.key}.description`)}</span>
                            {implied && impliers.length > 0 ? (
                              <span className="field-help">{t("impliedBy", { permissions: impliers.map((key) => t(`permissions.${key}.label`)).join(", ") })}</span>
                            ) : null}
                          </span>
                        </label>
                      );
                    })}
                  </fieldset>
                ))}
              </div>
            </div>

            <div className="modal-actions">
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
