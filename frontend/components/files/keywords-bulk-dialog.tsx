"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { KeywordInput } from "@/components/ui/keyword-input";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";

export type KeywordCount = { keyword: string; count: number };

/** Obergrenze wie im Backend (file_keywords.MAX_BULK_FILES). */
export const MAX_KEYWORD_BULK = 200;

/**
 * Mehrfachbearbeitung der Keywords (Fotos und Ablage): neue Keywords hinzufügen und vorhandene
 * der Auswahl zum Entfernen markieren. Speichert mit «Übernehmen» in einem Aufruf.
 */
export function KeywordsBulkDialog({
  open,
  fileIds,
  onClose,
  onDone,
}: {
  open: boolean;
  fileIds: string[];
  onClose: () => void;
  onDone?: () => void;
}) {
  const t = useTranslations("files.keywords.bulk");
  const showToast = useToast();
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([]);
  const [existing, setExisting] = useState<KeywordCount[] | null>(null);
  const [busy, setBusy] = useState(false);
  const tooMany = fileIds.length > MAX_KEYWORD_BULK;
  const idsKey = fileIds.join(",");

  useEffect(() => {
    if (!open) return;
    setAdd([]);
    setRemove([]);
    setExisting(null);
    if (fileIds.length === 0 || tooMany) {
      setExisting([]);
      return;
    }
    let cancelled = false;
    browserApiFetch<KeywordCount[]>("/api/files/keywords-summary", { method: "POST", body: JSON.stringify({ file_ids: fileIds }) })
      .then((data) => { if (!cancelled) setExisting(data ?? []); })
      .catch(() => { if (!cancelled) setExisting([]); });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, idsKey]);

  function toggleRemove(keyword: string) {
    setRemove((current) => (current.includes(keyword) ? current.filter((entry) => entry !== keyword) : [...current, keyword]));
  }

  async function apply() {
    if (busy || (add.length === 0 && remove.length === 0)) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<{ updated: number }>("/api/files/bulk-keywords", {
        method: "POST",
        body: JSON.stringify({ file_ids: fileIds, add, remove }),
      });
      showToast(t("doneToast", { count: result?.updated ?? 0 }), "success");
      onDone?.();
      onClose();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("error"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={t("title", { count: fileIds.length })} description={t("description")} onClose={onClose}>
      <div className="section-stack">
        {tooMany ? <p className="muted">{t("tooMany", { max: MAX_KEYWORD_BULK })}</p> : null}
        <div className="field-stack">
          <span className="field-label">{t("addLabel")}</span>
          <KeywordInput value={add} onChange={setAdd} label={t("addLabel")} placeholder={t("addPlaceholder")} readOnly={tooMany} />
        </div>
        <div className="field-stack">
          <span className="field-label">{t("removeLabel")}</span>
          {existing === null ? (
            <span className="muted">{t("loading")}</span>
          ) : existing.length === 0 ? (
            <span className="muted">{t("noneInSelection")}</span>
          ) : (
            <div className="keyword-bulk-existing" role="group" aria-label={t("removeLabel")}>
              {existing.map((entry) => (
                <button
                  key={entry.keyword}
                  type="button"
                  className="keyword-bulk-toggle"
                  aria-pressed={remove.includes(entry.keyword)}
                  onClick={() => toggleRemove(entry.keyword)}
                  title={remove.includes(entry.keyword) ? t("keep") : t("markRemove")}
                >
                  {entry.keyword}
                  <span className="keyword-bulk-count">{t("countSuffix", { count: entry.count })}</span>
                </button>
              ))}
            </div>
          )}
          <span className="field-help">{t("removeHelp")}</span>
        </div>
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose} disabled={busy}>
          {t("cancel")}
        </button>
        <button type="button" className="button-primary" onClick={() => void apply()} disabled={busy || tooMany || (add.length === 0 && remove.length === 0)}>
          {t("apply")}
        </button>
      </div>
    </Modal>
  );
}
