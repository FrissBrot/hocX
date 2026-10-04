"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { CopyField } from "@/components/ui/copy-field";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ShareLink } from "@/types/api";

type MetadataChoice = { share_location: boolean; share_capture_date: boolean; share_camera: boolean };
type MetadataKey = keyof MetadataChoice;

// Vorgabe wie im Backend (ShareLinkCreate): Datum ja, Standort und Kamera/Gerät nein.
const DEFAULT_METADATA: MetadataChoice = { share_location: false, share_capture_date: true, share_camera: false };
const METADATA_OPTIONS: { key: MetadataKey; label: "metadataLocation" | "metadataCaptureDate" | "metadataCamera"; help: "metadataLocationHelp" | "metadataCaptureDateHelp" | "metadataCameraHelp" }[] = [
  { key: "share_location", label: "metadataLocation", help: "metadataLocationHelp" },
  { key: "share_capture_date", label: "metadataCaptureDate", help: "metadataCaptureDateHelp" },
  { key: "share_camera", label: "metadataCamera", help: "metadataCameraHelp" },
];

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
  const [metadata, setMetadata] = useState<MetadataChoice>(DEFAULT_METADATA);
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
          ...metadata,
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
    setMetadata(DEFAULT_METADATA);
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
          <fieldset className="share-metadata-fieldset">
            <legend className="field-label">{t("createModal.metadataLegend")}</legend>
            {METADATA_OPTIONS.map((option) => (
              <label key={option.key} className="share-metadata-option">
                <input
                  type="checkbox"
                  role="switch"
                  checked={metadata[option.key]}
                  onChange={(event) => setMetadata((current) => ({ ...current, [option.key]: event.target.checked }))}
                />
                <span className="album-picker-switch-track" aria-hidden="true" />
                <span className="share-metadata-text">
                  <span>{t(`createModal.${option.label}`)}</span>
                  <span className="field-help">{t(`createModal.${option.help}`)}</span>
                </span>
              </label>
            ))}
            <span className="field-help">{t("createModal.metadataHelp")}</span>
          </fieldset>
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
