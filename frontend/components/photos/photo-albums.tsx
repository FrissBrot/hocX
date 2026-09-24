"use client";

import { useEffect, useState } from "react";

import { AlbumShareModal } from "./album-share-modal";
import { PhotosView } from "./photos-view";
import { Badge } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { AlbumShareRequest, PhotoAlbum as Album, PhotoAlbumKind } from "@/types/api";

const ALBUM_KIND_LABEL: Record<PhotoAlbumKind, string> = {
  manual: "Manuell erstellt",
  cycle: "Zyklus",
  submission: "Abgabe",
  submission_element: "Abgabe-Element",
};

function PendingAlbumShareRequests({ requests, onDone }: { requests: AlbumShareRequest[]; onDone: () => void }) {
  const toast = useToast();
  const [busyAlbumId, setBusyAlbumId] = useState<string | null>(null);

  async function respond(albumId: string, accept: boolean) {
    if (busyAlbumId) return;
    setBusyAlbumId(albumId);
    try {
      await browserApiFetch(`/api/files/albums/${albumId}/respond`, { method: "POST", body: JSON.stringify({ accept }) });
      toast(accept ? "Album-Freigabe angenommen." : "Anfrage abgelehnt.", "success");
      onDone();
    } catch {
      toast("Anfrage konnte nicht beantwortet werden.", "error");
    } finally {
      setBusyAlbumId(null);
    }
  }

  if (requests.length === 0) return null;

  return (
    <div className="card album-share-requests">
      <div className="eyebrow">Anfragen</div>
      {requests.map((request) => (
        <div key={request.album_id} className="record-list-row album-share-row">
          <span className="album-share-row-name">
            <strong>{request.owner_tenant_name}</strong> möchte das Album „{request.album_name}“ mit dir teilen.
          </span>
          <button type="button" className="button-primary" disabled={busyAlbumId === request.album_id} onClick={() => void respond(request.album_id, true)}>
            Annehmen
          </button>
          <button type="button" className="button-ghost" disabled={busyAlbumId === request.album_id} onClick={() => void respond(request.album_id, false)}>
            Ablehnen
          </button>
        </div>
      ))}
    </div>
  );
}

export function PhotoAlbums() {
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
  const toast = useToast();

  useEffect(() => {
    browserApiFetch<Album[]>("/api/files/albums")
      .then((data) => {
        setAlbums(data ?? []);
        setActive((current) => (current ? data?.find((album) => album.id === current.id) ?? current : current));
      })
      .catch(() => setError("Alben konnten nicht geladen werden."))
      .finally(() => setLoading(false));
    browserApiFetch<AlbumShareRequest[]>("/api/files/album-share-requests")
      .then((data) => setPendingRequests(data ?? []))
      .catch(() => {});
  }, [revision]);

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
      setError("Album konnte nicht erstellt werden.");
    } finally { setBusy(false); }
  }

  if (active) {
    return (
      <div className="grid">
        <div className="page-header">
          <div>
            <button type="button" className="button-ghost" onClick={() => { setActive(null); setRevision((value) => value + 1); }}>← Alle Alben</button>
            <h2>{active.name}</h2>
            <p className="muted">
              {ALBUM_KIND_LABEL[active.kind]}{active.kind !== "manual" ? " (automatisch geführt)" : ""}
              {active.owner_tenant_name ? ` · Geteilt von ${active.owner_tenant_name}` : ""}
            </p>
            {active.shared_with.length > 0 && (
              <p className="muted">
                Geteilt mit: {active.shared_with.map((share) => `${share.tenant_name} (${share.status === "accepted" ? "aktiv" : share.status === "pending" ? "angefragt" : "abgelehnt"})`).join(", ")}
              </p>
            )}
          </div>
          <div className="table-toolbar-actions">
            <button type="button" className="button-secondary" onClick={() => setPicking(true)}>Vorhandene Fotos hinzufügen</button>
            <button type="button" className="button-secondary" onClick={() => setSharingLink(true)}>Link teilen</button>
            {active.kind === "manual" && !active.owner_tenant_name && (
              <button type="button" className="button-secondary" onClick={() => setSharingTenant(true)}>Mit anderem Mandanten teilen</button>
            )}
          </div>
        </div>
        <PhotosView key={active.id + revision} albumId={active.id} />
        {picking && (
          <Modal open title="Fotos zum Album hinzufügen" size="wide" onClose={() => setPicking(false)}>
            <PhotosView onSelectPhoto={async (item) => {
              try {
                await browserApiFetch(`/api/files/albums/${active.id}/items`, { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
                setRevision((value) => value + 1);
                toast("Foto zum Album hinzugefügt.", "success");
              } catch { toast("Foto konnte nicht hinzugefügt werden.", "error"); }
            }} />
          </Modal>
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
      <div><button type="button" className="button-secondary" onClick={() => { setError(""); setCreating(true); }}>+ Album erstellen</button></div>
      {loading ? (
        <p className="muted">Alben werden geladen…</p>
      ) : albums.length === 0 ? (
        <p className="muted">Noch keine Fotoalben vorhanden.</p>
      ) : (
        <div className="album-grid">
          {albums.map((album) => (
            <button type="button" className="album-card" key={album.id} onClick={() => setActive(album)}>
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
                  {album.photo_count} {album.photo_count === 1 ? "Foto" : "Fotos"}
                  {album.kind !== "manual" && album.best_of_count > 0 ? ` · ${album.best_of_count} Best-of` : ""}
                </span>
                <span className="album-card-kind muted">
                  {ALBUM_KIND_LABEL[album.kind]}{album.kind !== "manual" ? " · automatisch geführt" : ""}
                </span>
                {album.owner_tenant_name ? (
                  <Badge variant="info" className="album-card-badge">Geteilt von {album.owner_tenant_name}</Badge>
                ) : album.shared_with.some((share) => share.status === "accepted") ? (
                  <Badge variant="neutral" className="album-card-badge">Geteilt</Badge>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      )}
      {creating && (
        <Modal open title="Fotoalbum erstellen" onClose={() => { if (!busy) setCreating(false); }}>
          <ModalSaveForm className="grid" onSubmit={createAlbum}>
            <label>Albumname<input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
            <button className="button-secondary" data-modal-save type="submit" disabled={busy || !name.trim()}>{busy ? "Wird erstellt…" : "Album erstellen"}</button>
          </ModalSaveForm>
        </Modal>
      )}
    </div>
  );
}
