"use client";

import { ReactNode, useCallback, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { browserApiFetch } from "@/lib/api/client";

export type DeletionPreviewFile = {
  id: string;
  name: string;
  mime_type: string | null;
  is_image: boolean;
  thumbnail_url: string | null;
  created_at: string | null;
  group: "protocol_image" | "submission" | "gallery";
  used_elsewhere: boolean;
  label: string | null;
};

export type DeletionResult = { deleted_files: number; kept_files: number; untouched_files: number };

const GROUP_ORDER: DeletionPreviewFile["group"][] = ["protocol_image", "submission", "gallery"];

type ModalProps = {
  open: boolean;
  title: string;
  message: string;
  files: DeletionPreviewFile[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: (deleteFileIds: string[]) => void;
};

// Lösch-Dialog mit Dateiauswahl (Datenschutz-Audit, Paket 2): standardmässig werden alle Dateien
// mitgelöscht, abgewählte wandern mit Herkunfts-Tag in die Galerie. Dateien, die noch anderswo
// verwendet werden, bleiben in jedem Fall und sind nicht wählbar.
export function DeleteWithFilesModal({ open, title, message, files, busy, onCancel, onConfirm }: ModalProps) {
  const t = useTranslations("common.deleteWithFiles");
  const selectable = useMemo(() => files.filter((file) => !file.used_elsewhere), [files]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(selectable.map((file) => file.id)));

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = selectable.length > 0 && selectable.every((file) => selected.has(file.id));
  const keptCount = selectable.length - selectable.filter((file) => selected.has(file.id)).length;

  return (
    <Modal open={open} title={title} onClose={onCancel} size="wide">
      <div className="delete-files">
        <p className="muted">{message}</p>
        <div className="delete-files-toolbar">
          <span className="field-help">{t("selectedCount", { selected: selected.size, total: selectable.length })}</span>
          {selectable.length > 0 ? (
            <button
              type="button"
              className="button-ghost"
              onClick={() => setSelected(allSelected ? new Set() : new Set(selectable.map((file) => file.id)))}
            >
              {allSelected ? t("selectNone") : t("selectAll")}
            </button>
          ) : null}
        </div>
        {GROUP_ORDER.map((group) => {
          const items = files.filter((file) => file.group === group);
          if (items.length === 0) return null;
          return (
            <section key={group} className="delete-files-group">
              <h3 className="delete-files-heading">{t(`groups.${group}`)}</h3>
              <ul className="delete-files-list">
                {items.map((file) => (
                  <li key={file.id}>
                    <label className={`delete-files-item${file.used_elsewhere ? " delete-files-item-locked" : ""}`}>
                      <input
                        type="checkbox"
                        disabled={file.used_elsewhere || busy}
                        checked={!file.used_elsewhere && selected.has(file.id)}
                        onChange={() => toggle(file.id)}
                      />
                      {file.thumbnail_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img className="delete-files-thumb" src={file.thumbnail_url} alt="" loading="lazy" />
                      ) : (
                        <span className="delete-files-thumb delete-files-thumb-empty" aria-hidden="true" />
                      )}
                      <span className="delete-files-text">
                        <span className="delete-files-name">{file.label || file.name}</span>
                        <span className="delete-files-hint">{file.used_elsewhere ? t("usedElsewhere") : file.label ? file.name : null}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        {keptCount > 0 ? <p className="field-help">{t("keptHint", { count: keptCount })}</p> : null}
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onCancel} disabled={busy}>
          {t("cancel")}
        </button>
        <button type="button" className="button-danger" disabled={busy} onClick={() => onConfirm(Array.from(selected))}>
          {t("confirm", { count: selected.size })}
        </button>
      </div>
    </Modal>
  );
}

type UseDeleteOptions = {
  title: string;
  message: string;
  previewUrl: string;
  deleteUrl: string;
};

/**
 * Lädt die Vorschau; ohne Dateien genügt die übliche Rückfrage, sonst öffnet sich der Dialog mit
 * Auswahl. Liefert das Ergebnis oder null (abgebrochen).
 */
export function useDeleteWithFiles(): {
  requestDelete: (options: UseDeleteOptions) => Promise<DeletionResult | null>;
  modal: ReactNode;
} {
  const t = useTranslations("common.deleteWithFiles");
  const confirm = useConfirm();
  const [state, setState] = useState<(UseDeleteOptions & { files: DeletionPreviewFile[] }) | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ resolve: (value: DeletionResult | null) => void; reject: (error: unknown) => void } | null>(null);

  const requestDelete = useCallback(
    async (options: UseDeleteOptions) => {
      const preview = await browserApiFetch<{ files: DeletionPreviewFile[] }>(options.previewUrl);
      if (preview.files.length === 0) {
        const ok = await confirm({ title: options.title, message: options.message, tone: "danger", confirmLabel: t("confirmPlain") });
        if (!ok) return null;
        return browserApiFetch<DeletionResult>(options.deleteUrl, { method: "POST", body: JSON.stringify({ delete_file_ids: [] }) });
      }
      return new Promise<DeletionResult | null>((resolve, reject) => {
        pending.current = { resolve, reject };
        setState({ ...options, files: preview.files });
      });
    },
    [confirm, t],
  );

  const close = (value: DeletionResult | null) => {
    pending.current?.resolve(value);
    pending.current = null;
    setState(null);
  };

  const modal = state ? (
    <DeleteWithFilesModal
      key={state.deleteUrl}
      open
      title={state.title}
      message={state.message}
      files={state.files}
      busy={busy}
      onCancel={() => close(null)}
      onConfirm={async (ids) => {
        setBusy(true);
        try {
          const result = await browserApiFetch<DeletionResult>(state.deleteUrl, { method: "POST", body: JSON.stringify({ delete_file_ids: ids }) });
          close(result);
        } catch (error) {
          pending.current?.reject(error);
          pending.current = null;
          setState(null);
        } finally {
          setBusy(false);
        }
      }}
    />
  ) : null;

  return { requestDelete, modal };
}
