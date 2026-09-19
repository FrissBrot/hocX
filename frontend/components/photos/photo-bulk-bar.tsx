"use client";

import { useEffect, useState } from "react";

import { SearchableSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { FileBulkDeleteResult, PhotoAlbum } from "@/types/api";

export function PhotoBulkBar({
  selectedIds,
  tagSuggestions,
  onClearSelection,
  onDone,
}: {
  selectedIds: string[];
  tagSuggestions: string[];
  onClearSelection: () => void;
  onDone: () => void;
}) {
  const confirm = useConfirm();
  const showToast = useToast();
  const [albums, setAlbums] = useState<PhotoAlbum[]>([]);
  const [selectedAlbumId, setSelectedAlbumId] = useState("");
  const [taggingOpen, setTaggingOpen] = useState(false);
  const [tagsValue, setTagsValue] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    browserApiFetch<PhotoAlbum[]>("/api/files/albums").then((data) => setAlbums(data ?? [])).catch(() => {});
  }, []);

  async function addToAlbum() {
    if (!selectedAlbumId || busy) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/files/albums/${selectedAlbumId}/items`, {
        method: "POST",
        body: JSON.stringify({ file_ids: selectedIds }),
      });
      showToast(`${selectedIds.length} Foto(s) zum Album hinzugefügt.`, "success");
      onDone();
    } catch {
      showToast("Fotos konnten nicht zum Album hinzugefügt werden.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function applyTags() {
    const addTags = tagsValue.split(",").map((tag) => tag.trim()).filter(Boolean);
    if (addTags.length === 0 || busy) return;
    setBusy(true);
    try {
      await browserApiFetch("/api/files/bulk-tags", {
        method: "POST",
        body: JSON.stringify({ file_ids: selectedIds, add_tags: addTags, remove_tags: [] }),
      });
      showToast("Tags hinzugefügt.", "success");
      setTaggingOpen(false);
      setTagsValue("");
      onDone();
    } catch {
      showToast("Tags konnten nicht hinzugefügt werden.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function toggleBest(bestOverride: "include" | "exclude") {
    if (busy) return;
    setBusy(true);
    try {
      const results = await Promise.allSettled(
        selectedIds.map((id) =>
          browserApiFetch(`/api/files/${id}/best`, { method: "PATCH", body: JSON.stringify({ best_override: bestOverride }) })
        )
      );
      const failed = results.filter((result) => result.status === "rejected").length;
      if (failed > 0) showToast(`${failed} Foto(s) gehören zu keinem Album - Best-of nicht möglich.`, "info");
      // Only claim success if at least one update actually went through - previously this
      // fired unconditionally, so selecting only photos outside an album showed both "0
      // möglich" and "hinzugefügt" toasts back to back, falsely telling the user the
      // action succeeded when nothing did (audit fix, 2026-09-17).
      if (failed < selectedIds.length) {
        showToast(bestOverride === "include" ? "Zu Best-of hinzugefügt." : "Aus Best-of entfernt.", "success");
      }
      onDone();
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelected() {
    if (busy) return;
    const ok = await confirm({
      tone: "danger",
      message: `${selectedIds.length} ${selectedIds.length === 1 ? "Bild wird" : "Bilder werden"} endgültig gelöscht. Diese Aktion kann nicht rückgängig gemacht werden.`,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<FileBulkDeleteResult>("/api/files/bulk-delete", {
        method: "POST",
        body: JSON.stringify({ file_ids: selectedIds }),
      });
      const deletedCount = result?.deleted_ids.length ?? 0;
      if (deletedCount > 0) showToast(deletedCount === 1 ? "1 Bild gelöscht." : `${deletedCount} Bilder gelöscht.`, "success");
      if (result?.errors.length) showToast(result.errors.join(" · "), deletedCount > 0 ? "info" : "error");
      onDone();
    } catch {
      showToast("Bilder konnten nicht gelöscht werden.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="photo-bulk-bar">
      <span className="pill">{selectedIds.length} ausgewählt</span>
      <div className="table-toolbar-actions">
        <SearchableSelect
          className="photo-bulk-bar-album-select"
          options={albums}
          getId={(album) => album.id}
          getLabel={(album) => album.name}
          value={selectedAlbumId || null}
          onChange={(album) => setSelectedAlbumId(album?.id ?? "")}
          nullLabel="Album wählen…"
          disabled={busy}
        />
        <button type="button" className="button-ghost button-secondary" onClick={() => void addToAlbum()} disabled={busy || !selectedAlbumId}>
          Zu Album hinzufügen
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={() => setTaggingOpen((current) => !current)} disabled={busy}>
          Tags hinzufügen
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={() => void toggleBest("include")} disabled={busy}>
          ★ Best-of
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={() => void toggleBest("exclude")} disabled={busy}>
          ☆ Best-of entfernen
        </button>
        <button type="button" className="button-secondary button-danger" onClick={() => void deleteSelected()} disabled={busy}>
          Löschen
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={onClearSelection} disabled={busy}>
          Auswahl aufheben
        </button>
      </div>
      {taggingOpen && (
        <div className="photo-bulk-bar-tagging">
          <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder="Tag hinzufügen…" />
          <button type="button" className="button-secondary" onClick={() => void applyTags()} disabled={busy || !tagsValue.trim()}>
            Anwenden
          </button>
        </div>
      )}
    </div>
  );
}
