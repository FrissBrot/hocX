"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { HelpPopover } from "@/components/ui/help-popover";

import { PhotoActionIcon } from "./photo-action-icon";
import { PhotoCaptureDateDialog } from "./photo-capture-date-dialog";
import { PhotoPlaceDialog } from "./photo-place-dialog";
import { KeywordsBulkDialog } from "@/components/files/keywords-bulk-dialog";
import { menuButtonKeyDown, Popover } from "@/components/ui/popover";
import { confirmAddToSharedAlbum } from "./album-share-release";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { TagInput } from "@/components/ui/tag-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { fetchAllPages } from "@/components/mobile/mobile-data";
import { ChunkProgress, runInChunks } from "@/lib/uploads/upload-jobs";
import { formatDate } from "@/lib/utils/format";
import { EventSummary, FileBulkDeleteResult, FileOverviewItem, PhotoAlbum } from "@/types/api";

// Grenzen der Bulk-Endpunkte (Backend): Tags, Album, Löschen, Termin, Keywords je 200 Dateien.
// Grössere Auswahlen (z. B. «Alle N dieses Uploads») stückelt die Leiste (Upload-Verlauf E-4).
const BULK_CHUNK = 200;
const BEST_PARALLEL = 8;

export function PhotoBulkBar({
  selectedIds,
  tagSuggestions,
  onClearSelection,
  onDone,
  onReleaseSelected,
  onRemoveFromAlbum,
  onSelectAll,
  selectedItems = [],
  onSelectAllInJob,
  jobSelectableCount = null,
  uploadJobId,
  referenceItems = [],
}: {
  selectedIds: string[];
  tagSuggestions: string[];
  onClearSelection: () => void;
  onDone: () => void;
  // Albumansicht des Besitzers mit noch nicht freigegebenen Fotos in der Auswahl.
  onReleaseSelected?: () => void;
  // Albumansicht: Auswahl aus dem Album nehmen (die Fotos bleiben erhalten).
  onRemoveFromAlbum?: () => void;
  onSelectAll?: () => void;
  selectedItems?: { id: string; original_name: string; content_url: string }[];
  // Upload-Verlauf: alle beschreibbaren Fotos des Vorgangs wählen (auch nicht geladene)
  onSelectAllInJob?: () => void;
  jobSelectableCount?: number | null;
  uploadJobId?: string;
  // Geladene Fotos als Referenz für «Nach Referenzfoto» im Datumsdialog
  referenceItems?: FileOverviewItem[];
}) {
  const t = useTranslations("photos.bulkBar");
  const tShareRelease = useTranslations("photos.shareRelease");
  const tCapture = useTranslations("photos.captureCorrection");
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
  const [captureDateOpen, setCaptureDateOpen] = useState(false);
  const [keywordsOpen, setKeywordsOpen] = useState(false);
  const [placeOpen, setPlaceOpen] = useState(false);
  const tPlaces = useTranslations("photos.places");
  // Fortschritt gestückelter Aktionen («Tags werden gesetzt … 400/1240») und Abbruch
  const [progress, setProgress] = useState<(ChunkProgress & { label: string }) | null>(null);
  const cancelRef = useRef(false);
  const eventAnchorRef = useRef<HTMLDivElement>(null);
  const [eventOpen, setEventOpen] = useState(false);
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [selectedEventId, setSelectedEventId] = useState("");

  useEffect(() => {
    if (!eventOpen || events.length > 0) return;
    fetchAllPages<EventSummary>("/api/events").then((data) => setEvents(data)).catch(() => {});
  }, [eventOpen, events.length]);

  /** Auswahl in Stücken an einen Bulk-Endpunkt; Rückgabe: Anzahl fehlgeschlagener Stücke. */
  async function chunked<R>(label: string, run: (ids: string[]) => Promise<R>) {
    cancelRef.current = false;
    const outcome = await runInChunks(selectedIds, BULK_CHUNK, run, {
      onProgress: (value) => setProgress(selectedIds.length > BULK_CHUNK ? { ...value, label } : null), // i18n-ok: Vergleich, kein Text
      shouldCancel: () => cancelRef.current,
    });
    setProgress(null);
    if (outcome.cancelled) showToast(t("chunkCancelled"), "info");
    if (outcome.failedChunks > 0) showToast(t("chunkPartialError", { count: outcome.failedChunks }), "error");
    return outcome;
  }

  async function linkEvent(mode: "set" | "auto") {
    if (busy || (mode === "set" && !selectedEventId)) return;
    setBusy(true);
    try {
      const outcome = await chunked(t("eventProgress"), (ids) =>
        browserApiFetch<{ updated_ids: string[]; not_found_ids: string[] }>("/api/files/bulk-event-link", {
          method: "POST",
          body: JSON.stringify({ file_ids: ids, mode, event_id: mode === "set" ? selectedEventId : null }),
        }),
      );
      const updated = outcome.results.reduce((sum, result) => sum + (result?.updated_ids.length ?? 0), 0);
      if (updated > 0) showToast(mode === "set" ? t("eventLinkedToast", { count: updated }) : t("eventAutoToast", { count: updated }), "success");
      setEventOpen(false);
      onDone();
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    browserApiFetch<PhotoAlbum[]>("/api/files/albums").then((data) => setAlbums(data ?? [])).catch(() => {});
  }, []);

  async function addToAlbum() {
    if (!selectedAlbumId || busy) return;
    const album = albums.find((candidate) => candidate.id === selectedAlbumId);
    if (album && !(await confirmAddToSharedAlbum(confirm, tShareRelease, album, selectedIds.length))) return;
    setBusy(true);
    try {
      const outcome = await chunked(t("albumProgress"), (ids) =>
        browserApiFetch(`/api/files/albums/${selectedAlbumId}/items`, { method: "POST", body: JSON.stringify({ file_ids: ids }) }),
      );
      if (outcome.results.length === 0 && outcome.failedChunks > 0) showToast(t("addToAlbumError"), "error");
      else showToast(t("addedToAlbumToast", { count: Math.min(selectedIds.length, outcome.results.length * BULK_CHUNK) }), "success");
      onDone();
    } finally {
      setBusy(false);
    }
  }

  async function applyTags() {
    const addTags = tagsValue.split(",").map((tag) => tag.trim()).filter(Boolean);
    if (addTags.length === 0 || busy) return;
    setBusy(true);
    try {
      const outcome = await chunked(t("tagsProgress"), (ids) =>
        browserApiFetch("/api/files/bulk-tags", { method: "POST", body: JSON.stringify({ file_ids: ids, add_tags: addTags, remove_tags: [] }) }),
      );
      if (outcome.results.length === 0 && outcome.failedChunks > 0) {
        showToast(t("tagsError"), "error");
        return;
      }
      showToast(t("tagsAddedToast"), "success");
      setTaggingOpen(false);
      setTagsValue("");
      onDone();
    } finally {
      setBusy(false);
    }
  }

  async function toggleBest(bestOverride: "include" | "exclude") {
    if (busy) return;
    setBusy(true);
    try {
      // Je Foto ein Aufruf - in kleinen Gruppen statt alle auf einmal (grosse Auswahl aus dem Upload-Verlauf)
      let failed = 0;
      await runInChunks(selectedIds, BEST_PARALLEL, async (ids) => {
        const results = await Promise.allSettled(
          ids.map((id) => browserApiFetch(`/api/files/${id}/best`, { method: "PATCH", body: JSON.stringify({ best_override: bestOverride }) })),
        );
        failed += results.filter((result) => result.status === "rejected").length;
      }, {
        onProgress: (value) => setProgress(selectedIds.length > BULK_CHUNK ? { ...value, label: t("bestProgress") } : null), // i18n-ok: Vergleich, kein Text
        shouldCancel: () => cancelRef.current,
      });
      setProgress(null);
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
      const outcome = await chunked(t("deleteProgress"), (ids) =>
        browserApiFetch<FileBulkDeleteResult>("/api/files/bulk-delete", { method: "POST", body: JSON.stringify({ file_ids: ids }) }),
      );
      const deletedCount = outcome.results.reduce((sum, result) => sum + (result?.deleted_ids.length ?? 0), 0);
      const errors = outcome.results.flatMap((result) => result?.errors ?? []);
      if (deletedCount > 0) showToast(t("deletedToast", { count: deletedCount }), "success");
      if (errors.length) showToast(errors.slice(0, 5).join(" · "), deletedCount > 0 ? "info" : "error");
      if (outcome.results.length === 0 && outcome.failedChunks > 0) showToast(t("deleteError"), "error");
      onDone();
    } finally {
      setBusy(false);
    }
  }

  async function downloadSelected() {
    if (busy) return;
    setBusy(true);
    try {
      for (const item of selectedItems) {
        // Export-Endpunkt statt Original: trägt ein geschätztes Aufnahmedatum in die
        // heruntergeladene Kopie ein (das gespeicherte Original bleibt unverändert).
        const response = await fetch(`${browserApiBaseUrl}/api/stored-files/${item.id}/download?part=image`, { credentials: "include" });
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
        {onSelectAllInJob && (
          <button type="button" className="button-secondary button-ghost photo-bulk-select-all" onClick={onSelectAllInJob} disabled={busy}>
            {jobSelectableCount !== null && jobSelectableCount === selectedIds.length ? t("allOfUploadSelected") : t("selectAllOfUpload")}
          </button>
        )}
      </div>
      {progress ? (
        <div className="photo-bulk-progress" role="status" aria-live="polite">
          <span>{t("chunkProgress", { label: progress.label, done: progress.done, total: progress.total })}</span>
          <button type="button" className="button-secondary button-ghost" onClick={() => { cancelRef.current = true; }}>{t("chunkCancel")}</button>
        </div>
      ) : null}
      <div className="photo-bulk-actions">
        {onReleaseSelected && <button type="button" className="button-secondary button-ghost" onClick={onReleaseSelected} disabled={busy}>{t("release")}</button>}
        <div ref={albumAnchorRef}>
          <button type="button" className="button-secondary button-ghost" onClick={() => setAlbumOpen((open) => !open)} disabled={busy} aria-expanded={albumOpen}><PhotoActionIcon name="album" />{t("albumAction")}</button>
          <Popover open={albumOpen} onOpenChange={setAlbumOpen} anchorRef={albumAnchorRef} className="photo-bulk-album-popover" role="dialog" label={t("albumAction")}>
            <SearchableSelect className="photo-bulk-bar-album-select" options={albums} getId={(album) => album.id} getLabel={(album) => album.name} value={selectedAlbumId || null} onChange={(album) => setSelectedAlbumId(album?.id ?? "")} nullLabel={t("albumPlaceholder")} disabled={busy} />
            <button type="button" className="button-primary" onClick={() => void addToAlbum()} disabled={busy || !selectedAlbumId}>{t("addToAlbum")}</button>
          </Popover>
        </div>
        <button type="button" className="button-secondary button-ghost" onClick={() => setTaggingOpen((open) => !open)} disabled={busy} aria-expanded={taggingOpen}><PhotoActionIcon name="tag" />{t("tagsAction")}</button>
        <button type="button" className="button-secondary button-ghost" onClick={() => setKeywordsOpen(true)} disabled={busy}><PhotoActionIcon name="tag" />{t("keywordsAction")}</button>
        <div ref={bestAnchorRef}>
          <button type="button" className="button-secondary button-ghost photo-bulk-best" onClick={() => setBestOpen((open) => !open)} onKeyDown={menuButtonKeyDown(bestOpen, setBestOpen)} disabled={busy} aria-haspopup="menu" aria-expanded={bestOpen}><PhotoActionIcon name="star" />{t("bestAction")}</button>
          <HelpPopover topic={t("bestAction")} docs={{ page: "fotos", anchor: "best-of" }}>{t("bestHelp")}</HelpPopover>
          <Popover open={bestOpen} onOpenChange={setBestOpen} anchorRef={bestAnchorRef} className="action-menu">
            <button type="button" role="menuitem" className="action-menu-item" disabled={busy} onClick={() => { setBestOpen(false); void toggleBest("include"); }}>{t("markBest")}</button>
            <button type="button" role="menuitem" className="action-menu-item" disabled={busy} onClick={() => { setBestOpen(false); void toggleBest("exclude"); }}>{t("unmarkBest")}</button>
          </Popover>
        </div>
        <button type="button" className="button-secondary button-ghost" onClick={() => setCaptureDateOpen(true)} disabled={busy}><PhotoActionIcon name="calendar" />{tCapture("bulkAction")}</button>
        <button type="button" className="button-secondary button-ghost" onClick={() => setPlaceOpen(true)} disabled={busy}><PhotoActionIcon name="place" />{tPlaces("bulkAction")}</button>
        <div ref={eventAnchorRef}>
          <button type="button" className="button-secondary button-ghost" onClick={() => setEventOpen((open) => !open)} disabled={busy} aria-expanded={eventOpen}><PhotoActionIcon name="link" />{t("eventAction")}</button>
          <Popover open={eventOpen} onOpenChange={setEventOpen} anchorRef={eventAnchorRef} className="photo-bulk-album-popover" role="dialog" label={t("eventAction")}>
            <SearchableSelect
              className="photo-bulk-bar-album-select"
              options={events}
              getId={(event) => event.id}
              getLabel={(event) => `${event.title} (${formatDate(event.event_date)})`}
              value={selectedEventId || null}
              onChange={(event) => setSelectedEventId(event?.id ?? "")}
              nullLabel={t("eventPlaceholder")}
              disabled={busy}
            />
            <button type="button" className="button-primary" onClick={() => void linkEvent("set")} disabled={busy || !selectedEventId}>{t("eventSet")}</button>
            <button type="button" className="button-secondary" onClick={() => void linkEvent("auto")} disabled={busy}>{t("eventAuto")}</button>
          </Popover>
        </div>
        {selectedItems.length > 0 && <button type="button" className="button-secondary button-ghost" onClick={() => void downloadSelected()} disabled={busy}><PhotoActionIcon name="download" />{t("download")}</button>}
        <button type="button" className="button-secondary button-ghost" onClick={() => setShareOpen(true)} disabled={busy}><PhotoActionIcon name="share" />{t("share")}</button>
        {onRemoveFromAlbum && <button type="button" className="button-secondary button-ghost photo-bulk-remove-from-album" onClick={onRemoveFromAlbum} disabled={busy}><PhotoActionIcon name="album" />{t("removeFromAlbum")}</button>}
        <button type="button" className="button-secondary button-ghost photo-bulk-delete" onClick={() => void deleteSelected()} disabled={busy}><PhotoActionIcon name="delete" />{t("delete")}</button>
      </div>
      {captureDateOpen && (
        <PhotoCaptureDateDialog open fileIds={selectedIds} onClose={() => setCaptureDateOpen(false)} onDone={onDone} uploadJobId={uploadJobId} referenceItems={referenceItems} />
      )}
      {placeOpen && (
        <PhotoPlaceDialog open fileIds={selectedIds} uploadJobId={uploadJobId} onClose={() => setPlaceOpen(false)} onDone={onDone} />
      )}
      {keywordsOpen && (
        <KeywordsBulkDialog open fileIds={selectedIds} onClose={() => setKeywordsOpen(false)} onDone={onDone} />
      )}
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
