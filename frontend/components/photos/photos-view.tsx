"use client";

import { useEffect, useRef, useState } from "react";

import { GalleryUploadModal } from "./gallery-upload-modal";
import { GalleryUploadProgress } from "./gallery-upload-progress";
import { mergeNewItems } from "./merge-new-items";
import { PhotoAlbums } from "./photo-albums";
import { PhotoAnalysisProgress } from "./photo-analysis-progress";
import { PhotoBulkBar } from "./photo-bulk-bar";
import { PhotoDateGroups } from "./photo-date-groups";
import { PhotoSimilarSeries } from "./photo-similar-series";
import { PhotoViewer } from "./photo-viewer";
import { FileDropOverlay } from "@/components/ui/file-drop-overlay";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useFileDrop } from "@/lib/hooks/use-file-drop";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { FileOverviewItem, GalleryUploadJob, GalleryUploadJobDetail, PhotoAnalysisProgress as ProgressData } from "@/types/api";

const PAGE_SIZE = 60;
const SYNC_INTERVAL_MS = 15000;

type SortKey = "group_date" | "created_at" | "sharpness_score" | "exposure_score" | "face_quality_score";
type Tab = "all" | "albums" | "similar";

type SortOption = { id: string; label: string; key: SortKey; dir: "asc" | "desc" };

const SORT_OPTIONS: SortOption[] = [
  { id: "group_date:desc", label: "Neueste zuerst", key: "group_date", dir: "desc" },
  { id: "group_date:asc", label: "Älteste zuerst", key: "group_date", dir: "asc" },
  { id: "sharpness_score:desc", label: "Schärfe (am schärfsten zuerst)", key: "sharpness_score", dir: "desc" },
  { id: "exposure_score:desc", label: "Belichtung (am besten zuerst)", key: "exposure_score", dir: "desc" },
  { id: "face_quality_score:desc", label: "Gesichtsqualität (am besten zuerst)", key: "face_quality_score", dir: "desc" },
];

type Props = {
  albumId?: string;
  onSelectPhoto?: (item: FileOverviewItem) => void;
};

