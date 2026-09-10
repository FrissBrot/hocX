"use client";

import { PhotoAlbums } from "./photo-albums";
import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { LightboxImage } from "@/components/ui/lightbox-image";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem, FileOverviewSource, PhotoAnalysisJob, SimilarityGroup, StoredFileMetadata } from "@/types/api";

const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.zip";

const PAGE_SIZE = 60;

type Mode = "photos" | "files";
type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes" | "sharpness_score" | "exposure_score" | "face_quality_score";

const SOURCE_OPTIONS: Record<Mode, { value: SourceFilter; label: string }[]> = {
  photos: [],
  files: [
    { value: "all", label: "Alle Quellen" },
    { value: "protocol_image", label: "Protokolle" },
    { value: "word_import", label: "Word-Import" },
    { value: "submission_upload", label: "Abgaben" },
  ],
};

const SOURCE_LABEL: Record<FileOverviewSource, string> = {
  protocol_image: "Protokoll",
  word_import: "Word-Import",
  submission_upload: "Abgabe",
  gallery_upload: "Galerie",
};

const SOURCE_BADGE_VARIANT: Record<FileOverviewSource, BadgeVariant> = {
  protocol_image: "info",
  word_import: "neutral",
  submission_upload: "success",
  gallery_upload: "warning",
};

type Props = {
  mode: Mode;
  initialItems: FileOverviewItem[];
  albumId?: string;
  onSelectPhoto?: (item: FileOverviewItem) => void;
};

