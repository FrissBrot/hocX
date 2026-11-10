"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";

export type AdminSystemDocumentTemplate = {
  id: string;
  system_key: string | null;
  name: string;
  description: string | null;
  document_type: string;
  variant: string | null;
  status: "active" | "archived";
  is_platform_default: boolean;
  revision: number | null;
  published_at: string | null;
  copies: number;
  exports: number;
};

type StatusFilter = "active" | "archived" | "all";

// Seite /admin/document-templates: mitgelieferte Systemvorlagen des Document Studio. Ihr Inhalt
// kommt aus dem Code (backend/app/documents/system_templates.py); hier wird nur gesteuert, welche
// Mandanten angeboten werden und welche je Dokumentart der Plattform-Standard ist.
export function AdminSystemDocumentTemplates({ initialTemplates, canWrite }: { initialTemplates: AdminSystemDocumentTemplate[]; canWrite: boolean }) {
  const t = useTranslations("admin.documentTemplates");
  const tDocType = useTranslations("documentStudio.docType");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [templates, setTemplates] = useState(initialTemplates);
  const [filter, setFilter] = useState<StatusFilter>("active");
  const [busyId, setBusyId] = useState<string | null>(null);

  const visible = templates.filter((row) => filter === "all" || row.status === filter);
  const docTypeLabel = (type: string) => (tDocType.has(type) ? tDocType(type) : type);

  async function reload() {
    setTemplates(await browserApiFetch<AdminSystemDocumentTemplate[]>("/api/admin/document-templates"));
  }

  async function run(row: AdminSystemDocumentTemplate, path: string, body: unknown, successKey: string) {
    setBusyId(row.id);
    try {
      await browserApiFetch<AdminSystemDocumentTemplate>(`/api/admin/document-templates/${row.id}/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      // Ein neuer Standard nimmt dem bisherigen die Markierung - deshalb die ganze Liste neu laden.
      await reload();
      showToast(t(successKey, { name: row.name }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("actionFailed"), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function archive(row: AdminSystemDocumentTemplate) {
    const ok = await confirm({ message: t("archiveConfirm", { name: row.name, copies: row.copies }), tone: "danger", confirmLabel: t("actions.archive") });
    if (ok) await run(row, "archive", { archived: true }, "archived");
  }

  function actions(row: AdminSystemDocumentTemplate) {
    if (row.status === "archived") {
      return [{ label: t("actions.reactivate"), onClick: () => void run(row, "archive", { archived: false }, "reactivated") }];
    }
    const items = [];
    if (!row.is_platform_default) {
      items.push({ label: t("actions.makeDefault"), onClick: () => void run(row, "platform-default", {}, "madeDefault") });
      items.push({ label: t("actions.archive"), onClick: () => void archive(row), danger: true });
    }
    return items;
  }

  return (
    <div className="grid">
      <DataToolbar title={t("title")} description={t("description")} />
      <FilterTabs
        options={(["active", "archived", "all"] as const).map((value) => ({
          value,
          label: t(`filter.${value}`),
          count: value === "all" ? templates.length : templates.filter((row) => row.status === value).length,
        }))}
        value={filter}
        onChange={setFilter}
      />
      <DataTable
        columns={[t("columns.template"), t("columns.documentType"), t("columns.revision"), t("columns.usage"), t("columns.status"), t("columns.actions")]}
        emptyMessage={t("empty")}
      >
        {visible.map((row) => {
          const rowActions = canWrite ? actions(row) : [];
          return (
            <tr key={row.id}>
              <td>
                <strong>{row.name}</strong>
                {row.description ? <div className="muted">{row.description}</div> : null}
              </td>
              <td>
                {docTypeLabel(row.document_type)}
                {row.variant ? <div className="muted">{row.variant}</div> : null}
              </td>
              <td className="muted">
                {row.revision != null ? t("revision", { revision: row.revision }) : t("unpublished")}
                {row.published_at ? <div>{formatDateTime(row.published_at, locale)}</div> : null}
              </td>
              <td className="muted">{t("usage", { copies: row.copies, exports: row.exports })}</td>
              <td>
                <div className="status-row">
                  {row.is_platform_default ? <Badge variant="success" dot>{t("platformDefault")}</Badge> : null}
                  <Badge variant={row.status === "active" ? "info" : "neutral"}>{t(`status.${row.status}`)}</Badge>
                </div>
              </td>
              <td>{rowActions.length === 0 || busyId === row.id ? null : <ActionMenu items={rowActions} />}</td>
            </tr>
          );
        })}
      </DataTable>
    </div>
  );
}
