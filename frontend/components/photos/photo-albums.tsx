"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { AlbumPhotoPicker } from "./album-photo-picker";
import { AlbumReleaseNotice } from "./album-share-release";
import { AlbumShareModal } from "./album-share-modal";
import { PhotosView } from "./photos-view";
import { Badge } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { AlbumShareRequest, PhotoAlbum as Album, PhotoAlbumKind } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function albumKindLabel(t: TFunc): Record<PhotoAlbumKind, string> {
  return {
    manual: t("kindLabel.manual"),
    cycle: t("kindLabel.cycle"),
    submission: t("kindLabel.submission"),
    submission_element: t("kindLabel.submissionElement"),
  };
}

function PendingAlbumShareRequests({ requests, onDone }: { requests: AlbumShareRequest[]; onDone: () => void }) {
  const t = useTranslations("photos.albums");
  const toast = useToast();
  const [busyAlbumId, setBusyAlbumId] = useState<string | null>(null);

  async function respond(albumId: string, accept: boolean) {
    if (busyAlbumId) return;
    setBusyAlbumId(albumId);
    try {
      await browserApiFetch(`/api/files/albums/${albumId}/respond`, { method: "POST", body: JSON.stringify({ accept }) });
      toast(accept ? t("pendingRequests.acceptedToast") : t("pendingRequests.rejectedToast"), "success");
      onDone();
    } catch {
      toast(t("pendingRequests.respondError"), "error");
    } finally {
      setBusyAlbumId(null);
    }
  }

  if (requests.length === 0) return null;

  return (
    <div className="card album-share-requests">
      <div className="eyebrow">{t("pendingRequests.eyebrow")}</div>
      {requests.map((request) => (
        <div key={request.album_id} className="record-list-row album-share-row">
          <span className="album-share-row-name">
            <strong>{request.owner_tenant_name}</strong> {t("pendingRequests.requestText", { name: request.album_name })}
          </span>
          <button type="button" className="button-primary" disabled={busyAlbumId === request.album_id} onClick={() => void respond(request.album_id, true)}>
            {t("pendingRequests.accept")}
          </button>
          <button type="button" className="button-ghost" disabled={busyAlbumId === request.album_id} onClick={() => void respond(request.album_id, false)}>
            {t("pendingRequests.reject")}
          </button>
        </div>
      ))}
    </div>
  );
}