export function FilesView({ mode, initialItems, albumId, onSelectPhoto }: Props) {
  const [photoTab, setPhotoTab] = useState<"all" | "albums">("all");
  const router = useRouter();
  const showToast = useToast();
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [similarityModalOpen, setSimilarityModalOpen] = useState(false);
  const [analysisModalOpen, setAnalysisModalOpen] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [items, setItems] = useState<FileOverviewItem[]>(initialItems);
  const [hasMore, setHasMore] = useState(initialItems.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isReloading, setIsReloading] = useState(false);
  const [detailItem, setDetailItem] = useState<FileOverviewItem | null>(null);
  const didMountRef = useRef(false);
  const requestIdRef = useRef(0);

  // Same filters as the current list view (minus pagination/sort) - "act on whatever this
  // filtered view currently shows", shared by the similarity-grouping and face-quality-
  // analysis actions below.
  function buildFilterParams() {
    const params = new URLSearchParams();
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    if (albumId) params.set("album_id", albumId);
    return params;
  }

  function buildUrl(skip: number) {
    const params = buildFilterParams();
    params.set("skip", String(skip));
    params.set("limit", String(PAGE_SIZE));
    if (mode === "photos") params.set("only_images", "true");
    if (mode === "files") params.set("exclude_images", "true");
    params.set("sort_by", sortKey);
    params.set("sort_dir", sortDir);
    return `/api/files?${params.toString()}`;
  }

  // Same filters as the current list view (minus pagination/sort/only_images) - "act on
  // whatever this filtered view currently shows", used by the similarity-grouping and
  // face-quality-analysis actions below (both only offered outside an album context, so
  // albumId is never set when buildAnalysisJobBody is actually used - the POST endpoint
  // has no album_id param, unlike the GET ones).
  function buildAnalysisJobBody() {
    return {
      source: sourceFilter !== "all" ? sourceFilter : null,
      search: search.trim() || null,
      tags: tagFilter.length > 0 ? tagFilter : null,
    };
  }

  // Filters are applied server-side (the tenant can have far more files than one page),
  // so every filter change re-queries from skip=0 instead of re-filtering what's loaded -
  // unlike the client-side-only filtering used on smaller lists elsewhere in this app.
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      if (!albumId && !onSelectPhoto) return;
    }
    const requestId = ++requestIdRef.current;
    setIsReloading(true);
    const timer = setTimeout(async () => {
      try {
        const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
        if (requestIdRef.current !== requestId) return;
        setItems(next ?? []);
        setHasMore((next ?? []).length === PAGE_SIZE);
      } catch {
        if (requestIdRef.current === requestId) showToast("Fotos oder Dateien konnten nicht geladen werden.", "error");
      } finally {
        if (requestIdRef.current === requestId) setIsReloading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, search, tagFilter, sortKey, sortDir, albumId]);

  useEffect(() => {
    browserApiFetch<string[]>("/api/files/tags")
      .then((tags) => setTagSuggestions(tags ?? []))
      .catch(() => {});
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
    hasMore: hasMore && photoTab === "all",
    isLoading: isLoadingMore || isReloading,
    onLoadMore: () => void loadMore(),
  });

  function handleTagsSaved(itemId: string, tags: string[]) {
    setItems((current) => current.map((item) => (item.id === itemId ? { ...item, tags } : item)));
    setDetailItem((current) => (current && current.id === itemId ? { ...current, tags } : current));
    setTagSuggestions((current) => Array.from(new Set([...current, ...tags])).sort((a, b) => a.localeCompare(b)));
  }

  function handleUploaded(uploaded: FileOverviewItem[], errors: string[]) {
    if (uploaded.length > 0) {
      if (albumId) {
        void browserApiFetch(`/api/files/albums/${albumId}/items`, { method: "POST", body: JSON.stringify({ file_ids: uploaded.map((item) => item.id) }) })
          .then(() => browserApiFetch<FileOverviewItem[]>(buildUrl(0)))
          .then((next) => { setItems(next ?? []); setHasMore((next ?? []).length === PAGE_SIZE); })
          .catch(() => showToast("Bilder hochgeladen, aber Zuordnung zum Album fehlgeschlagen.", "error"));
      } else {
        void browserApiFetch<FileOverviewItem[]>(buildUrl(0)).then((next) => { setItems(next ?? []); setHasMore((next ?? []).length === PAGE_SIZE); });
      }
      setTagSuggestions((current) =>
        Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b))
      );
      showToast(uploaded.length === 1 ? "1 Bild hochgeladen." : `${uploaded.length} Bilder hochgeladen.`, "success");
    }
    if (errors.length > 0) {
      showToast(errors.join(" · "), uploaded.length > 0 ? "info" : "error");
    }
  }

  return (
    <div className="grid">
      {!albumId && !onSelectPhoto && <div className="page-header">
        <div>
          <h1 className="page-title">{mode === "photos" ? "Fotos" : "Dateien"}</h1>
          <p className="muted">
            {mode === "photos"
              ? "Alle Fotos dieses Mandanten - aus Protokollen, Abgaben und direkt hochgeladenen Galerie-Bildern."
              : "Alle hochgeladenen Nicht-Bild-Dateien dieses Mandanten - aus Protokollen, Word-Importen und Abgaben. Fotos siehe die separate \"Fotos\"-Seite."}
          </p>
        </div>
        {mode === "photos" && (
          <div className="table-toolbar-actions">
            <button type="button" className="button-inline" onClick={() => setUploadModalOpen(true)}>
              + Bilder hochladen
            </button>
            <button type="button" className="button-inline button-ghost" onClick={() => setSimilarityModalOpen(true)}>
              Ähnliche gruppieren
            </button>
            <button type="button" className="button-inline button-ghost" onClick={() => setAnalysisModalOpen(true)}>
              Gesichtsqualität analysieren
            </button>
          </div>
        )}
      </div>}

      {mode === "photos" && !albumId && !onSelectPhoto && <FilterTabs options={[{ value: "all", label: "Alle Fotos" }, { value: "albums", label: "Alben" }]} value={photoTab} onChange={setPhotoTab} />}
      {photoTab === "albums" ? <PhotoAlbums /> : <>
      {albumId && <button type="button" className="button-inline" onClick={() => setUploadModalOpen(true)}>+ Bilder hochladen</button>}
      <div className="list-filter-row">
        {mode === "files" && <FilterTabs
          options={SOURCE_OPTIONS[mode]}
          value={sourceFilter}
          onChange={(value) => setSourceFilter(value as SourceFilter)}
        />}
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={mode === "photos" ? "Fotos durchsuchen" : "Dateien durchsuchen"} />
        </div>
        {mode === "files" && <select
          className="files-sort-select"
          value={`${sortKey}:${sortDir}`}
          onChange={(event) => {
            const [key, dir] = event.target.value.split(":") as [SortKey, "asc" | "desc"];
            setSortKey(key);
            setSortDir(dir);
          }}
        >
          <option value="created_at:desc">Neueste zuerst</option>
          <option value="created_at:asc">Älteste zuerst</option>
          <option value="original_name:asc">Name (A-Z)</option>
          <option value="original_name:desc">Name (Z-A)</option>
          <option value="file_size_bytes:desc">Grösse (gross-klein)</option>
          <option value="file_size_bytes:asc">Grösse (klein-gross)</option>
        </select>}
        {mode === "photos" && !onSelectPhoto && <select
          className="files-sort-select"
          value={`${sortKey}:${sortDir}`}
          onChange={(event) => {
            const [key, dir] = event.target.value.split(":") as [SortKey, "asc" | "desc"];
            setSortKey(key);
            setSortDir(dir);
          }}
        >
          <option value="created_at:desc">Neueste zuerst</option>
          <option value="created_at:asc">Älteste zuerst</option>
          <option value="sharpness_score:desc">Schärfe (am schärfsten zuerst)</option>
          <option value="exposure_score:desc">Belichtung (am besten zuerst)</option>
          <option value="face_quality_score:desc">Gesichtsqualität (am besten zuerst)</option>
        </select>}
      </div>

      <div className="files-tag-filter">
        <span className="files-tag-filter-label">Nach Tags filtern</span>
        <TagInput
          value={tagFilter.join(",")}
          onChange={(value) => setTagFilter(value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [])}
          suggestions={tagSuggestions}
          placeholder="Tag wählen oder eingeben…"
        />
      </div>

      {items.length === 0 && !isReloading ? (
        <p className="muted">{mode === "photos" ? "Keine Fotos gefunden." : "Keine Dateien gefunden."}</p>
      ) : (
        <div className={mode === "photos" ? "files-grid files-grid-photos" : "files-grid"}>
          {items.map((item) => (
            <div key={item.id}>
            {onSelectPhoto && <button type="button" className="button-inline" onClick={() => onSelectPhoto(item)}>Zum Album hinzufügen</button>}
            <FileCard
              key={item.id}
              item={item}
              onNavigate={(href) => router.push(href as Route)}
              onOpenDetail={() => setDetailItem(item)}
              onTagClick={(tag) => setTagFilter((current) => (current.includes(tag) ? current : [...current, tag]))}
            />
            </div>
          ))}
        </div>
      )}

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">Lädt weitere Dateien…</span>
          ) : (
            <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()}>
              Mehr laden ({items.length} geladen)
            </button>
          )}
        </div>
      )}

      </>}

      {detailItem && (
        <FileDetailModal
          item={detailItem}
          tagSuggestions={tagSuggestions}
          onClose={() => setDetailItem(null)}
          onNavigate={(href) => router.push(href as Route)}
          onTagsSaved={(tags) => handleTagsSaved(detailItem.id, tags)}
        />
      )}

      {uploadModalOpen && (
        <GalleryUploadModal
          tagSuggestions={tagSuggestions}
          onClose={() => setUploadModalOpen(false)}
          onUploaded={handleUploaded}
        />
      )}

      {similarityModalOpen && (
        <SimilarityGroupsModal
          filterParams={buildFilterParams()}
          onClose={() => setSimilarityModalOpen(false)}
        />
      )}

      {analysisModalOpen && (
        <AnalysisJobModal
          body={buildAnalysisJobBody()}
          onClose={() => setAnalysisModalOpen(false)}
          onDone={() => {
            showToast("Analyse abgeschlossen - nach Gesichtsqualität sortieren, um die Ergebnisse zu sehen.", "success");
            void browserApiFetch<FileOverviewItem[]>(buildUrl(0)).then((next) => {
              setItems(next ?? []);
              setHasMore((next ?? []).length === PAGE_SIZE);
            });
          }}
        />
      )}
    </div>
  );
}

