"use client";

import { useEffect, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { FilesView } from "./files-view";

type Album = { id: string; name: string };

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
  }, []);

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

  return <div className="grid">
    {error && <p role="alert" className="form-error-banner">{error}</p>}
    {active ? <>
      <div className="page-header">
        <div><button type="button" className="button-ghost" onClick={() => setActive(null)}>← Alle Alben</button><h2>{active.name}</h2></div>
        <button type="button" className="button-inline" onClick={() => setPicking(true)}>Vorhandene Fotos hinzufügen</button>
      </div>
      <FilesView key={active.id + revision} mode="photos" initialItems={[]} albumId={active.id} />
    </> : <>
      <div><button type="button" className="button-inline" onClick={() => { setError(""); setCreating(true); }}>+ Album erstellen</button></div>
      {loading ? <p className="muted">Alben werden geladen…</p> : albums.length === 0 ? <p className="muted">Noch keine Fotoalben vorhanden.</p> :
        <div className="files-grid">{albums.map((album) => <button type="button" className="file-card" key={album.id} onClick={() => setActive(album)}>
          <span className="file-card-body">{album.name}</span>
        </button>)}</div>}
    </>}
    {creating && <Modal open title="Fotoalbum erstellen" onClose={() => { if (!busy) setCreating(false); }}>
      <form className="grid" onSubmit={createAlbum}>
        <label>Albumname<input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <button className="button-inline" type="submit" disabled={busy || !name.trim()}>{busy ? "Wird erstellt…" : "Album erstellen"}</button>
      </form>
    </Modal>}
    {picking && active && <Modal open title="Fotos zum Album hinzufügen" size="wide" onClose={() => setPicking(false)}>
      <FilesView mode="photos" initialItems={[]} onSelectPhoto={async (item) => {
        try {
          await browserApiFetch(`/api/files/albums/${active.id}/items`, { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
          setRevision((value) => value + 1);
          toast("Foto zum Album hinzugefügt.", "success");
        } catch { toast("Foto konnte nicht hinzugefügt werden.", "error"); }
      }} />
    </Modal>}
  </div>;
}
