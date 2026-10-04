"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { confirmAddToSharedAlbum } from "./album-share-release";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
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
  onReleaseSelected,
}: {
  selectedIds: string[];
  tagSuggestions: string[];
  onClearSelection: () => void;
  onDone: () => void;
  // Albumansicht des Besitzers mit noch nicht freigegebenen Fotos in der Auswahl.
  onReleaseSelected?: () => void;
}) {
  const t = useTranslations("photos.bulkBar");
  const confirm = useConfirm();
  const showToast = useToast();
  const [albums, setAlbums] = useState<PhotoAlbum[]>([]);
  const [selectedAlbumId, setSelectedAlbumId] = useState("");
  const [taggingOpen, setTaggingOpen] = useState(false);
  const [tagsValue, setTagsValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  useEffect(() => {
    browserApiFetch<PhotoAlbum[]>("/api/files/albums").then((data) => setAlbums(data ?? [])).catch(() => {});
  }, []);

  async function addToAlbum() {
    if (!selectedAlbumId || busy) return;
    const album = albums.find((candidate) => candidate.id === selectedAlbumId);
    if (album && !(await confirmAddToSharedAlbum(confirm, album, selectedIds.length))) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/files/albums/${selectedAlbumId}/items`, {
        method: "POST",
        body: JSON.stringify({ file_ids: selectedIds }),
      });
      showToast(t("addedToAlbumToast", { count: selectedIds.length }), "success");
      onDone();
    } catch {
      showToast(t("addToAlbumError"), "error");
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
      showToast(t("tagsAddedToast"), "success");
      setTaggingOpen(false);
      setTagsValue("");
      onDone();
    } catch {
      showToast(t("tagsError"), "error");
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
      if (failed > 0) showToast(t("noAlbumToast", { count: failed }), "info");
      // Only claim success if at least one update actually went through - previously this
      // fired unconditionally, so selecting only photos outside an album showed both "0
      // möglich" and "hinzugefügt" toasts back to back, falsely telling the user the
      // action succeeded when nothing did (audit fix, 2026-09-17).
      if (failed < selectedIds.length) {
        showToast(bestOverride === "include" ? t("markedBestToast") : t("unmarkedBestToast"), "success");
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
      message: t("deleteConfirm", { count: selectedIds.length }),
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<FileBulkDeleteResult>("/api/files/bulk-delete", {
        method: "POST",
        body: JSON.stringify({ file_ids: selectedIds }),
      });
      const deletedCount = result?.deleted_ids.length ?? 0;
      if (deletedCount > 0) showToast(t("deletedToast", { count: deletedCount }), "success");
      if (result?.errors.length) showToast(result.errors.join(" · "), deletedCount > 0 ? "info" : "error");
      onDone();
    } catch {
      showToast(t("deleteError"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="photo-bulk-bar">
      <span className="pill">{t("selectedCount", { count: selectedIds.length })}</span>
      <div className="table-toolbar-actions">
        {onReleaseSelected && (
          <button type="button" className="button-secondary" onClick={onReleaseSelected} disabled={busy}>
            {t("release")}
          </button>
        )}
        <SearchableSelect
          className="photo-bulk-bar-album-select"
          options={albums}
          getId={(album) => album.id}
          getLabel={(album) => album.name}
          value={selectedAlbumId || null}
          onChange={(album) => setSelectedAlbumId(album?.id ?? "")}
          nullLabel={t("albumPlaceholder")}
          disabled={busy}
        />
        <button type="button" className="button-ghost button-secondary" onClick={() => void addToAlbum()} disabled={busy || !selectedAlbumId}>
          {t("addToAlbum")}
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={() => setTaggingOpen((current) => !current)} disabled={busy}>
          {t("addTags")}
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={() => void toggleBest("include")} disabled={busy}>
          {t("markBest")}
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={() => void toggleBest("exclude")} disabled={busy}>
          {t("unmarkBest")}
        </button>
        <button type="button" className="button-secondary" onClick={() => setShareOpen(true)} disabled={busy}>
          {t("share")}
        </button>
        <button type="button" className="button-secondary button-danger" onClick={() => void deleteSelected()} disabled={busy}>
          {t("delete")}
        </button>
        <button type="button" className="button-ghost button-secondary" onClick={onClearSelection} disabled={busy}>
          {t("clearSelection")}
        </button>
      </div>
      <ShareLinkModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        fileIds={selectedIds}
        defaultName={t("shareDefaultName", { count: selectedIds.length })}
      />
      {taggingOpen && (
        <div className="photo-bulk-bar-tagging">
          <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder={t("tagPlaceholder")} />
          <button type="button" className="button-secondary" onClick={() => void applyTags()} disabled={busy || !tagsValue.trim()}>
            {t("apply")}
          </button>
        </div>
      )}
    </div>
  );
}