function GalleryUploadModal({
  tagSuggestions,
  onClose,
  onUploaded,
}: {
  tagSuggestions: string[];
  onClose: () => void;
  onUploaded: (items: FileOverviewItem[], errors: string[]) => void;
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [tagsValue, setTagsValue] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function addFiles(fileList: FileList | File[]) {
    setSelectedFiles((current) => [...current, ...Array.from(fileList)]);
    setError(null);
  }

  function removeFile(index: number) {
    setSelectedFiles((current) => current.filter((_, i) => i !== index));
  }

  async function handleUpload() {
    if (selectedFiles.length === 0 || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      selectedFiles.forEach((file) => body.append("files", file));
      body.append("tags", tagsValue);
      const result = await browserApiFetch<{ items: FileOverviewItem[]; errors: string[] }>("/api/files/gallery-uploads", {
        method: "POST",
        body,
      });
      onUploaded(result?.items ?? [], result?.errors ?? []);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload fehlgeschlagen");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Modal
      open
      title="Bilder hochladen"
      description="Direkt in die Galerie hochladen - auch als ZIP-Archiv, dabei werden nur enthaltene Bilddateien übernommen. Jede Datei durchläuft die Virenprüfung."
      onClose={onClose}
      size="wide"
    >
      <div className="gallery-upload">
        <div
          className={`gallery-upload-dropzone${isDragging ? " gallery-upload-dropzone-active" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files);
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={GALLERY_UPLOAD_ACCEPT}
            hidden
            onChange={(event) => {
              if (event.target.files) addFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <p>Bilder oder ZIP-Dateien hierher ziehen oder klicken zum Auswählen</p>
          <p className="muted">JPEG, PNG, GIF, WebP, BMP, TIFF - oder ein ZIP-Archiv mit Bildern darin</p>
        </div>

        {selectedFiles.length > 0 && (
          <ul className="gallery-upload-file-list">
            {selectedFiles.map((file, index) => (
              <li key={`${file.name}-${index}`}>
                <span className="gallery-upload-file-name" title={file.name}>{file.name}</span>
                <span className="muted">{formatFileSize(file.size)}</span>
                <button type="button" className="button-ghost button-inline" onClick={() => removeFile(index)}>
                  Entfernen
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="gallery-upload-tags">
          <span className="file-detail-tags-label">Tags für diesen Upload</span>
          <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder="Tag hinzufügen…" />
        </div>

        {error && <p className="form-error-banner">{error}</p>}

        <div className="gallery-upload-actions">
          <button type="button" className="button-ghost" onClick={onClose} disabled={uploading}>
            Abbrechen
          </button>
          <button
            type="button"
            className="button-inline"
            onClick={() => void handleUpload()}
            disabled={uploading || selectedFiles.length === 0}
          >
            {uploading
              ? "Lädt hoch…"
              : selectedFiles.length > 0
                ? `${selectedFiles.length} ${selectedFiles.length === 1 ? "Bild" : "Bilder"} hochladen`
                : "Hochladen"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function SimilarityGroupsModal({
  filterParams,
  onClose,
}: {
  filterParams: URLSearchParams;
  onClose: () => void;
}) {
  const [groups, setGroups] = useState<SimilarityGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    browserApiFetch<SimilarityGroup[]>(`/api/files/similarity-groups?${filterParams.toString()}`)
      .then((data) => setGroups(data ?? []))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Gruppen konnten nicht geladen werden."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Singles (nothing similar found) aren't interesting here - this view exists to review
  // near-duplicate clusters, not to re-list every photo.
  const multiGroups = groups?.filter((group) => group.images.length > 1) ?? [];

  return (
    <Modal
      open
      title="Ähnliche Bilder"
      description="Serienaufnahmen und andere sehr ähnliche Bilder, gruppiert per Bildvergleich. Das nach Schärfe/Belichtung beste Bild jeder Gruppe ist markiert."
      onClose={onClose}
      size="wide"
    >
      {error && <p className="form-error-banner">{error}</p>}
      {!groups && !error ? (
        <p className="muted">Gruppiert…</p>
      ) : multiGroups.length === 0 ? (
        <p className="muted">Keine ähnlichen Bilder gefunden.</p>
      ) : (
        <div className="grid">
          {multiGroups.map((group) => (
            <div key={group.best_id}>
              <p className="muted">Gruppe von {group.images.length} ähnlichen Bildern</p>
              <div className="files-grid">
                {group.images.map((image) => {
                  const thumbnailUrl = image.thumbnail_url ? `${browserApiBaseUrl}${image.thumbnail_url}` : `${browserApiBaseUrl}${image.content_url}`;
                  const isBest = image.id === group.best_id;
                  return (
                    <div key={image.id} className="file-card">
                      <a
                        className="file-card-preview file-card-preview-button"
                        href={`${browserApiBaseUrl}${image.content_url}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <img alt={image.original_name} src={thumbnailUrl} loading="lazy" decoding="async" />
                      </a>
                      <div className="file-card-body">
                        <span className="file-card-name" title={image.original_name}>{image.original_name}</span>
                        {isBest && <Badge variant="success">Beste Wahl</Badge>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function AnalysisJobModal({
  body,
  onClose,
  onDone,
}: {
  body: { source: string | null; search: string | null; tags: string[] | null };
  onClose: () => void;
  onDone: () => void;
}) {
  const [job, setJob] = useState<PhotoAnalysisJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    function schedulePoll(jobId: string) {
      pollTimerRef.current = setTimeout(async () => {
        try {
          const updated = await browserApiFetch<PhotoAnalysisJob>(`/api/files/analysis-jobs/${jobId}`);
          if (cancelled || !updated) return;
          setJob(updated);
          if (updated.status === "queued" || updated.status === "running") {
            schedulePoll(jobId);
          } else if (updated.status === "done") {
            onDone();
          }
        } catch {
          if (!cancelled) setError("Status konnte nicht abgerufen werden.");
        }
      }, 2000);
    }

    browserApiFetch<PhotoAnalysisJob>("/api/files/analysis-jobs", { method: "POST", body: JSON.stringify(body) })
      .then((created) => {
        if (cancelled || !created) return;
        setJob(created);
        schedulePoll(created.id);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Auftrag konnte nicht gestartet werden.");
      });

    return () => {
      cancelled = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Modal
      open
      title="Gesichtsqualität analysieren"
      description="Läuft im Hintergrund und kann je nach Anzahl Bilder einige Minuten dauern - dieses Fenster kann geschlossen werden, der Auftrag läuft weiter."
      onClose={onClose}
    >
      {error && <p className="form-error-banner">{error}</p>}
      {!job ? (
        <p className="muted">Auftrag wird gestartet…</p>
      ) : job.status === "queued" ? (
        <p className="muted">In Warteschlange - {job.image_count} Bilder.</p>
      ) : job.status === "running" ? (
        <p className="muted">Analysiert {job.image_count} Bilder…</p>
      ) : job.status === "done" ? (
        <p>Fertig - {job.image_count} Bilder analysiert.</p>
      ) : job.status === "failed" ? (
        <p className="form-error-banner">Analyse fehlgeschlagen{job.error ? `: ${job.error}` : "."}</p>
      ) : null}
      <div className="gallery-upload-actions">
        <button type="button" className="button-ghost" onClick={onClose}>
          Schliessen
        </button>
      </div>
    </Modal>
  );
}

function FileCard({
  item,
  onNavigate,
  onOpenDetail,
  onTagClick,
}: {
  item: FileOverviewItem;
  onNavigate: (href: string) => void;
  onOpenDetail: () => void;
  onTagClick: (tag: string) => void;
}) {
  const thumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : undefined;
  const extension = item.original_name.includes(".") ? item.original_name.split(".").pop()!.toUpperCase() : "DATEI";

  return (
    <div className="file-card">
      {item.is_image ? (
        <button type="button" className="file-card-preview file-card-preview-button" onClick={onOpenDetail}>
          <img alt={item.original_name} src={thumbnailUrl ?? `${browserApiBaseUrl}${item.content_url}`} loading="lazy" decoding="async" />
        </button>
      ) : (
        <button type="button" className="file-card-preview file-card-preview-icon" onClick={onOpenDetail}>
          <FileTypeIcon />
          <span className="file-card-ext">{extension}</span>
        </button>
      )}
      <div className="file-card-body">
        <span className="file-card-name" title={item.original_name}>{item.original_name}</span>
        <div className="file-card-meta">
          <Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{SOURCE_LABEL[item.source]}</Badge>
          <span className="muted">{formatDate(item.created_at)}</span>
          {item.file_size_bytes ? <span className="muted">{formatFileSize(item.file_size_bytes)}</span> : null}
        </div>
        {item.ref_label ? (
          item.ref_href ? (
            <button type="button" className="file-card-ref" onClick={() => onNavigate(item.ref_href!)}>
              {item.source === "protocol_image" ? `Protokoll ${item.ref_label}` : item.ref_label}
              {item.ref_date ? ` · ${formatDate(item.ref_date)}` : ""}
            </button>
          ) : (
            <span className="file-card-ref file-card-ref-plain">
              {item.ref_label}
              {item.ref_date ? ` · ${formatDate(item.ref_date)}` : ""}
            </span>
          )
        ) : null}
        {item.tags.length > 0 && (
          <div className="file-card-tags">
            {item.tags.map((tag) => (
              <button key={tag} type="button" className="tag-chip tag-chip-sm" onClick={() => onTagClick(tag)}>
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FileDetailModal({
  item,
  tagSuggestions,
  onClose,
  onNavigate,
  onTagsSaved,
}: {
  item: FileOverviewItem;
  tagSuggestions: string[];
  onClose: () => void;
  onNavigate: (href: string) => void;
  onTagsSaved: (tags: string[]) => void;
}) {
  const [metadata, setMetadata] = useState<StoredFileMetadata | null>(null);
  const [loadingMetadata, setLoadingMetadata] = useState(true);
  const [tagsValue, setTagsValue] = useState(item.tags.join(","));
  const [saving, setSaving] = useState(false);
  const [qualityPanelOpen, setQualityPanelOpen] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;

  useEffect(() => {
    setTagsValue(item.tags.join(","));
    setMetadata(null);
    setLoadingMetadata(true);
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => setMetadata(data))
      .catch(() => setMetadata(null))
      .finally(() => setLoadingMetadata(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  function handleTagsChange(value: string) {
    setTagsValue(value);
    const tags = value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [];
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      setSaving(true);
      try {
        const saved = await browserApiFetch<string[]>(item.tags_url, {
          method: "PATCH",
          body: JSON.stringify({ tags }),
        });
        onTagsSaved(saved ?? tags);
      } finally {
        setSaving(false);
      }
    }, 500);
  }

  const dimensions = metadata?.width && metadata?.height ? `${metadata.width} × ${metadata.height} px` : null;

  return (
    <Modal
      open
      title={item.original_name}
      onClose={onClose}
      size="wide"
      headerActions={
        item.is_image ? (
          <button
            type="button"
            className="quality-info-toggle"
            aria-label="Analyse-Status anzeigen"
            aria-expanded={qualityPanelOpen}
            onClick={() => setQualityPanelOpen((open) => !open)}
          >
            <QualityInfoIcon />
          </button>
        ) : undefined
      }
    >
      {qualityPanelOpen && item.is_image && (
        <dl className="file-detail-quality-panel">
          <div>
            <dt>Schärfe</dt>
            <dd>{item.sharpness_score !== null ? item.sharpness_score.toFixed(1) : "Ausstehend"}</dd>
          </div>
          <div>
            <dt>Belichtung</dt>
            <dd>{item.exposure_score !== null ? `${Math.round(item.exposure_score * 100)}%` : "Ausstehend"}</dd>
          </div>
          <div>
            <dt>Gesichtsqualität</dt>
            <dd>{item.face_quality_score !== null ? item.face_quality_score.toFixed(1) : "Ausstehend"}</dd>
          </div>
        </dl>
      )}
      <div className="file-detail">
        <div className="file-detail-preview">
          {item.is_image ? (
            <LightboxImage src={fileUrl} alt={item.original_name} className="file-detail-preview-img" />
          ) : (
            <a href={fileUrl} target="_blank" rel="noreferrer" className="file-detail-preview-icon">
              <FileTypeIcon />
              <span>Original öffnen</span>
            </a>
          )}
        </div>

        <div className="file-detail-meta">
          <dl className="file-detail-meta-list">
            <div>
              <dt>Quelle</dt>
              <dd><Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{SOURCE_LABEL[item.source]}</Badge></dd>
            </div>
            {item.ref_label && (
              <div>
                <dt>Bezug</dt>
                <dd>
                  {item.ref_href ? (
                    <button type="button" className="file-card-ref" onClick={() => onNavigate(item.ref_href!)}>
                      {item.ref_label}
                    </button>
                  ) : (
                    item.ref_label
                  )}
                  {item.ref_date ? ` · ${formatDate(item.ref_date)}` : ""}
                </dd>
              </div>
            )}
            <div>
              <dt>Hochgeladen</dt>
              <dd>{formatDateTime(item.created_at)}</dd>
            </div>
            {metadata?.uploaded_by_name && (
              <div>
                <dt>Hochgeladen von</dt>
                <dd>{metadata.uploaded_by_name}</dd>
              </div>
            )}
            <div>
              <dt>Dateityp</dt>
              <dd>{item.mime_type ?? "Unbekannt"}</dd>
            </div>
            {item.file_size_bytes ? (
              <div>
                <dt>Grösse</dt>
                <dd>{formatFileSize(item.file_size_bytes)}</dd>
              </div>
            ) : null}
            {loadingMetadata ? (
              <div>
                <dt>Bildmasse</dt>
                <dd className="muted">Lädt…</dd>
              </div>
            ) : dimensions ? (
              <div>
                <dt>Bildmasse</dt>
                <dd>{dimensions}</dd>
              </div>
            ) : null}
            {metadata?.exif_taken_at && (
              <div>
                <dt>Aufgenommen</dt>
                <dd>{formatDateTime(metadata.exif_taken_at)}</dd>
              </div>
            )}
            {metadata?.exif_camera && (
              <div>
                <dt>Kamera</dt>
                <dd>{metadata.exif_camera}</dd>
              </div>
            )}
          </dl>

          <div className="file-detail-origin">
            <span className="file-detail-origin-label">Herkunft</span>
            <span className="tag-chip tag-chip-sm tag-chip-origin">{item.origin_tag}</span>
          </div>

          <div className="file-detail-tags">
            <span className="file-detail-tags-label">
              Tags {saving ? <span className="muted">(speichert…)</span> : null}
            </span>
            <TagInput value={tagsValue} onChange={handleTagsChange} suggestions={tagSuggestions} placeholder="Tag hinzufügen…" />
          </div>

          <a href={fileUrl} target="_blank" rel="noreferrer" className="button-inline button-ghost">
            Original in neuem Tab öffnen
          </a>
        </div>
      </div>
    </Modal>
  );
}

function FileTypeIcon() {
  return (
    <svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

function QualityInfoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="12" cy="12" r="9.25" />
      <line x1="12" y1="7.5" x2="12" y2="13" />
      <line x1="12" y1="16.5" x2="12" y2="16.5" />
    </svg>
  );
}