export function PhotosView({ albumId, onSelectPhoto }: Props) {
  const embedded = Boolean(albumId) || Boolean(onSelectPhoto);
  const showToast = useToast();

  const [tab, setTab] = useState<Tab>("all");
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  // Files dropped onto the page - they open the upload dialog with these already queued.
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("group_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [items, setItems] = useState<FileOverviewItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);
  const loadingMoreRef = useRef(false);
  const [isReloading, setIsReloading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState<ProgressData | null>(null);
  const [galleryUploadJobs, setGalleryUploadJobs] = useState<GalleryUploadJob[]>([]);
  const requestIdRef = useRef(0);
  const didMountRef = useRef(false);
  const viewerOpenRef = useRef(false);
  viewerOpenRef.current = viewerIndex !== null;
  const isReloadingRef = useRef(true);
  isReloadingRef.current = isReloading;
  const syncNewItemsRef = useRef<() => Promise<void>>(async () => {});

  // The whole page is one big dropzone; not while another dialog/viewer is on top, and not in
  // the embedded variants (album picker etc.), which have no upload of their own.
  const isFileDragging = useFileDrop(
    (files) => {
      setDroppedFiles(files);
      setUploadModalOpen(true);
    },
    !embedded && !uploadModalOpen && viewerIndex === null,
  );

  function buildUrl(skip: number) {
    const params = new URLSearchParams();
    params.set("only_images", "true");
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    if (albumId) params.set("album_id", albumId);
    params.set("skip", String(skip));
    params.set("limit", String(PAGE_SIZE));
    params.set("sort_by", sortKey);
    params.set("sort_dir", sortDir);
    return `/api/files?${params.toString()}`;
  }

  useEffect(() => {
    const firstLoad = !didMountRef.current;
    didMountRef.current = true;
    const requestId = ++requestIdRef.current;
    setIsReloading(true);
    setLoadMoreFailed(false);
    const timer = setTimeout(async () => {
      try {
        const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
        if (requestIdRef.current !== requestId) return;
        setItems(next ?? []);
        setHasMore((next ?? []).length === PAGE_SIZE);
        setSelectedIds(new Set());
      } catch {
        if (requestIdRef.current === requestId) showToast("Fotos konnten nicht geladen werden.", "error");
      } finally {
        if (requestIdRef.current === requestId) setIsReloading(false);
      }
    }, firstLoad ? 0 : 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagFilter.join(","), sortKey, sortDir, albumId]);

  useEffect(() => {
    browserApiFetch<string[]>("/api/files/tags").then((tags) => setTagSuggestions(tags ?? [])).catch(() => {});
  }, []);

  async function loadMore() {
    if (loadingMoreRef.current || isReloading || !hasMore) return;
    const requestId = requestIdRef.current;
    loadingMoreRef.current = true;
    setIsLoadingMore(true);
    setLoadMoreFailed(false);
    try {
      const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(items.length));
      if (requestId !== requestIdRef.current) return;
      // Offset paging overlaps when rows are inserted above the cursor (e.g. a fresh upload
      // sorts to the top and shifts everything down), so the next page can repeat items
      // already shown - drop those, or React sees two children with the same key.
      setItems((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...current, ...(next ?? []).filter((item) => !known.has(item.id))];
      });
      setHasMore((next ?? []).length === PAGE_SIZE);
    } catch {
      if (requestId === requestIdRef.current) {
        setLoadMoreFailed(true);
        showToast("Weitere Fotos konnten nicht geladen werden. Bitte erneut versuchen.", "error");
      }
    } finally {
      loadingMoreRef.current = false;
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore: hasMore && !loadMoreFailed && tab === "all",
    isLoading: isLoadingMore || isReloading,
    onLoadMore: () => void loadMore(),
  });

  function reload() {
    // Invalidates any in-flight filter-change response before re-fetching directly, so a
    // slow earlier request can't overwrite this refresh's result.
    const requestId = ++requestIdRef.current;
    void (async () => {
      try {
        const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
        if (requestIdRef.current !== requestId) return;
        setItems(next ?? []);
        setHasMore((next ?? []).length === PAGE_SIZE);
        setLoadMoreFailed(false);
        setSelectedIds(new Set());
      } catch {
        if (requestIdRef.current === requestId) showToast("Fotos konnten nicht neu geladen werden.", "error");
      }
    })();
  }

  // Silent background sync: fetches the first page with the current filters and adds only the
  // items that aren't shown yet (see mergeNewItems) - no skeleton, no list replacement, no
  // toast, selection and scroll position stay as they are. Skipped while something else is
  // touching the list; the viewer works on an index into `items`, so nothing may be inserted
  // in front of it while it's open. The next tick picks up whatever was missed.
  async function syncNewItems() {
    if (isReloadingRef.current || loadingMoreRef.current || viewerOpenRef.current) return;
    const requestId = requestIdRef.current;
    try {
      const latest = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
      if (!latest || requestIdRef.current !== requestId || loadingMoreRef.current || viewerOpenRef.current) return;
      setItems((current) => mergeNewItems(current, latest));
    } catch {
      // Transient - the next tick tries again; a background sync has no error UI.
    }
  }
  syncNewItemsRef.current = syncNewItems;

  useEffect(() => {
    if (tab !== "all") return;
    const tick = () => {
      if (document.visibilityState === "visible") void syncNewItemsRef.current();
    };
    const timer = setInterval(tick, SYNC_INTERVAL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [tab]);

  // Photos deleted from another tab of this page (Ähnliche): the gallery list stays mounted
  // underneath, so drop them right away instead of showing them until the next reload.
  function handleDeletedElsewhere(deletedIds: string[]) {
    const gone = new Set(deletedIds);
    setItems((current) => (current.some((item) => gone.has(item.id)) ? current.filter((item) => !gone.has(item.id)) : current));
    setSelectedIds((current) => (Array.from(current).some((id) => gone.has(id)) ? new Set(Array.from(current).filter((id) => !gone.has(id))) : current));
  }

  function toggleSelect(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  useEffect(() => {
    if (selectedIds.size === 0 || viewerIndex !== null) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setSelectedIds(new Set());
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedIds.size, viewerIndex]);

  async function handleAlbumScopedToggleBest(item: FileOverviewItem) {
    if (!albumId) return;
    const nextOverride = item.is_best ? "exclude" : "include";
    try {
      await browserApiFetch(`/api/files/albums/${albumId}/items/${item.id}/best`, {
        method: "PATCH",
        body: JSON.stringify({ best_override: nextOverride }),
      });
      setItems((current) => current.map((current_item) => (current_item.id === item.id ? { ...current_item, is_best: nextOverride === "include" } : current_item)));
    } catch {
      showToast("Best-of-Status konnte nicht geändert werden.", "error");
    }
  }

  async function handleUnscopedToggleBest(item: FileOverviewItem) {
    const nextOverride = item.is_best ? "exclude" : "include";
    try {
      await browserApiFetch(`/api/files/${item.id}/best`, { method: "PATCH", body: JSON.stringify({ best_override: nextOverride }) });
      setItems((current) => current.map((current_item) => (current_item.id === item.id ? { ...current_item, is_best: nextOverride === "include" } : current_item)));
    } catch {
      showToast("Dieses Foto gehört zu keinem Album - Best-of ist nur innerhalb eines Albums möglich.", "error");
    }
  }

  function handleTagsSaved(itemId: string, tags: string[]) {
    setItems((current) => current.map((item) => (item.id === itemId ? { ...item, tags } : item)));
    setTagSuggestions((current) => Array.from(new Set([...current, ...tags])).sort((a, b) => a.localeCompare(b)));
  }

  function handleGalleryUploadQueued() {
    // The actual result (imported items/errors) only arrives later, once the background
    // job finishes - see handleGalleryUploadJobDone, wired to GalleryUploadProgress below.
    showToast("Wird hochgeladen und im Hintergrund verarbeitet…", "info");
  }

  function handleGalleryUploadJobDone(job: GalleryUploadJobDetail) {
    const uploaded = job.imported_items;
    const errors = job.errors;
    if (uploaded.length > 0) {
      if (albumId) {
        void browserApiFetch(`/api/files/albums/${albumId}/items`, { method: "POST", body: JSON.stringify({ file_ids: uploaded.map((item) => item.id) }) })
          .then(() => syncNewItems())
          .catch(() => showToast("Bilder hochgeladen, aber Zuordnung zum Album fehlgeschlagen.", "error"));
      } else {
        void syncNewItems();
      }
      setTagSuggestions((current) => Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b)));
      showToast(uploaded.length === 1 ? "1 Bild hochgeladen." : `${uploaded.length} Bilder hochgeladen.`, "success");
    }
    if (errors.length > 0) showToast(errors.join(" · "), uploaded.length > 0 ? "info" : "error");
    if (job.error) showToast(job.error, "error");
  }

  const grouped = sortKey === "group_date";

  return (
    <div className="grid grid-tight">
      {!embedded && (
        <>
          <div className="page-header">
            <div>
              <h1 className="page-title">Fotos</h1>
              <p className="muted">
                Alle Fotos dieses Mandanten - aus Protokollen, Abgaben und direkt hochgeladenen Galerie-Bildern.
                {tab === "all" && ` ${items.length} geladen.`}
              </p>
            </div>
            <div className="table-toolbar-actions">
              {analysisProgress && analysisProgress.pending_images > 0 && (
                <span className="pill">Analyse läuft · {analysisProgress.active_job_image_count || analysisProgress.pending_images} Bilder</span>
              )}
              {galleryUploadJobs.length > 0 && (
                <span className="pill">
                  Galerie-Upload läuft · {galleryUploadJobs.reduce((sum, job) => sum + job.processed_files, 0)}
                  {galleryUploadJobs.every((job) => job.total_files !== null)
                    ? ` von ${galleryUploadJobs.reduce((sum, job) => sum + (job.total_files ?? 0), 0)}`
                    : ""}{" "}
                  Bildern
                </span>
              )}
              <button type="button" className="button-inline" onClick={() => {
                setDroppedFiles([]);
                setUploadModalOpen(true);
              }}>
                + Bilder hochladen
              </button>
            </div>
          </div>
          <div className="list-filter-row list-filter-row-compact">
            <FilterTabs
              options={[
                { value: "all", label: "Alle Fotos" },
                { value: "albums", label: "Alben" },
                { value: "similar", label: "Ähnliche" },
              ]}
              value={tab}
              onChange={setTab}
            />
            {tab !== "albums" && (
              <div className="list-filter-search">
                <SearchInput value={search} onChange={setSearch} placeholder="Fotos durchsuchen" />
              </div>
            )}
            {tab === "all" && !onSelectPhoto && (
              <SearchableSelect
                className="files-sort-select"
                options={SORT_OPTIONS}
                getId={(option) => option.id}
                getLabel={(option) => option.label}
                value={`${sortKey}:${sortDir}`}
                onChange={(option) => {
                  if (!option) return;
                  setSortKey(option.key);
                  setSortDir(option.dir);
                }}
              />
            )}
            {tab !== "albums" && (
              <div className="list-filter-tags">
                <TagInput value={tagFilter.join(",")} onChange={(value) => setTagFilter(value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [])} suggestions={tagSuggestions} placeholder="Tag wählen oder eingeben…" />
              </div>
            )}
          </div>
        </>
      )}

      {tab === "albums" && !embedded ? (
        <PhotoAlbums />
      ) : tab === "similar" && !embedded ? (
        <PhotoSimilarSeries search={search} tagFilter={tagFilter} onDeleted={handleDeletedElsewhere} />
      ) : (
        <>
          {!embedded && <PhotoAnalysisProgress onUpdate={setAnalysisProgress} />}
          {!embedded && <GalleryUploadProgress onUpdate={setGalleryUploadJobs} onJobDone={handleGalleryUploadJobDone} />}
          {embedded && (
            <div className="list-filter-row list-filter-row-compact">
              <div className="list-filter-search">
                <SearchInput value={search} onChange={setSearch} placeholder="Fotos durchsuchen" />
              </div>
              {!onSelectPhoto && (
                <SearchableSelect
                  className="files-sort-select"
                  options={SORT_OPTIONS}
                  getId={(option) => option.id}
                  getLabel={(option) => option.label}
                  value={`${sortKey}:${sortDir}`}
                  onChange={(option) => {
                    if (!option) return;
                    setSortKey(option.key);
                    setSortDir(option.dir);
                  }}
                />
              )}
              <div className="list-filter-tags">
                <TagInput value={tagFilter.join(",")} onChange={(value) => setTagFilter(value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [])} suggestions={tagSuggestions} placeholder="Tag wählen oder eingeben…" />
              </div>
            </div>
          )}

          {!onSelectPhoto && selectedIds.size > 0 && (
            <PhotoBulkBar
              selectedIds={Array.from(selectedIds)}
              tagSuggestions={tagSuggestions}
              onClearSelection={() => setSelectedIds(new Set())}
              onDone={() => reload()}
            />
          )}

          {items.length === 0 && isReloading ? (
            <div className="photo-loading-grid" role="status" aria-label="Fotos werden geladen">
              {Array.from({ length: 18 }, (_, index) => (
                <div key={index} className="photo-tile" aria-hidden="true">
                  <div className="photo-tile-preview" style={{ aspectRatio: 4 / 3 }} />
                </div>
              ))}
            </div>
          ) : items.length === 0 ? (
            <p className="muted">Keine Fotos gefunden.</p>
          ) : onSelectPhoto ? (
            <div className="photo-grid">
              {items.map((item) => (
                <div key={item.id}>
                  <button type="button" className="button-inline" onClick={() => onSelectPhoto(item)}>Zum Album hinzufügen</button>
                  <img
                    alt={item.original_name}
                    src={item.thumbnail_url ?? item.content_url}
                    loading="lazy"
                    decoding="async"
                    className={item.width && item.height ? "photo-tile-img photo-tile-img-fitted" : "photo-tile-img"}
                    style={item.width && item.height ? { aspectRatio: item.width / item.height } : undefined}
                  />
                </div>
              ))}
            </div>
          ) : (
            <PhotoDateGroups
              items={items}
              grouped={grouped && !albumId}
              selectedIds={selectedIds}
              onOpen={(item) => setViewerIndex(items.findIndex((current) => current.id === item.id))}
              onToggleSelect={toggleSelect}
            />
          )}

          {hasMore && (
            <div className="load-more-row" ref={loadMoreSentinelRef}>
              {isLoadingMore ? <span className="muted">Lädt weitere Fotos…</span> : (
                <button type="button" className="button-inline button-ghost" disabled={isReloading} onClick={() => void loadMore()}>
                  {loadMoreFailed ? "Erneut versuchen" : `Mehr laden (${items.length} geladen)`}
                </button>
              )}
            </div>
          )}
        </>
      )}

      {viewerIndex !== null && (
        <PhotoViewer
          items={items}
          index={viewerIndex}
          onIndexChange={setViewerIndex}
          onClose={() => setViewerIndex(null)}
          onToggleBest={albumId ? handleAlbumScopedToggleBest : handleUnscopedToggleBest}
          onTagsSaved={handleTagsSaved}
        />
      )}

      {uploadModalOpen && (
        <GalleryUploadModal
          tagSuggestions={tagSuggestions}
          initialFiles={droppedFiles}
          onClose={() => setUploadModalOpen(false)}
          onQueued={handleGalleryUploadQueued}
        />
      )}

      <FileDropOverlay active={isFileDragging} title="Zum Hochladen loslassen" hint="Bilder oder ZIP-Dateien - danach stellst du den Upload ein." />
    </div>
  );
}
