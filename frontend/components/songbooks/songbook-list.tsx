"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import { SongbookSummary } from "@/types/api";

export function SongbookList({ initialBooks }: { initialBooks: SongbookSummary[] }) {
  const toast = useToast();
  const [books, setBooks] = useState(initialBooks);
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const filtered = useMemo(() => {
    const q = search.trim().toLocaleLowerCase("de");
    return books.filter((book) => !q || `${book.title} ${book.description ?? ""}`.toLocaleLowerCase("de").includes(q));
  }, [books, search]);

  async function createBook(event: FormEvent) {
    event.preventDefault();
    try {
      const book = await browserApiFetch<SongbookSummary>("/api/songbooks", {
        method: "POST",
        body: JSON.stringify({ title, description: description || null }),
      });
      setBooks((current) => [book, ...current]);
      setCreating(false);
      setTitle("");
      setDescription("");
      toast("Liederbuch erstellt");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Liederbuch konnte nicht erstellt werden", "error");
    }
  }

  async function deleteBook(book: SongbookSummary) {
    if (!window.confirm(`Liederbuch „${book.title}“ löschen?`)) return;
    try {
      await browserApiFetch<null>(`/api/songbooks/${book.id}`, { method: "DELETE" });
      setBooks((current) => current.filter((item) => item.id !== book.id));
      toast("Liederbuch gelöscht");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Liederbuch konnte nicht gelöscht werden", "error");
    }
  }

  return (
    <>
      <DataToolbar
        title="Liederbücher"
        description="Lieder zusammenstellen und Liedtexte bearbeiten."
        actions={
          <div className="protocol-list-toolbar">
            <input
              className="protocol-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Liederbücher suchen"
              aria-label="Liederbücher suchen"
            />
            <button className="button-primary button-inline" type="button" onClick={() => setCreating(true)}>
              Neues Liederbuch
            </button>
          </div>
        }
      />
      <DataTable columns={["Titel", "Lieder", "Geändert", ""]} emptyMessage={filtered.length ? undefined : "Keine Liederbücher gefunden."}>
        {filtered.map((book) => (
          <tr key={book.id}>
            <td>
              <strong>{book.title}</strong>
              {book.description ? <div className="table-subtitle">{book.description}</div> : null}
            </td>
            <td>{book.song_count}</td>
            <td>{formatDateTime(book.updated_at)}</td>
            <td className="table-actions table-actions-end">
              <Link className="button-inline" href={`/tools/songbooks/${book.id}`}>Öffnen</Link>
              <button className="button-icon button-icon-danger" type="button" onClick={() => deleteBook(book)} aria-label={`${book.title} löschen`} title="Löschen">
                ×
              </button>
            </td>
          </tr>
        ))}
      </DataTable>
      <Modal open={creating} title="Liederbuch erstellen" onClose={() => setCreating(false)}>
        <form className="grid" onSubmit={createBook}>
          <label className="field-stack">
            <span className="field-label">Titel</span>
            <input required value={title} onChange={(event) => setTitle(event.target.value)} autoFocus />
          </label>
          <label className="field-stack">
            <span className="field-label">Beschreibung</span>
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} />
          </label>
          <div className="modal-header-actions">
            <button type="button" onClick={() => setCreating(false)}>Abbrechen</button>
            <button className="button-primary" type="submit">Erstellen</button>
          </div>
        </form>
      </Modal>
    </>
  );
}
