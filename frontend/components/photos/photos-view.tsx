"use client";

import { useEffect, useRef, useState } from "react";

import { GalleryUploadModal } from "./gallery-upload-modal";
import { PhotoAlbums } from "./photo-albums";
import { PhotoAnalysisProgress } from "./photo-analysis-progress";
import { PhotoBulkBar } from "./photo-bulk-bar";
import { PhotoDateGroups } from "./photo-date-groups";
import { PhotoSimilarSeries } from "./photo-similar-series";
import { PhotoViewer } from "./photo-viewer";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { FileOverviewItem, PhotoAnalysisProgress as ProgressData } from "@/types/api";

const PAGE_SIZE = 60;

type SortKey = "group_date" | "created_at" | "sharpness_score" | "exposure_score" | "face_quality_score";
type Tab = "all" | "albums" | "similar";

type Props = {
  albumId?: string;
  onSelectPhoto?: (item: FileOverviewItem) => void;
};

export function PhotosView({ albumId, onSelectPhoto }: Props) {
  const embedded = Boolean(albumId) || Boolean(onSelectPhoto);
  const showToast = useToast();

  const [tab, setTab] = useState<Tab>("all");
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("group_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [items, setItems] = useState<FileOverviewItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isReloading, setIsReloading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState<ProgressData | null>(null);
  const requestIdRef = useRef(0);
  const didMountRef = useRef(false);

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
    const requestId = requestIdRef.current;
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(items.length));
      if (requestId !== requestIdRef.current) return;
      setItems((current) => [...current, ...(next ?? [])]);
      setHasMore((next ?? []).length === PAGE_SIZE);
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore: hasMore && tab === "all",
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
        setSelectedIds(new Set());
      } catch {
        if (requestIdRef.current === requestId) showToast("Fotos konnten nicht neu geladen werden.", "error");
      }
    })();
  }

  function toggleSelect(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

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

  function handleUploaded(uploaded: FileOverviewItem[], errors: string[]) {
    if (uploaded.length > 0) {
      if (albumId) {
        void browserApiFetch(`/api/files/albums/${albumId}/items`, { method: "POST", body: JSON.stringify({ file_ids: uploaded.map((item) => item.id) }) })
          .then(() => reload())
          .catch(() => showToast("Bilder hochgeladen, aber Zuordnung zum Album fehlgeschlagen.", "error"));
      } else {
        reload();
      }
      setTagSuggestions((current) => Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b)));
      showToast(uploaded.length === 1 ? "1 Bild hochgeladen." : `${uploaded.length} Bilder hochgeladen.`, "success");
    }
    if (errors.length > 0) showToast(errors.join(" · "), uploaded.length > 0 ? "info" : "error");
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
              <button type="button" className="button-inline" onClick={() => setUploadModalOpen(true)}>
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
              <select className="files-sort-select" value={`${sortKey}:${sortDir}`} onChange={(event) => {
                const [key, dir] = event.target.value.split(":") as [SortKey, "asc" | "desc"];
                setSortKey(key);
                setSortDir(dir);
              }}>
                <option value="group_date:desc">Neueste zuerst</option>
                <option value="group_date:asc">Älteste zuerst</option>
                <option value="sharpness_score:desc">Schärfe (am schärfsten zuerst)</option>
                <option value="exposure_score:desc">Belichtung (am besten zuerst)</option>
                <option value="face_quality_score:desc">Gesichtsqualität (am besten zuerst)</option>
              </select>
            )}
            {tab !== "albums" && (
              <div className="list-filter-tags">
                <TagInput value={tagFilter.join(",")} onChange={(value) => setTagFilter(value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [])} suggestions={tagSuggestions} placeholder="Tag wählen oder eingeben…" />
              </div>
            )}
          </div>
        </>
      )}
      {embedded && albumId && (
        <button type="button" className="button-inline" onClick={() => setUploadModalOpen(true)}>+ Bilder hochladen</button>
      )}

      {tab === "albums" && !embedded ? (
        <PhotoAlbums />
      ) : tab === "similar" && !embedded ? (
        <PhotoSimilarSeries search={search} tagFilter={tagFilter} />
      ) : (
        <>
          {!embedded && <PhotoAnalysisProgress onUpdate={setAnalysisProgress} />}
          {embedded && (
            <div className="list-filter-row list-filter-row-compact">
              <div className="list-filter-search">
                <SearchInput value={search} onChange={setSearch} placeholder="Fotos durchsuchen" />
              </div>
              {!onSelectPhoto && (
                <select className="files-sort-select" value={`${sortKey}:${sortDir}`} onChange={(event) => {
                  const [key, dir] = event.target.value.split(":") as [SortKey, "asc" | "desc"];
                  setSortKey(key);
                  setSortDir(dir);
                }}>
                  <option value="group_date:desc">Neueste zuerst</option>
                  <option value="group_date:asc">Älteste zuerst</option>
                  <option value="sharpness_score:desc">Schärfe (am schärfsten zuerst)</option>
                  <option value="exposure_score:desc">Belichtung (am besten zuerst)</option>
                  <option value="face_quality_score:desc">Gesichtsqualität (am besten zuerst)</option>
                </select>
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
                <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()}>
                  Mehr laden ({items.length} geladen)
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
        <GalleryUploadModal tagSuggestions={tagSuggestions} onClose={() => setUploadModalOpen(false)} onUploaded={handleUploaded} />
      )}
    </div>
  );
}
