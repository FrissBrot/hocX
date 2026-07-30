"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { LyricsSearchResult, Songbook, SongbookSong } from "@/types/api";

export function SongbookEditor({ initialBook }: { initialBook: Songbook }) {
  const toast = useToast();
  const [book, setBook] = useState(initialBook);
  const [selectedId, setSelectedId] = useState<number | null>(initialBook.songs[0]?.id ?? null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LyricsSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [addingId, setAddingId] = useState<string | null>(null);
  const selected = book.songs.find((song) => song.id === selectedId) ?? null;

  async function searchSongs(event: FormEvent) {
    event.preventDefault();
    setSearching(true);
    try {
      setResults(await browserApiFetch<LyricsSearchResult[]>(`/api/lyrics/search?q=${encodeURIComponent(query)}`));
    } catch (error) {
      toast(error instanceof Error ? error.message : "Suche fehlgeschlagen", "error");
    } finally {
      setSearching(false);
    }
  }

  async function addSong(result: LyricsSearchResult) {
    setAddingId(result.source_id);
    try {
      const song = await browserApiFetch<SongbookSong>(`/api/songbooks/${book.id}/songs`, {
        method: "POST",
        body: JSON.stringify({
          title: result.title,
          artist: result.artist,
          album: result.album,
          duration_seconds: result.duration_seconds,
          lyrics: result.lyrics,
          source_name: "LRCLIB",
          source_id: result.source_id,
        }),
      });
      setBook((current) => ({ ...current, song_count: current.song_count + 1, songs: [...current.songs, song] }));
      setSelectedId(song.id);
      setSearchOpen(false);
      toast(result.lyrics ? "Lied mit Liedtext hinzugefügt" : "Lied hinzugefügt. Liedtext bitte manuell ergänzen.");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Lied konnte nicht hinzugefügt werden", "error");
    } finally {
      setAddingId(null);
    }
  }

  function changeSelected(values: Partial<SongbookSong>) {
    if (!selected) return;
    setBook((current) => ({
      ...current,
      songs: current.songs.map((song) => (song.id === selected.id ? { ...song, ...values } : song)),
    }));
  }

  async function saveSong() {
    if (!selected) return;
    try {
      const saved = await browserApiFetch<SongbookSong>(`/api/songbook-songs/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: selected.title,
          artist: selected.artist,
          album: selected.album,
          lyrics: selected.lyrics,
        }),
      });
      changeSelected(saved);
      toast("Lied gespeichert", "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Lied konnte nicht gespeichert werden", "error");
    }
  }

  async function removeSong() {
    if (!selected || !window.confirm(`„${selected.title}“ aus dem Liederbuch entfernen?`)) return;
    await browserApiFetch<null>(`/api/songbook-songs/${selected.id}`, { method: "DELETE" });
    const remaining = book.songs.filter((song) => song.id !== selected.id);
    setBook((current) => ({ ...current, song_count: current.song_count - 1, songs: remaining }));
    setSelectedId(remaining[0]?.id ?? null);
    toast("Lied entfernt");
  }

  return (
    <>
      <div className="songbook-header">
        <div>
          <Link className="muted" href="/tools/songbooks">← Liederbücher</Link>
          <h2>{book.title}</h2>
          {book.description ? <p className="muted">{book.description}</p> : null}
        </div>
        <div className="songbook-header-actions">
          <button type="button" onClick={() => window.print()}>Drucken / PDF</button>
          <button className="button-primary" type="button" onClick={() => setSearchOpen(true)}>Lied hinzufügen</button>
        </div>
      </div>

      <div className="songbook-workspace">
        <aside className="songbook-song-list" aria-label="Lieder im Liederbuch">
          {book.songs.map((song, index) => (
            <button
              key={song.id}
              type="button"
              className={`songbook-song-item${song.id === selectedId ? " songbook-song-item-active" : ""}`}
              onClick={() => setSelectedId(song.id)}
            >
              <span className="songbook-song-number">{index + 1}</span>
              <span>
                <strong>{song.title}</strong>
                <small>{song.artist}</small>
              </span>
            </button>
          ))}
          {!book.songs.length ? <div className="editor-panel-empty muted">Noch keine Lieder</div> : null}
        </aside>

        <div className="songbook-editor">
          {selected ? (
            <>
              <div className="songbook-metadata">
                <label className="field-stack">
                  <span className="field-label">Titel</span>
                  <input value={selected.title} onChange={(event) => changeSelected({ title: event.target.value })} />
                </label>
                <label className="field-stack">
                  <span className="field-label">Interpret</span>
                  <input value={selected.artist} onChange={(event) => changeSelected({ artist: event.target.value })} />
                </label>
                <label className="field-stack">
                  <span className="field-label">Album</span>
                  <input value={selected.album ?? ""} onChange={(event) => changeSelected({ album: event.target.value || null })} />
                </label>
              </div>
              <label className="field-stack songbook-lyrics">
                <span className="field-label">Liedtext</span>
                <textarea
                  value={selected.lyrics}
                  onChange={(event) => changeSelected({ lyrics: event.target.value })}
                  placeholder="Liedtext eingeben"
                  spellCheck
                />
              </label>
              <div className="songbook-editor-actions">
                <button className="button-danger" type="button" onClick={removeSong}>Entfernen</button>
                <button className="button-primary" type="button" onClick={saveSong}>Speichern</button>
              </div>
            </>
          ) : (
            <div className="editor-panel-empty muted">Füge über die Suche ein Lied hinzu.</div>
          )}
        </div>
      </div>

      <article className="songbook-print" aria-hidden="true">
        <header>
          <h1>{book.title}</h1>
          {book.description ? <p>{book.description}</p> : null}
        </header>
        {book.songs.map((song, index) => (
          <section key={song.id}>
            <h2>{index + 1}. {song.title}</h2>
            <p>{song.artist}{song.album ? ` · ${song.album}` : ""}</p>
            <pre>{song.lyrics || "Kein Liedtext vorhanden."}</pre>
          </section>
        ))}
      </article>

      <Modal
        open={searchOpen}
        title="Lied hinzufügen"
        description="Titel oder Interpret suchen. Verfügbare Liedtexte werden automatisch übernommen."
        onClose={() => setSearchOpen(false)}
        size="wide"
      >
        <form className="song-search-form" onSubmit={searchSongs}>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Titel oder Interpret"
            aria-label="Lied suchen"
            minLength={2}
            required
            autoFocus
          />
          <button className="button-primary" type="submit" disabled={searching}>
            {searching ? "Suche..." : "Suchen"}
          </button>
        </form>
        <div className="song-search-results">
          {results.map((result) => (
            <div className="song-search-result" key={result.source_id}>
              <div>
                <strong>{result.title}</strong>
                <div className="table-subtitle">
                  {result.artist}{result.album ? ` · ${result.album}` : ""}
                  {result.lyrics ? " · Liedtext verfügbar" : " · ohne Liedtext"}
                </div>
              </div>
              <button type="button" onClick={() => addSong(result)} disabled={addingId === result.source_id}>
                Hinzufügen
              </button>
            </div>
          ))}
          {!searching && query && results.length === 0 ? <p className="muted">Keine Ergebnisse.</p> : null}
        </div>
      </Modal>
    </>
  );
}
