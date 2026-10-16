"use client";

// Wiederverwendbare Komponenten des Mandanten (z. B. ein eigener Briefkopf). Entstehen im
// Designer über «Als Komponente speichern» und werden dort per Verweis eingefügt; Änderungen an
// der Komponente wirken in allen Vorlagen, die sie verwenden.

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, Capabilities, ReusableComponent, studioApi } from "@/lib/documents/api";
import { formatDateTime } from "@/lib/utils/format";

export function ComponentsLibrary({ capabilities }: { capabilities: Capabilities }) {
  const t = useTranslations("documentStudio");
  const locale = useLocale();
  const toast = useToast();
  const confirm = useConfirm();
  const [items, setItems] = useState<ReusableComponent[] | null>(null);
  const [editing, setEditing] = useState<ReusableComponent | null>(null);
  const load = () => void studioApi.components().then(setItems).catch((error) => toast(apiErrorMessage(error, t("components.loadFailed")), "error"));
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("components.title")}</h1>
          <p className="muted">{t("components.description")}</p>
        </div>
      </div>
      <DataTable
        columns={[
          { key: "name", label: t("components.name") },
          { key: "type", label: t("components.type") },
          { key: "updated", label: t("components.updated") },
          { key: "actions", label: t("components.actions") },
        ]}
        emptyMessage={items === null ? t("common.loading") : t("components.empty")}
      >
        {(items ?? []).map((item) => (
          <tr key={item.id}>
            <td>
              <strong>{item.name}</strong>
              {item.description && <div className="field-help">{item.description}</div>}
            </td>
            <td>{t(`nodeType.${item.node.type}`)}</td>
            <td>{formatDateTime(item.updated_at, locale)}</td>
            <td className="studio-row-actions">
              {capabilities.edit_templates && (
                <>
                  <button type="button" className="button-secondary" onClick={() => setEditing(item)}>
                    {t("components.edit")}
                  </button>
                  <button
                    type="button"
                    className="button-danger"
                    onClick={async () => {
                      if (!(await confirm({ message: t("components.deleteConfirm", { name: item.name }), tone: "danger", confirmLabel: t("components.delete") }))) return;
                      try {
                        await studioApi.deleteComponent(item.id);
                        load();
                      } catch (error) {
                        toast(apiErrorMessage(error, t("common.actionFailed")), "error");
                      }
                    }}
                  >
                    {t("components.delete")}
                  </button>
                </>
              )}
            </td>
          </tr>
        ))}
      </DataTable>
      <Modal className="studio-modal" open={!!editing} onClose={() => setEditing(null)} title={t("components.editTitle")}>
        {editing && (
          <>
            <label className="field-stack">
              <span className="field-label">{t("components.name")}</span>
              <input value={editing.name} maxLength={120} onChange={(event) => setEditing({ ...editing, name: event.target.value })} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("components.descriptionLabel")}</span>
              <textarea rows={3} value={editing.description ?? ""} maxLength={600} onChange={(event) => setEditing({ ...editing, description: event.target.value })} />
            </label>
            <p className="field-help">{t("components.editHelp")}</p>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setEditing(null)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="button-primary"
                onClick={async () => {
                  try {
                    await studioApi.updateComponent(editing.id, { name: editing.name, description: editing.description, lock_version: editing.lock_version });
                    setEditing(null);
                    load();
                  } catch (error) {
                    toast(apiErrorMessage(error, t("common.actionFailed")), "error");
                  }
                }}
              >
                {t("common.save")}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
