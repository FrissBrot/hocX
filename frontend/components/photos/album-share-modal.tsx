"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

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
const AVATAR_TONES = ["danger", "info", "warning", "success"] as const;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FORM_ID = "album-share-form";
const SEARCH_DELAY_MS = 250;

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

/** Profilbild, Initialen (bekannter Mandant ohne Bild) oder generisches Symbol (ohne Trust). */
function TenantAvatar({ name, imageUrl, tone, large = false }: { name: string | null; imageUrl: string | null; tone?: string; large?: boolean }) {
  const className = `album-share-avatar${large ? " album-share-avatar-lg" : ""}`;
  if (name && imageUrl) return <img className={`${className} album-share-avatar-img`} src={imageUrl} alt="" />;
  if (name) return <span className={`${className} album-share-avatar-${tone ?? avatarTone(name)}`} aria-hidden="true">{initials(name)}</span>;
  return (
    <span className={`${className} album-share-avatar-neutral`} aria-hidden="true" data-testid="tenant-avatar-generic">
      <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3.5 17V6.5l6.5-3.5 6.5 3.5V17" />
        <path d="M2 17h16M8 17v-4h4v4M7 9.5h.01M10 9.5h.01M13 9.5h.01" />
      </svg>
    </span>
  );
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
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<TenantLookup | null>(null);
  const [lookupError, setLookupError] = useState("");
  const [suggestions, setSuggestions] = useState<TenantLookup[] | null>(null);
  const [busy, setBusy] = useState(false);
  const requestIdRef = useRef(0);

  const trimmed = query.trim();
  const isId = UUID_PATTERN.test(trimmed);

  // Vollständige ID: sofort auflösen (auch unbekannte Mandanten, dann anonym). Sonst ab zwei
  // Zeichen nur unter vertrauten Mandanten nach Namen suchen - fremde sind per Name nicht auffindbar.
  useEffect(() => {
    const requestId = ++requestIdRef.current;
    setLookupError("");
    setSuggestions(null);
    if (preview) return;
    if (isId) {
      browserApiFetch<TenantLookup>(`/api/tenants/lookup?public_id=${encodeURIComponent(trimmed)}`)
        .then((tenant) => {
          if (requestIdRef.current !== requestId) return;
          if (tenant) setPreview(tenant);
          else setLookupError("Kein Mandant mit dieser ID gefunden.");
        })
        .catch(() => { if (requestIdRef.current === requestId) setLookupError("Kein Mandant mit dieser ID gefunden."); });
      return;
    }
    if (trimmed.length < 2) return;
    const timer = setTimeout(() => {
      browserApiFetch<TenantLookup[]>(`/api/tenants/trusted?search=${encodeURIComponent(trimmed)}`)
        .then((tenants) => { if (requestIdRef.current === requestId) setSuggestions(tenants ?? []); })
        .catch(() => { if (requestIdRef.current === requestId) setSuggestions([]); });
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [trimmed, isId, preview]);

  function changeQuery(value: string) {
    setQuery(value);
    setPreview(null);
  }

  function choose(tenant: TenantLookup) {
    setPreview(tenant);
    setQuery(tenant.name ?? tenant.id);
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
      toast(preview.name ? `Einladung an ${preview.name} gesendet.` : "Einladung gesendet.", "success");
      setQuery("");
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
      message: share.tenant_name
        ? pending
          ? `Einladung an „${share.tenant_name}“ zurückziehen?`
          : `„${share.tenant_name}“ den Zugriff auf dieses Album entziehen?`
        : pending
          ? "Einladung an diesen Mandanten zurückziehen?"
          : "Diesem Mandanten den Zugriff auf dieses Album entziehen?",
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
            {busy ? "Wird eingeladen…" : preview?.name ? `${preview.name} einladen` : "Einladen"}
          </button>
        </div>
      }
    >
      <ModalSaveForm id={FORM_ID} className="grid album-share-form" onSubmit={invite}>
        <div className="album-share-field-head">
          <label className="field-label" htmlFor="album-share-tenant-id">Mandanten-ID oder Name</label>
          <span className="album-share-field-hint">ID unter Mandant-Einstellungen → Allgemein</span>
        </div>
        <div className="album-share-input">
          <input
            id="album-share-tenant-id"
            className={isId ? "album-share-input-id" : undefined}
            value={query}
            onChange={(event) => changeQuery(event.target.value)}
            placeholder="Mandanten-ID einfügen"
            autoComplete="off"
            spellCheck={false}
          />
          {query && (
            <button type="button" className="album-share-input-clear" aria-label="Eingabe leeren" onClick={() => changeQuery("")}>
              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" aria-hidden="true">
                <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>
        {preview ? (
          <div className="album-share-found" role="status">
            <TenantAvatar name={preview.name} imageUrl={preview.profile_image_url} tone="success" large />
            <span className="album-share-entry-text">
              {preview.trusted && preview.name ? (
                <>
                  <strong>{preview.name}</strong>
                  <span className="album-share-entry-meta">
                    {[preview.slug, preview.participant_count !== null ? `${preview.participant_count} Teilnehmer` : null].filter(Boolean).join(" · ")}
                  </span>
                </>
              ) : (
                <>
                  <strong>Mandant gefunden</strong>
                  <span className="album-share-entry-meta">Name und Profilbild werden sichtbar, sobald er eine Einladung angenommen hat.</span>
                </>
              )}
            </span>
            <span className="album-share-found-mark">✓ Gefunden</span>
          </div>
        ) : lookupError ? (
          <p className="status-banner status-error" role="alert">{lookupError}</p>
        ) : suggestions === null ? null : suggestions.length === 0 ? (
          <p className="album-share-field-hint">
            Kein bekannter Mandant mit diesem Namen. Neue Mandanten findest du nur über ihre Mandanten-ID.
          </p>
        ) : (
          <ul className="album-share-list" aria-label="Bekannte Mandanten">
            {suggestions.map((tenant) => (
              <li key={tenant.id}>
                <button type="button" className="album-share-entry album-share-suggestion" onClick={() => choose(tenant)}>
                  <TenantAvatar name={tenant.name} imageUrl={tenant.profile_image_url} />
                  <span className="album-share-entry-text">
                    <strong>{tenant.name}</strong>
                    {tenant.slug && <span className="album-share-entry-meta">{tenant.slug}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ModalSaveForm>

      {album.shared_with.length > 0 && (
        <section className="album-share-list-section">
          <h3 className="field-label">Geteilt mit</h3>
          <ul className="album-share-list">
            {album.shared_with.map((share) => {
              const pending = share.status === "pending";
              const displayName = share.tenant_name ?? "Unbekannter Mandant";
              return (
                <li key={share.tenant_public_id} className="album-share-entry">
                  <TenantAvatar name={share.tenant_name} imageUrl={share.tenant_profile_image_url} />
                  <span className="album-share-entry-text">
                    <strong>{displayName}</strong>
                    <span className="album-share-entry-meta">
                      {share.tenant_name ? shareMeta(share) : (
                        <>
                          <span className="album-share-entry-id" title={share.tenant_public_id}>{share.tenant_public_id.slice(0, 8)}…</span>
                          {" · "}{shareMeta(share)}
                        </>
                      )}
                    </span>
                  </span>
                  <Badge variant={STATUS_VARIANT[share.status]}>{STATUS_LABEL[share.status]}</Badge>
                  <button
                    type="button"
                    className="button-ghost album-share-entry-action"
                    aria-label={`${pending ? "Einladung an" : "Freigabe für"} ${share.tenant_name ?? share.tenant_public_id} ${pending ? "zurückziehen" : "entfernen"}`}
                    onClick={() => void revoke(share)}
                  >
                    {pending ? "Zurückziehen" : "Entfernen"}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </Modal>
  );
}
