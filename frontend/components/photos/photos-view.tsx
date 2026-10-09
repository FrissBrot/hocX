"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { AlbumReleaseNotice } from "./album-share-release";
import { GalleryUploadModal } from "./gallery-upload-modal";
import { GalleryUploadProgress } from "./gallery-upload-progress";
import { mergeNewItems } from "./merge-new-items";
import { PhotoAlbums } from "./photo-albums";
import { PhotoAnalysisProgress } from "./photo-analysis-progress";
import { PhotoBulkBar } from "./photo-bulk-bar";
import { PhotoDateGroups } from "./photo-date-groups";
import { PhotoSimilarGroups } from "./photo-similar-groups";
import { PhotoSimilarSeries } from "./photo-similar-series";
import { PhotoViewer } from "./photo-viewer";
import { EmptyState } from "@/components/ui/empty-state";
import { FileDropOverlay } from "@/components/ui/file-drop-overlay";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { MobileFab, MobileSegmented } from "@/components/mobile/mobile-ui";
import { browserApiFetch } from "@/lib/api/client";
import { useFileDrop } from "@/lib/hooks/use-file-drop";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import {
  AlbumPendingRelease,
  FileOverviewItem,
  GalleryUploadJob,
  GalleryUploadJobDetail,
  PhotoAnalysisProgress as ProgressData,
} from "@/types/api";

const PAGE_SIZE = 60;
const SYNC_INTERVAL_MS = 15000;

type SortKey = "group_date" | "created_at" | "sharpness_score" | "exposure_score" | "face_quality_score";
type Tab = "all" | "albums" | "duplicates" | "series";

type SortOption = { id: string; label: string; key: SortKey; dir: "asc" | "desc" };

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function sortOptions(t: TFunc): SortOption[] {
  return [
    { id: "group_date:desc", label: t("sortOptions.newest"), key: "group_date", dir: "desc" },
    { id: "group_date:asc", label: t("sortOptions.oldest"), key: "group_date", dir: "asc" },
    { id: "sharpness_score:desc", label: t("sortOptions.sharpness"), key: "sharpness_score", dir: "desc" },
    { id: "exposure_score:desc", label: t("sortOptions.exposure"), key: "exposure_score", dir: "desc" },
    { id: "face_quality_score:desc", label: t("sortOptions.faceQuality"), key: "face_quality_score", dir: "desc" },
  ];
}

type Props = {
  albumId?: string;
  // Albumansicht des Besitzers: nur die noch nicht freigegebenen Fotos zeigen.
  sharePendingOnly?: boolean;
  // Nach einer Freigabe aus dieser Ansicht (Albumzähler/Hinweis neu laden).
  onReleased?: () => void;
  // Mobile-Oberflaeche: Kopf kommt von MobilePhotos, Upload als schwebender Plus-Button,
  // Reiter als Segment, Sortierung/Tag-Filter entfallen (Suche bleibt).
  mobile?: boolean;
};

