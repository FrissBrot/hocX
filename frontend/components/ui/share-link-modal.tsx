"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { CopyField } from "@/components/ui/copy-field";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ShareLink } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  /** Genau eines von fileIds/albumId wird gesetzt - feste Auswahl vs. "live" Album-Link. */
  fileIds?: string[];
  albumId?: string;
  defaultName?: string;
  onCreated?: () => void;
};

export function ShareLinkModal({ open, onClose, fileIds, albumId, defaultName = "", onCreated }: Props) {
  const t = useTranslations("sharedLinks");
  const tCommon = useTranslations("common");
  const toast = useToast();
  const [name, setName] = useState(defaultName);
  const [expiresAt, setExpiresAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ShareLink | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    try {
      const link = await browserApiFetch<ShareLink>("/api/share-links", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          expires_at: expiresAt || null,
          file_ids: albumId ? null : fileIds,
          album_id: albumId ?? null,
        }),
      });
      if (link) {
        setCreated(link);
        onCreated?.();
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : t("createModal.createFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  function handleClose() {
    setName(defaultName);
    setExpiresAt("");
    setCreated(null);
    onClose();
  }

  return (
    <Modal open={open} title={t("createModal.title")} onClose={handleClose}>
      {created ? (
        <div className="grid">
          <p className="muted">{t("createModal.createdIntro")}</p>
          <label className="field-stack">
            <span className="field-label">{t("createModal.shareLinkLabel")}</span>
            <CopyField label={t("createModal.shareLinkLabel")} value={`${window.location.origin}${created.url}`} />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-primary" onClick={handleClose}>{t("createModal.doneButton")}</button>
          </div>
        </div>
      ) : (
        <ModalSaveForm className="grid" onSubmit={create}>
          <label className="field-stack">
            <span className="field-label">{t("createModal.nameLabel")}</span>
            <input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("createModal.expiryLabel")}</span>
            <DateInput value={expiresAt} onChange={setExpiresAt} />
            <span className="field-help">{t("createModal.expiryHelp")}</span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={handleClose}>{tCommon("cancel")}</button>
            <button className="button-primary" data-modal-save type="submit" disabled={busy || !name.trim()}>
              {busy ? t("createModal.creatingEllipsis") : t("createModal.createButton")}
            </button>
          </div>
        </ModalSaveForm>
      )}
    </Modal>
  );
}
