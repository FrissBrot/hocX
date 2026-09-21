"use client";

import { useEffect, useState } from "react";

import { PhotosView } from "./photos-view";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { PhotoAlbum as Album, PhotoAlbumKind } from "@/types/api";

const ALBUM_KIND_LABEL: Record<PhotoAlbumKind, string> = {
  manual: "Manuell erstellt",
  cycle: "Zyklus",
  submission: "Abgabe",
  submission_element: "Abgabe-Element",
};

export function PhotoAlbums() {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [active, setActive] = useState<Album | null>(null);
  const [creating, setCreating] = useState(false);
  const [picking, setPicking] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const toast = useToast();

  useEffect(() => {
    browserApiFetch<Album[]>("/api/files/albums")
      .then((data) => setAlbums(data ?? []))
      .catch(() => setError("Alben konnten nicht geladen werden."))
      .finally(() => setLoading(false));
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
            <p className="muted">{ALBUM_KIND_LABEL[active.kind]}{active.kind !== "manual" ? " (automatisch geführt)" : ""}</p>
          </div>
          <button type="button" className="button-secondary" onClick={() => setPicking(true)}>Vorhandene Fotos hinzufügen</button>
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
      </div>
    );
  }

  return (
    <div className="grid">
      {error && <p role="alert" className="form-error-banner">{error}</p>}
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
              </div>
            </button>
          ))}
        </div>
      )}
      {creating && (
        <Modal open title="Fotoalbum erstellen" onClose={() => { if (!busy) setCreating(false); }}>
          <form className="grid" onSubmit={createAlbum}>
            <label>Albumname<input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
            <button className="button-secondary" type="submit" disabled={busy || !name.trim()}>{busy ? "Wird erstellt…" : "Album erstellen"}</button>
          </form>
        </Modal>
      )}
    </div>
  );
}