export function PhotosView({ albumId, sharePendingOnly = false, onReleased, mobile = false }: Props) {
  const t = useTranslations("photos.view");
  const tMobile = useTranslations("mobile");
  const embedded = Boolean(albumId);
  const router = useRouter();
  const showToast = useToast();
  const SORT_OPTIONS = sortOptions(t);

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
  const [queuedUploadId, setQueuedUploadId] = useState<string | undefined>();
  const [galleryUploadJobs, setGalleryUploadJobs] = useState<GalleryUploadJob[]>([]);
  // Eigene geteilte Alben mit automatisch einsortierten, noch nicht freigegebenen Fotos.
  const [pendingReleases, setPendingReleases] = useState<AlbumPendingRelease[]>([]);
  const [openAlbumId, setOpenAlbumId] = useState<string | null>(null);
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
    if (albumId && sharePendingOnly) params.set("share_pending", "true");
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
        if (requestIdRef.current === requestId) showToast(t("loadError"), "error");
      } finally {
        if (requestIdRef.current === requestId) setIsReloading(false);
      }
    }, firstLoad ? 0 : 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagFilter.join(","), sortKey, sortDir, albumId, sharePendingOnly]);

  function loadPendingReleases() {
    if (embedded) return;
    browserApiFetch<AlbumPendingRelease[]>("/api/files/album-pending-releases")
      .then((data) => setPendingReleases(data ?? []))
      .catch(() => {});
  }

  useEffect(() => {
    loadPendingReleases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  async function releaseSelected() {
    if (!albumId || selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    try {
      const result = await browserApiFetch<{ released: number }>(`/api/files/albums/${albumId}/release`, {
        method: "POST",
        body: JSON.stringify({ file_ids: ids }),
      });
      const released = result?.released ?? 0;
      showToast(released > 0 ? t("releasedToast", { count: released }) : t("alreadyReleasedToast"), "success");
      reload();
      onReleased?.();
    } catch {
      showToast(t("releaseError"), "error");
    }
  }

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
        showToast(t("loadMoreError"), "error");
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
        if (requestIdRef.current === requestId) showToast(t("reloadError"), "error");
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

  function toggleGroup(ids: string[]) {
    setSelectedIds((current) => {
      const next = new Set(current);
      const allSelected = ids.every((id) => current.has(id));
      for (const id of ids) {
        if (allSelected) next.delete(id);
        else next.add(id);
      }
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
      showToast(t("bestError"), "error");
    }
  }

  async function handleUnscopedToggleBest(item: FileOverviewItem) {
    const nextOverride = item.is_best ? "exclude" : "include";
    try {
      await browserApiFetch(`/api/files/${item.id}/best`, { method: "PATCH", body: JSON.stringify({ best_override: nextOverride }) });
      setItems((current) => current.map((current_item) => (current_item.id === item.id ? { ...current_item, is_best: nextOverride === "include" } : current_item)));
    } catch {
      showToast(t("bestUnscopedError"), "error");
    }
  }

  function handleTagsSaved(itemId: string, tags: string[]) {
    setItems((current) => current.map((item) => (item.id === itemId ? { ...item, tags } : item)));
    setTagSuggestions((current) => Array.from(new Set([...current, ...tags])).sort((a, b) => a.localeCompare(b)));
  }

  function handleGalleryUploadQueued(job: GalleryUploadJob) {
    setQueuedUploadId(job.id);
    // The actual result (imported items/errors) only arrives later, once the background
    // job finishes - see handleGalleryUploadJobDone, wired to GalleryUploadProgress below.
    showToast(t("uploadQueuedToast"), "info");
  }

  function handleGalleryUploadJobDone(job: GalleryUploadJobDetail) {
    const uploaded = job.imported_items;
    const errors = job.errors;
    if (uploaded.length > 0) {
      if (albumId) {
        void browserApiFetch(`/api/files/albums/${albumId}/items`, { method: "POST", body: JSON.stringify({ file_ids: uploaded.map((item) => item.id) }) })
          .then(() => syncNewItems())
          .catch(() => showToast(t("uploadAlbumAssignError"), "error"));
      } else {
        void syncNewItems();
      }
      setTagSuggestions((current) => Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b)));
      showToast(t("uploadedToast", { count: uploaded.length }), "success");
    }
    if (errors.length > 0) showToast(errors.join(" · "), uploaded.length > 0 ? "info" : "error");
    if (job.error) showToast(job.error, "error");
    loadPendingReleases();
  }

  const pendingReleaseTotal = pendingReleases.reduce((sum, row) => sum + row.pending_count, 0);

  const grouped = sortKey === "group_date";

  return (
    <div className="grid grid-tight photos-overview">
      {!embedded && (
        <>
          {!mobile ? (
          <div className="page-header photos-page-header">
            <div>
              <h1 className="page-title">{t("pageTitle")}</h1>
              <p className="muted">
                {t("description")}
                {tab === "all" && ` ${analysisProgress?.total_images ? t("loadedOfTotal", { count: items.length, total: analysisProgress.total_images }) : t("loadedSuffix", { count: items.length })}`}
              </p>
            </div>
            <div className="table-toolbar-actions photos-header-actions">
              {analysisProgress && analysisProgress.pending_images > 0 && (
                <span className="pill">{t("analysisPill", { count: analysisProgress.active_job_image_count || analysisProgress.pending_images })}</span>
              )}
              {galleryUploadJobs.length > 0 && (
                <span className="pill">
                  {galleryUploadJobs.every((job) => job.total_files !== null)
                    ? t("uploadPillTotal", {
                        processed: galleryUploadJobs.reduce((sum, job) => sum + job.processed_files, 0),
                        total: galleryUploadJobs.reduce((sum, job) => sum + (job.total_files ?? 0), 0),
                      })
                    : t("uploadPillNoTotal", { processed: galleryUploadJobs.reduce((sum, job) => sum + job.processed_files, 0) })}
                </span>
              )}
              <button type="button" className="button-primary photos-upload-button" onClick={() => {
                setDroppedFiles([]);
                setUploadModalOpen(true);
              }}>
                {t("uploadButton")}
              </button>
            </div>
          </div>
          ) : (
            <>
              {analysisProgress && analysisProgress.pending_images > 0 ? (
                <span className="pill photos-mobile-pill">{t("analysisPill", { count: analysisProgress.active_job_image_count || analysisProgress.pending_images })}</span>
              ) : null}
              <MobileFab
                label={tMobile("photos.fab")}
                onClick={() => {
                  setDroppedFiles([]);
                  setUploadModalOpen(true);
                }}
              />
            </>
          )}
          {pendingReleaseTotal > 0 && (
            <AlbumReleaseNotice
              message={
                pendingReleases.length === 1
                  ? t("singleAlbumNotice", { count: pendingReleaseTotal, albumName: pendingReleases[0].album_name })
                  : t("multiAlbumNotice", { count: pendingReleaseTotal, albumCount: pendingReleases.length })
              }
            >
              {pendingReleases.slice(0, 3).map((row) => (
                <button
                  key={row.album_id}
                  type="button"
                  className="album-release-notice-link"
                  onClick={() => {
                    setTab("albums");
                    setOpenAlbumId(row.album_id);
                  }}
                >
                  {pendingReleases.length === 1 ? t("reviewLink") : t("albumLinkWithCount", { name: row.album_name, count: row.pending_count })}
                </button>
              ))}
              {pendingReleases.length > 3 && (
                <button type="button" className="album-release-notice-link" onClick={() => setTab("albums")}>
                  {t("allAlbumsLink")}
                </button>
              )}
            </AlbumReleaseNotice>
          )}
          <div className="list-filter-row list-filter-row-compact photos-filter-row">
            {mobile ? (
              <MobileSegmented<Tab>
                ariaLabel={t("pageTitle")}
                value={tab}
                onChange={setTab}
                options={[
                  { value: "all", label: t("tabs.all") },
                  { value: "albums", label: t("tabs.albums") },
                  { value: "duplicates", label: t("tabs.duplicates") },
                  { value: "series", label: t("tabs.series") },
                ]}
              />
            ) : (
              <FilterTabs
                options={[
                  { value: "all", label: t("tabs.all") },
                  { value: "albums", label: t("tabs.albums") },
                  { value: "duplicates", label: t("tabs.duplicates") },
                  { value: "series", label: t("tabs.series") },
                ]}
                value={tab}
                onChange={setTab}
              />
            )}
            {tab !== "albums" && (
              <div className="list-filter-search">
                <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
              </div>
            )}
            {tab === "all" && !mobile && (
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
            {tab !== "albums" && !mobile && (
              <div className="list-filter-tags">
                <TagInput value={tagFilter.join(",")} onChange={(value) => setTagFilter(value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [])} suggestions={tagSuggestions} placeholder={t("tagPlaceholder")} />
              </div>
            )}
          </div>
        </>
      )}

      {tab === "albums" && !embedded ? (
        <PhotoAlbums
          openAlbumId={openAlbumId}
          onOpenedAlbum={() => setOpenAlbumId(null)}
          onReleaseChanged={loadPendingReleases}
        />
      ) : tab === "duplicates" && !embedded ? (
        <PhotoSimilarSeries search={search} tagFilter={tagFilter} onDeleted={handleDeletedElsewhere} />
      ) : tab === "series" && !embedded ? (
        <PhotoSimilarGroups search={search} tagFilter={tagFilter} onDeleted={handleDeletedElsewhere} />
      ) : (
        <>
          {!embedded && <PhotoAnalysisProgress onUpdate={setAnalysisProgress} />}
          {!embedded && <GalleryUploadProgress queuedJobId={queuedUploadId} onUpdate={setGalleryUploadJobs} onJobDone={handleGalleryUploadJobDone} />}
          {embedded && (
            <div className="list-filter-row list-filter-row-compact photos-filter-row">
              <div className="list-filter-search">
                <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
              </div>
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
              <div className="list-filter-tags">
                <TagInput value={tagFilter.join(",")} onChange={(value) => setTagFilter(value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [])} suggestions={tagSuggestions} placeholder={t("tagPlaceholder")} />
              </div>
            </div>
          )}

          {selectedIds.size > 0 && (
            <PhotoBulkBar
              selectedIds={Array.from(selectedIds)}
              selectedItems={items.filter((item) => selectedIds.has(item.id))}
              onSelectAll={() => setSelectedIds(new Set(items.map((item) => item.id)))}
              tagSuggestions={tagSuggestions}
              onClearSelection={() => setSelectedIds(new Set())}
              onDone={() => reload()}
              onReleaseSelected={
                albumId && items.some((item) => item.share_pending && selectedIds.has(item.id)) ? () => void releaseSelected() : undefined
              }
            />
          )}

          {items.length === 0 && isReloading ? (
            <div className="photo-loading-grid" role="status" aria-label={t("loadingAriaLabel")}>
              {Array.from({ length: 18 }, (_, index) => (
                <div key={index} className="photo-tile" aria-hidden="true">
                  <div className="photo-tile-preview" style={{ aspectRatio: 4 / 3 }} />
                </div>
              ))}
            </div>
          ) : items.length === 0 && !embedded && !search.trim() && tagFilter.length === 0 ? (
            <EmptyState
              icon="image"
              title={t("emptyTitle")}
              description={t("emptyDescription")}
              actions={
                <>
                  <button
                    type="button"
                    className="button-primary"
                    onClick={() => {
                      setDroppedFiles([]);
                      setUploadModalOpen(true);
                    }}
                  >
                    {t("uploadButton")}
                  </button>
                  <button type="button" className="button-secondary" onClick={() => router.push("/submission-assignments")}>
                    {t("createAssignmentButton")}
                  </button>
                </>
              }
              hint={
                <div className="empty-state-sources">
                  <div>
                    <strong>{t("emptyHint.protocolsTitle")}</strong>
                    <span>{t("emptyHint.protocolsDesc")}</span>
                  </div>
                  <div>
                    <strong>{t("emptyHint.submissionsTitle")}</strong>
                    <span>{t("emptyHint.submissionsDesc")}</span>
                  </div>
                  <div>
                    <strong>{t("emptyHint.uploadsTitle")}</strong>
                    <span>{t("emptyHint.uploadsDesc")}</span>
                  </div>
                </div>
              }
            />
          ) : items.length === 0 ? (
            <p className="muted">{t("noResults")}</p>
          ) : (
            <PhotoDateGroups
              items={items}
              grouped={grouped && !albumId}
              selectedIds={selectedIds}
              onOpen={(item) => setViewerIndex(items.findIndex((current) => current.id === item.id))}
              onToggleSelect={toggleSelect}
              onToggleGroup={toggleGroup}
            />
          )}

          {hasMore && (
            <div className="load-more-row" ref={loadMoreSentinelRef}>
              {isLoadingMore ? (
                <span className="photo-loading-glow" role="status" aria-label={t("loadingMoreAriaLabel")}>
                  <span aria-hidden="true" />
                  <span aria-hidden="true" />
                  <span aria-hidden="true" />
                </span>
              ) : (
                <button type="button" className="button-secondary button-ghost" disabled={isReloading} onClick={() => void loadMore()}>
                  {loadMoreFailed ? t("retry") : t("loadMore", { count: items.length })}
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

      <FileDropOverlay active={isFileDragging} title={t("dropOverlayTitle")} hint={t("dropOverlayHint")} />
    </div>
  );
}
