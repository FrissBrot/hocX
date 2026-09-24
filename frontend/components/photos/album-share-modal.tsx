"use client";

import { FormEvent, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { PhotoAlbum, TenantLookup } from "@/types/api";

const STATUS_LABEL: Record<string, string> = { pending: "Angefragt", accepted: "Aktiv", declined: "Abgelehnt" };
const STATUS_VARIANT: Record<string, BadgeVariant> = { pending: "warning", accepted: "success", declined: "danger" };

export function AlbumShareModal({
  open,
  album,
  onClose,
  onChanged,
}: {
  open: boolean;
  album: PhotoAlbum;
  onClose: () => void;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const toast = useToast();
  const [tenantId, setTenantId] = useState("");
  const [preview, setPreview] = useState<TenantLookup | null>(null);
  const [lookupError, setLookupError] = useState("");
  const [busy, setBusy] = useState(false);

  async function lookup() {
    const trimmed = tenantId.trim();
    setPreview(null);
    setLookupError("");
    if (!trimmed) return;
    try {
      const tenant = await browserApiFetch<TenantLookup>(`/api/tenants/lookup?public_id=${encodeURIComponent(trimmed)}`);
      if (tenant) setPreview(tenant);
      else setLookupError("Kein Mandant mit dieser ID gefunden.");
    } catch {
      setLookupError("Kein Mandant mit dieser ID gefunden.");
    }
  }

  async function invite(event: FormEvent) {
    event.preventDefault();
    if (!preview || busy) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/files/albums/${album.id}/shares`, {
        method: "POST",
        body: JSON.stringify({ target_tenant_public_id: preview.id }),
      });
      toast(`Einladung an ${preview.name} gesendet.`, "success");
      setTenantId("");
      setPreview(null);
      onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Einladung konnte nicht gesendet werden.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(tenantPublicId: string, tenantName: string) {
    const ok = await confirm({ tone: "danger", message: `Freigabe für „${tenantName}“ wirklich beenden?`, confirmLabel: "Beenden" });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/files/albums/${album.id}/shares/${tenantPublicId}`, { method: "DELETE" });
      toast("Freigabe beendet.", "success");
      onChanged();
    } catch {
      toast("Freigabe konnte nicht beendet werden.", "error");
    }
  }

  return (
    <Modal open={open} title="Mit anderem Mandanten teilen" onClose={onClose}>
      <div className="grid">
        <ModalSaveForm className="grid" onSubmit={invite}>
          <label className="field-stack">
            <span className="field-label">Mandanten-ID</span>
            <input
              value={tenantId}
              onChange={(event) => {
                setTenantId(event.target.value);
                setPreview(null);
                setLookupError("");
              }}
              onBlur={() => void lookup()}
              placeholder="Mandanten-ID einfügen"
            />
            <span className="field-help">
              {preview ? `Gefunden: ${preview.name}` : lookupError || "Zu finden in den Mandant-Einstellungen der anderen Organisation."}
            </span>
          </label>
          <div className="modal-actions">
            <button type="submit" className="button-primary" data-modal-save disabled={!preview || busy}>
              {busy ? "Wird eingeladen…" : "Einladen"}
            </button>
          </div>
        </ModalSaveForm>

        {album.shared_with.length > 0 && (
          <div className="section-stack">
            <span className="field-label">Freigaben</span>
            {album.shared_with.map((share) => (
              <div key={share.tenant_public_id} className="record-list-row album-share-row">
                <span className="album-share-row-name">{share.tenant_name}</span>
                <Badge variant={STATUS_VARIANT[share.status]}>{STATUS_LABEL[share.status]}</Badge>
                <button
                  type="button"
                  className="button-icon-soft button-icon-soft-danger"
                  aria-label={`Freigabe für ${share.tenant_name} beenden`}
                  onClick={() => void revoke(share.tenant_public_id, share.tenant_name)}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
