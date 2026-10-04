"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { initials } from "@/components/protocol/collaboration-presence";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { toIntlLocale } from "@/lib/utils/format";
import { AlbumTenantShareStatus, PhotoAlbum, TenantLookup } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function statusLabel(t: TFunc): Record<AlbumTenantShareStatus["status"], string> {
  return { pending: t("status.pending"), accepted: t("status.accepted"), declined: t("status.declined") };
}
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

function formatShareDate(input: string | null | undefined, locale: string) {
  const date = input ? new Date(input) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(toIntlLocale(locale), { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function shareMeta(share: AlbumTenantShareStatus, t: TFunc, locale: string) {
  if (share.status === "pending") return t("invitedOn", { date: formatShareDate(share.invited_at, locale) });
  const since = share.responded_at ?? share.invited_at;
  return share.status === "accepted" ? t("since", { date: formatShareDate(since, locale) }) : t("declinedOn", { date: formatShareDate(since, locale) });
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
  const t = useTranslations("photos.shareModal");
  const locale = useLocale();
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
          else setLookupError(t("lookupNotFound"));
        })
        .catch(() => { if (requestIdRef.current === requestId) setLookupError(t("lookupNotFound")); });
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
      toast(preview.name ? t("invitedToast", { name: preview.name }) : t("invitedToastNoName"), "success");
      setQuery("");
      setPreview(null);
      onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("inviteError"), "error");
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
          ? t("revokeConfirmNamedPending", { name: share.tenant_name })
          : t("revokeConfirmNamedActive", { name: share.tenant_name })
        : pending
          ? t("revokeConfirmGenericPending")
          : t("revokeConfirmGenericActive"),
      confirmLabel: pending ? t("withdrawLabel") : t("removeLabel"),
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/files/albums/${album.id}/shares/${share.tenant_public_id}`, { method: "DELETE" });
      toast(pending ? t("withdrawnToast") : t("endedToast"), "success");
      onChanged();
    } catch {
      toast(t("revokeError"), "error");
    }
  }

  return (
    <Modal
      open={open}
      title={t("title")}
      className="album-share-modal"
      onClose={onClose}
      header={
        <div>
          <div className="eyebrow">{t("eyebrow")}</div>
          <h2>{t("title")}</h2>
          <p className="muted">
            {t("description", { albumName: album.name })}
          </p>
        </div>
      }
      footer={
        <div className="modal-footer-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" form={FORM_ID} className="button-primary" disabled={!preview || busy}>
            {busy ? t("inviting") : preview?.name ? t("inviteNamed", { name: preview.name }) : t("invite")}
          </button>
        </div>
      }
    >
      <ModalSaveForm id={FORM_ID} className="grid album-share-form" onSubmit={invite}>
        <div className="album-share-field-head">
          <label className="field-label" htmlFor="album-share-tenant-id">{t("fieldLabel")}</label>
          <span className="album-share-field-hint">{t("fieldHint")}</span>
        </div>
        <div className="album-share-input">
          <input
            id="album-share-tenant-id"
            className={isId ? "album-share-input-id" : undefined}
            value={query}
            onChange={(event) => changeQuery(event.target.value)}
            placeholder={t("inputPlaceholder")}
            autoComplete="off"
            spellCheck={false}
          />
          {query && (
            <button type="button" className="album-share-input-clear" aria-label={t("clearAriaLabel")} onClick={() => changeQuery("")}>
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
                    {[preview.slug, preview.participant_count !== null ? t("participantsSuffix", { count: preview.participant_count }) : null].filter(Boolean).join(" · ")}
                  </span>
                </>
              ) : (
                <>
                  <strong>{t("foundGeneric")}</strong>
                  <span className="album-share-entry-meta">{t("foundGenericHint")}</span>
                </>
              )}
            </span>
            <span className="album-share-found-mark">{t("foundMark")}</span>
          </div>
        ) : lookupError ? (
          <p className="status-banner status-error" role="alert">{lookupError}</p>
        ) : suggestions === null ? null : suggestions.length === 0 ? (
          <p className="album-share-field-hint">
            {t("noSuggestionsHint")}
          </p>
        ) : (
          <ul className="album-share-list" aria-label={t("suggestionsAriaLabel")}>
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
          <h3 className="field-label">{t("sharedWithTitle")}</h3>
          <ul className="album-share-list">
            {album.shared_with.map((share) => {
              const pending = share.status === "pending";
              const displayName = share.tenant_name ?? t("unknownTenant");
              return (
                <li key={share.tenant_public_id} className="album-share-entry">
                  <TenantAvatar name={share.tenant_name} imageUrl={share.tenant_profile_image_url} />
                  <span className="album-share-entry-text">
                    <strong>{displayName}</strong>
                    <span className="album-share-entry-meta">
                      {share.tenant_name ? shareMeta(share, t, locale) : (
                        <>
                          <span className="album-share-entry-id" title={share.tenant_public_id}>{share.tenant_public_id.slice(0, 8)}…</span>
                          {" · "}{shareMeta(share, t, locale)}
                        </>
                      )}
                    </span>
                  </span>
                  <Badge variant={STATUS_VARIANT[share.status]}>{statusLabel(t)[share.status]}</Badge>
                  <button
                    type="button"
                    className="button-ghost album-share-entry-action"
                    aria-label={pending ? t("actionAriaLabelPending", { name: share.tenant_name ?? share.tenant_public_id }) : t("actionAriaLabelActive", { name: share.tenant_name ?? share.tenant_public_id })}
                    onClick={() => void revoke(share)}
                  >
                    {pending ? t("withdrawLabel") : t("removeLabel")}
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
