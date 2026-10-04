"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { PhotoActionIcon } from "./photo-action-icon";
import { Popover } from "@/components/ui/popover";
import { confirmAddToSharedAlbum } from "./album-share-release";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { TagInput } from "@/components/ui/tag-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { FileBulkDeleteResult, PhotoAlbum } from "@/types/api";

export function PhotoBulkBar({
  selectedIds,
  tagSuggestions,
  onClearSelection,
  onDone,
  onReleaseSelected,
  onSelectAll,
  selectedItems = [],
}: {
  selectedIds: string[];
  tagSuggestions: string[];
  onClearSelection: () => void;
  onDone: () => void;
  // Albumansicht des Besitzers mit noch nicht freigegebenen Fotos in der Auswahl.
  onReleaseSelected?: () => void;
  onSelectAll?: () => void;
  selectedItems?: { original_name: string; content_url: string }[];
}) {
  const t = useTranslations("photos.bulkBar");
  const confirm = useConfirm();
  const showToast = useToast();
  const [albums, setAlbums] = useState<PhotoAlbum[]>([]);
  const [selectedAlbumId, setSelectedAlbumId] = useState("");
  const [taggingOpen, setTaggingOpen] = useState(false);
  const [tagsValue, setTagsValue] = useState("");
  const [busy, setBusy] = useState(false);
  const albumAnchorRef = useRef<HTMLDivElement>(null);
  const bestAnchorRef = useRef<HTMLDivElement>(null);
  const [albumOpen, setAlbumOpen] = useState(false);
  const [bestOpen, setBestOpen] = useState(false);
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

  async function downloadSelected() {
    if (busy) return;
    setBusy(true);
    try {
      for (const item of selectedItems) {
        const response = await fetch(`${browserApiBaseUrl}${item.content_url}`, { credentials: "include" });
        if (!response.ok) throw new Error();
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = item.original_name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
    } catch {
      showToast(t("downloadError"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="photo-bulk-bar" role="region" aria-label={t("selectionActions")}>
      <div className="photo-bulk-selection">
        <button type="button" className="button-icon-soft photo-bulk-clear" aria-label={t("clearSelection")} onClick={onClearSelection} disabled={busy}><PhotoActionIcon name="close" /></button>
        <span className="photo-bulk-count">{t("selectedCount", { count: selectedIds.length })}</span>
        {onSelectAll && <button type="button" className="button-secondary button-ghost photo-bulk-select-all" onClick={onSelectAll} disabled={busy}>{t("selectAll")}</button>}
      </div>
      <div className="photo-bulk-actions">
        {onReleaseSelected && <button type="button" className="button-secondary button-ghost" onClick={onReleaseSelected} disabled={busy}>{t("release")}</button>}
        <div ref={albumAnchorRef}>
          <button type="button" className="button-secondary button-ghost" onClick={() => setAlbumOpen((open) => !open)} disabled={busy} aria-expanded={albumOpen}><PhotoActionIcon name="album" />{t("albumAction")}</button>
          <Popover open={albumOpen} onOpenChange={setAlbumOpen} anchorRef={albumAnchorRef} className="photo-bulk-album-popover">
            <SearchableSelect className="photo-bulk-bar-album-select" options={albums} getId={(album) => album.id} getLabel={(album) => album.name} value={selectedAlbumId || null} onChange={(album) => setSelectedAlbumId(album?.id ?? "")} nullLabel={t("albumPlaceholder")} disabled={busy} />
            <button type="button" className="button-primary" onClick={() => void addToAlbum()} disabled={busy || !selectedAlbumId}>{t("addToAlbum")}</button>
          </Popover>
        </div>
        <button type="button" className="button-secondary button-ghost" onClick={() => setTaggingOpen((open) => !open)} disabled={busy} aria-expanded={taggingOpen}><PhotoActionIcon name="tag" />{t("tagsAction")}</button>
        <div ref={bestAnchorRef}>
          <button type="button" className="button-secondary button-ghost photo-bulk-best" onClick={() => setBestOpen((open) => !open)} disabled={busy} aria-expanded={bestOpen}><PhotoActionIcon name="star" />{t("bestAction")}</button>
          <Popover open={bestOpen} onOpenChange={setBestOpen} anchorRef={bestAnchorRef} className="action-menu">
            <button type="button" className="action-menu-item" disabled={busy} onClick={() => { setBestOpen(false); void toggleBest("include"); }}>{t("markBest")}</button>
            <button type="button" className="action-menu-item" disabled={busy} onClick={() => { setBestOpen(false); void toggleBest("exclude"); }}>{t("unmarkBest")}</button>
          </Popover>
        </div>
        {selectedItems.length > 0 && <button type="button" className="button-secondary button-ghost" onClick={() => void downloadSelected()} disabled={busy}><PhotoActionIcon name="download" />{t("download")}</button>}
        <button type="button" className="button-secondary button-ghost" onClick={() => setShareOpen(true)} disabled={busy}><PhotoActionIcon name="share" />{t("share")}</button>
        <button type="button" className="button-secondary button-ghost photo-bulk-delete" onClick={() => void deleteSelected()} disabled={busy}><PhotoActionIcon name="delete" />{t("delete")}</button>
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
