"use client";

import { FormEvent, useState } from "react";

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
      toast(error instanceof Error ? error.message : "Link konnte nicht erstellt werden.", "error");
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
    <Modal open={open} title="Link teilen" onClose={handleClose}>
      {created ? (
        <div className="grid">
          <p className="muted">Jede Person mit diesem Link kann die Dateien ohne Anmeldung herunterladen.</p>
          <label className="field-stack">
            <span className="field-label">Freigabe-Link</span>
            <CopyField label="Freigabe-Link" value={`${window.location.origin}${created.url}`} />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-primary" onClick={handleClose}>Fertig</button>
          </div>
        </div>
      ) : (
        <ModalSaveForm className="grid" onSubmit={create}>
          <label className="field-stack">
            <span className="field-label">Name</span>
            <input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field-stack">
            <span className="field-label">Ablaufdatum</span>
            <DateInput value={expiresAt} onChange={setExpiresAt} />
            <span className="field-help">Optional – ohne Ablaufdatum bleibt der Link aktiv, bis er widerrufen wird.</span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={handleClose}>Abbrechen</button>
            <button className="button-primary" data-modal-save type="submit" disabled={busy || !name.trim()}>
              {busy ? "Wird erstellt…" : "Link erstellen"}
            </button>
          </div>
        </ModalSaveForm>
      )}
    </Modal>
  );
}
