"use client";

// Aufräumen (Gestaltung auf Abruf): nicht verwendete eigene Vorlagen gesammelt archivieren.
// Archivieren ist umkehrbar; mitgelieferte Vorlagen bleiben ohnehin im Katalog.

import { useState } from "react";
import { useTranslations } from "next-intl";

import { templateDisplayName } from "@/components/documents/studio-labels";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DocumentTemplateInfo, studioApi } from "@/lib/documents/api";

type Props = { open: boolean; onClose: () => void; candidates: DocumentTemplateInfo[]; onDone: () => void };

export function CleanupModal({ open, onClose, candidates, onDone }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [selected, setSelected] = useState<Set<string>>(() => new Set(candidates.map((item) => item.id)));
  const [busy, setBusy] = useState(false);

  function toggle(id: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function archive() {
    setBusy(true);
    try {
      const result = await studioApi.archiveUnused([...selected]);
      toast(t("cleanup.done", { count: result.archived }), "success");
      onDone();
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
      setBusy(false);
    }
  }

  return (
    <Modal
      className="studio-modal"
      open={open}
      onClose={onClose}
      title={t("cleanup.title")}
      description={t("cleanup.description")}
      footer={
        <>
          <span className="field-help">{t("cleanup.footnote")}</span>
          <div className="modal-footer-actions">
            <button type="button" className="button-ghost" onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button type="button" className="button-primary" disabled={selected.size === 0 || busy} onClick={() => void archive()}>
              {t("cleanup.submit", { count: selected.size })}
            </button>
          </div>
        </>
      }
    >
      <ul className="studio-cleanup-list">
        {candidates.map((item) => (
          <li key={item.id}>
            <label className="studio-cleanup-item">
              <input type="checkbox" checked={selected.has(item.id)} onChange={(event) => toggle(item.id, event.target.checked)} />
              <span className="studio-cleanup-name">{templateDisplayName(t, item)}</span>
              <span className="field-help">{t(`docType.${item.document_type}`)}</span>
            </label>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
