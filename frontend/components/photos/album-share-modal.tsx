"use client";

import { FormEvent, useState } from "react";

import { initials } from "@/components/protocol/collaboration-presence";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { AlbumTenantShareStatus, PhotoAlbum, TenantLookup } from "@/types/api";

const STATUS_LABEL: Record<AlbumTenantShareStatus["status"], string> = { pending: "Einladung offen", accepted: "Hat Zugriff", declined: "Abgelehnt" };
const STATUS_VARIANT: Record<AlbumTenantShareStatus["status"], BadgeVariant> = { pending: "warning", accepted: "success", declined: "danger" };
// Getönte Avatar-Flächen aus den Status-Tokens, damit sie in beiden Themes stimmen.
const AVATAR_TONES = ["danger", "info", "warning", "success", "neutral"] as const;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FORM_ID = "album-share-form";

function avatarTone(name: string) {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return AVATAR_TONES[Math.abs(hash) % AVATAR_TONES.length];
}

function formatShareDate(input: string | null | undefined) {
  const date = input ? new Date(input) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("de-CH", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function shareMeta(share: AlbumTenantShareStatus) {
  if (share.status === "pending") return `eingeladen am ${formatShareDate(share.invited_at)}`;
  const since = share.responded_at ?? share.invited_at;
  return share.status === "accepted" ? `seit ${formatShareDate(since)}` : `abgelehnt am ${formatShareDate(since)}`;
}

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

  async function lookup(value: string) {
    const trimmed = value.trim();
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

  function changeTenantId(value: string) {
    setTenantId(value);
    setPreview(null);
    setLookupError("");
    // Eingefügte vollständige ID sofort auflösen, alles andere erst beim Verlassen des Feldes.
    if (UUID_PATTERN.test(value.trim())) void lookup(value);
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

  async function revoke(share: AlbumTenantShareStatus) {
    const pending = share.status === "pending";
    const ok = await confirm({
      tone: "danger",
      message: pending
        ? `Einladung an „${share.tenant_name}“ zurückziehen?`
        : `„${share.tenant_name}“ den Zugriff auf dieses Album entziehen?`,
      confirmLabel: pending ? "Zurückziehen" : "Entfernen",
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/files/albums/${album.id}/shares/${share.tenant_public_id}`, { method: "DELETE" });
      toast(pending ? "Einladung zurückgezogen." : "Freigabe beendet.", "success");
      onChanged();
    } catch {
      toast("Freigabe konnte nicht beendet werden.", "error");
    }
  }

  return (
    <Modal
      open={open}
      title="Mit anderem Mandanten teilen"
      className="album-share-modal"
      onClose={onClose}
      header={
        <div>
          <div className="eyebrow">Album teilen</div>
          <h2>Mit anderem Mandanten teilen</h2>
          <p className="muted">
            Der Mandant erhält eine Einladung. Nach dem Annehmen erscheint «{album.name}» bei ihm unter Alben.
          </p>
        </div>
      }
      footer={
        <div className="modal-footer-actions">
          <button type="button" className="button-ghost" onClick={onClose}>Abbrechen</button>
          <button type="submit" form={FORM_ID} className="button-primary" disabled={!preview || busy}>
            {busy ? "Wird eingeladen…" : preview ? `${preview.name} einladen` : "Einladen"}
          </button>
        </div>
      }
    >
      <ModalSaveForm id={FORM_ID} className="grid album-share-form" onSubmit={invite}>
        <div className="album-share-field-head">
          <label className="field-label" htmlFor="album-share-tenant-id">Mandanten-ID</label>
          <span className="album-share-field-hint">Zu finden unter Mandant-Einstellungen → Allgemein</span>
        </div>
        <div className="album-share-input">
          <input
            id="album-share-tenant-id"
            value={tenantId}
            onChange={(event) => changeTenantId(event.target.value)}
            onBlur={() => { if (!preview && !lookupError) void lookup(tenantId); }}
            placeholder="Mandanten-ID einfügen"
            autoComplete="off"
            spellCheck={false}
          />
          {tenantId && (
            <button type="button" className="album-share-input-clear" aria-label="Eingabe leeren" onClick={() => changeTenantId("")}>
              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" aria-hidden="true">
                <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>
        {preview ? (
          <div className="album-share-found" role="status">
            <span className="album-share-avatar album-share-avatar-success" aria-hidden="true">{initials(preview.name)}</span>
            <span className="album-share-entry-text">
              <strong>{preview.name}</strong>
              <span className="album-share-entry-meta">
                {[preview.slug, `${preview.participant_count} Teilnehmer`].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="album-share-found-mark">✓ Gefunden</span>
          </div>
        ) : lookupError ? (
          <p className="status-banner status-error" role="alert">{lookupError}</p>
        ) : null}
      </ModalSaveForm>

      {album.shared_with.length > 0 && (
        <section className="album-share-list-section">
          <h3 className="field-label">Geteilt mit</h3>
          <ul className="album-share-list">
            {album.shared_with.map((share) => (
              <li key={share.tenant_public_id} className="album-share-entry">
                <span className={`album-share-avatar album-share-avatar-${avatarTone(share.tenant_name)}`} aria-hidden="true">
                  {initials(share.tenant_name)}
                </span>
                <span className="album-share-entry-text">
                  <strong>{share.tenant_name}</strong>
                  <span className="album-share-entry-meta">{shareMeta(share)}</span>
                </span>
                <Badge variant={STATUS_VARIANT[share.status]}>{STATUS_LABEL[share.status]}</Badge>
                <button
                  type="button"
                  className="button-ghost album-share-entry-action"
                  aria-label={`${share.status === "pending" ? "Einladung an" : "Freigabe für"} ${share.tenant_name} ${share.status === "pending" ? "zurückziehen" : "entfernen"}`}
                  onClick={() => void revoke(share)}
                >
                  {share.status === "pending" ? "Zurückziehen" : "Entfernen"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Modal>
  );
}
