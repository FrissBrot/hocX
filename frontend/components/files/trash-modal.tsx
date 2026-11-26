"use client";

// Papierkorb für Dateien und Fotos (Migration 0199, backend services/file_trash_service.py).
// Erreichbar von der Dateien- und der Fotos-Seite; zeigt nur, was das Konto löschen darf
// (files.manage bzw. photos.manage - das filtert das Backend).
import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { FileTrashActionResult, FileTrashItem, FileTrashList } from "@/types/api";
import { RetryImage } from "@/components/ui/retry-image";

type Props = {
  open: boolean;
  onClose: () => void;
  /** Nach Wiederherstellen: die Liste der Seite neu laden. */
  onRestored?: (ids: string[]) => void;
};

export function TrashModal({ open, onClose, onRestored }: Props) {
  const t = useTranslations("files.trash");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [data, setData] = useState<FileTrashList | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await browserApiFetch<FileTrashList>("/api/files/trash"));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("loadError"), "error");
    } finally {
      setLoading(false);
    }
  }, [showToast, t]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  async function run(path: string, ids: string[]): Promise<FileTrashActionResult | null> {
    setBusy(true);
    try {
      return await browserApiFetch<FileTrashActionResult>(path, { method: "POST", body: JSON.stringify({ file_ids: ids }) });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("actionError"), "error");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function restore(item: FileTrashItem) {
    const result = await run("/api/files/trash/restore", [item.id]);
    if (!result) return;
    if (result.file_ids.length > 0) {
      showToast(t("restoredToast", { name: item.original_name }), "success");
      onRestored?.(result.file_ids);
    }
    if (result.errors.length > 0) showToast(result.errors.join(" · "), "error");
    await load();
  }

  async function purge(item: FileTrashItem) {
    const ok = await confirm({
      tone: "danger",
      message: t("purgeConfirm", { name: item.original_name }),
      confirmLabel: t("purgeLabel"),
    });
    if (!ok) return;
    const result = await run("/api/files/trash/purge", [item.id]);
    if (!result) return;
    if (result.file_ids.length > 0) showToast(t("purgedToast", { name: item.original_name }), "success");
    if (result.errors.length > 0) showToast(result.errors.join(" · "), "error");
    await load();
  }

  async function emptyTrash() {
    const count = data?.items.length ?? 0;
    if (count === 0) return;
    const ok = await confirm({ tone: "danger", message: t("emptyConfirm", { count }), confirmLabel: t("emptyLabel") });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<{ purged: number }>("/api/files/trash/empty", { method: "POST" });
      showToast(t("emptiedToast", { count: result?.purged ?? 0 }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("actionError"), "error");
    } finally {
      setBusy(false);
    }
    await load();
  }

  const items = data?.items ?? [];

  return (
    <Modal open={open} title={t("title")} onClose={onClose} size="wide">
      <div className="grid trash-modal">
        <StatusBanner
          tone="neutral"
          message={t("quotaHint", { days: data?.retention_days ?? 30, size: formatFileSize(data?.total_bytes ?? 0, locale) })}
        />
        <DataTable
          columns={[
            { key: "name", label: t("columns.name") },
            { key: "deleted", label: t("columns.deleted") },
            { key: "remaining", label: t("columns.remaining") },
            { key: "actions", label: t("columns.actions") },
          ]}
          emptyMessage={loading ? t("loading") : t("empty")}
        >
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <div className="trash-name">
                  {item.thumbnail_url ? (
                    <RetryImage className="trash-thumb" src={`${browserApiBaseUrl}${item.thumbnail_url}`} alt="" loading="lazy" />
                  ) : null}
                  <div>
                    <div>{item.original_name}</div>
                    <div className="muted">{formatFileSize(item.file_size_bytes, locale)}</div>
                  </div>
                </div>
              </td>
              <td>
                <div>{formatDateTime(item.deleted_at, locale)}</div>
                <div className="muted">{item.deleted_by_name ? t("deletedBy", { name: item.deleted_by_name }) : t("deletedByUnknown")}</div>
              </td>
              <td>{t("daysLeft", { count: item.days_left })}</td>
              <td>
                <div className="trash-actions">
                  <button type="button" className="button-secondary" disabled={busy} onClick={() => void restore(item)}>
                    {t("restore")}
                  </button>
                  <button type="button" className="button-danger" disabled={busy} onClick={() => void purge(item)}>
                    {t("purgeLabel")}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </DataTable>
        <div className="modal-actions">
          <button type="button" className="button-danger" disabled={busy || items.length === 0} onClick={() => void emptyTrash()}>
            {t("emptyLabel")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