export function PhotoAlbums({
  openAlbumId,
  onOpenedAlbum,
  onReleaseChanged,
}: {
  // Von aussen (Hinweis auf der Fotos-Seite) direkt zu öffnendes Album.
  openAlbumId?: string | null;
  onOpenedAlbum?: () => void;
  // Freigaben haben sich geändert - der Hinweis auf der Fotos-Seite lädt neu.
  onReleaseChanged?: () => void;
} = {}) {
  const t = useTranslations("photos.albums");
  const toast = useToast();
  const [albums, setAlbums] = useState<Album[]>([]);
  const [active, setActive] = useState<Album | null>(null);
  const [pendingRequests, setPendingRequests] = useState<AlbumShareRequest[]>([]);
  const [creating, setCreating] = useState(false);
  const [picking, setPicking] = useState(false);
  const [sharingLink, setSharingLink] = useState(false);
  const [sharingTenant, setSharingTenant] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [pendingOnly, setPendingOnly] = useState(false);
  const [releasing, setReleasing] = useState(false);

  useEffect(() => {
    browserApiFetch<Album[]>("/api/files/albums")
      .then((data) => {
        setAlbums(data ?? []);
        setActive((current) => (current ? data?.find((album) => album.id === current.id) ?? current : current));
      })
      .catch(() => setError(t("loadError")))
      .finally(() => setLoading(false));
    browserApiFetch<AlbumShareRequest[]>("/api/files/album-share-requests")
      .then((data) => setPendingRequests(data ?? []))
      .catch(() => {});
  }, [revision]);

  // Album aus dem Hinweis auf der Fotos-Seite öffnen, direkt in der Prüfansicht.
  useEffect(() => {
    if (!openAlbumId || loading) return;
    const album = albums.find((candidate) => candidate.id === openAlbumId);
    if (album) {
      setActive(album);
      setPendingOnly(album.pending_share_count > 0);
    }
    onOpenedAlbum?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openAlbumId, loading, albums]);

  function openAlbum(album: Album) {
    setActive(album);
    setPendingOnly(false);
  }

  function handleReleased() {
    setRevision((value) => value + 1);
    onReleaseChanged?.();
  }

  async function releaseAll(album: Album) {
    if (releasing) return;
    setReleasing(true);
    try {
      const result = await browserApiFetch<{ released: number }>(`/api/files/albums/${album.id}/release`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast(t("releasedToast", { count: result?.released ?? 0 }), "success");
      setPendingOnly(false);
      handleReleased();
    } catch {
      toast(t("releaseError"), "error");
    } finally {
      setReleasing(false);
    }
  }

  async function createAlbum(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const album = await browserApiFetch<Album>("/api/files/albums", {
        method: "POST", body: JSON.stringify({ name: name.trim() }),
      });
      if (album) {
        setAlbums((current) => [album, ...current]);
        setActive(album);
        setCreating(false);
        setName("");
      }
    } catch {
      setError(t("createError"));
    } finally { setBusy(false); }
  }

  if (active) {
    return (
      <div className="grid">
        <div className="page-header">
          <div>
            <button type="button" className="button-ghost" onClick={() => { setActive(null); setPendingOnly(false); setRevision((value) => value + 1); }}>{t("backToAlbums")}</button>
            <h2>{active.name}</h2>
            <p className="muted">
              {albumKindLabel(t)[active.kind]}{active.kind !== "manual" ? t("autoManagedSuffix") : ""}
              {active.owner_tenant_name ? t("sharedBySuffix", { name: active.owner_tenant_name }) : ""}
            </p>
            {active.shared_with.length > 0 && (
              <p className="muted">
                {t("sharedWithPrefix")}{active.shared_with.map((share) => `${share.tenant_name ?? t("unknownTenant", { id: `${share.tenant_public_id.slice(0, 8)}…` })} (${share.status === "accepted" ? t("statusActive") : share.status === "pending" ? t("statusPending") : t("statusDeclined")})`).join(", ")}
              </p>
            )}
          </div>
          <div className="table-toolbar-actions">
            <button type="button" className="button-secondary" onClick={() => setPicking(true)}>{t("addExistingPhotos")}</button>
            <button type="button" className="button-secondary" onClick={() => setSharingLink(true)}>{t("shareLink")}</button>
            {!active.owner_tenant_name && (
              <button type="button" className="button-secondary" onClick={() => setSharingTenant(true)}>{t("shareWithTenant")}</button>
            )}
          </div>
        </div>
        {active.pending_share_count > 0 && (
          <AlbumReleaseNotice
            message={t("pendingNotice", { count: active.pending_share_count })}
          >
            <button type="button" className="button-ghost" onClick={() => setPendingOnly((current) => !current)}>
              {pendingOnly ? t("showAll") : t("showPendingOnly")}
            </button>
            <button type="button" className="button-secondary" disabled={releasing} onClick={() => void releaseAll(active)}>
              {releasing ? t("releasing") : t("releaseAll")}
            </button>
          </AlbumReleaseNotice>
        )}
        <PhotosView
          key={active.id + revision}
          albumId={active.id}
          sharePendingOnly={pendingOnly && active.pending_share_count > 0}
          onReleased={handleReleased}
        />
        {picking && (
          <AlbumPhotoPicker album={active} onClose={() => setPicking(false)} onAdded={() => setRevision((value) => value + 1)} />
        )}
        <ShareLinkModal open={sharingLink} onClose={() => setSharingLink(false)} albumId={active.id} defaultName={active.name} />
        {sharingTenant && (
          <AlbumShareModal
            open={sharingTenant}
            album={active}
            onClose={() => setSharingTenant(false)}
            onChanged={() => setRevision((value) => value + 1)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="grid">
      {error && <p role="alert" className="form-error-banner">{error}</p>}
      <PendingAlbumShareRequests requests={pendingRequests} onDone={() => setRevision((value) => value + 1)} />
      <div><button type="button" className="button-secondary" onClick={() => { setError(""); setCreating(true); }}>{t("createButton")}</button></div>
      {loading ? (
        <p className="muted">{t("loadingAlbums")}</p>
      ) : albums.length === 0 ? (
        <p className="muted">{t("emptyAlbums")}</p>
      ) : (
        <div className="album-grid">
          {albums.map((album) => (
            <button type="button" className="album-card" key={album.id} onClick={() => openAlbum(album)}>
              <div className="album-cover">
                {Array.from({ length: 4 }).map((_, index) => {
                  const url = album.cover_thumbnail_urls[index];
                  return url ? (
                    <img key={index} src={url} alt="" className="album-cover-cell" draggable={false} />
                  ) : (
                    <div key={index} className="album-cover-cell album-cover-empty" />
                  );
                })}
              </div>
              <div className="album-card-body">
                <span className="album-card-name">{album.name}</span>
                <span className="album-card-stats muted">
                  {t("photoCount", { count: album.photo_count })}
                  {album.kind !== "manual" && album.best_of_count > 0 ? t("bestOfSuffix", { count: album.best_of_count }) : ""}
                </span>
                <span className="album-card-kind muted">
                  {albumKindLabel(t)[album.kind]}{album.kind !== "manual" ? t("autoManagedInline") : ""}
                </span>
                {album.owner_tenant_name ? (
                  <Badge variant="info" className="album-card-badge">{t("sharedByBadge", { name: album.owner_tenant_name })}</Badge>
                ) : album.shared_with.some((share) => share.status === "accepted") ? (
                  <Badge variant="neutral" className="album-card-badge">{t("sharedBadge")}</Badge>
                ) : null}
                {album.pending_share_count > 0 && (
                  <Badge variant="warning" dot className="album-card-badge">
                    {t("pendingBadge", { count: album.pending_share_count })}
                  </Badge>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
      {creating && (
        <Modal open title={t("createModalTitle")} onClose={() => { if (!busy) setCreating(false); }}>
          <ModalSaveForm className="grid" onSubmit={createAlbum}>
            <label>{t("nameLabel")}<input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
            <button className="button-secondary" data-modal-save type="submit" disabled={busy || !name.trim()}>{busy ? t("creating") : t("createSubmit")}</button>
          </ModalSaveForm>
        </Modal>
      )}
    </div>
  );
}
