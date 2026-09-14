"use client";

import { PhotoAlbums } from "./photo-albums";
import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { LightboxImage } from "@/components/ui/lightbox-image";
import { Modal } from "@/components/ui/modal";
import { NavIcon } from "@/components/ui/nav-icons";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem, FileOverviewSource, StoredFileMetadata } from "@/types/api";

const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.zip";

const PAGE_SIZE = 60;

type Mode = "photos" | "files";
type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes";

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

  function buildUrl(skip: number) {
    const params = new URLSearchParams();
    params.set("skip", String(skip));
    params.set("limit", String(PAGE_SIZE));
    if (mode === "photos") params.set("only_images", "true");
    if (mode === "files") params.set("exclude_images", "true");
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    if (albumId) params.set("album_id", albumId);
    params.set("sort_by", mode === "photos" ? "created_at" : sortKey);
    params.set("sort_dir", mode === "photos" ? "desc" : sortDir);
    return `/api/files?${params.toString()}`;
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

  function handleUploaded(uploaded: FileOverviewItem[], errors: string[], targetAlbumId = albumId) {
    if (uploaded.length > 0) {
      if (targetAlbumId) {
        void browserApiFetch(`/api/files/albums/${targetAlbumId}/items`, { method: "POST", body: JSON.stringify({ file_ids: uploaded.map((item) => item.id) }) })
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
          albumId={albumId}
          tagSuggestions={tagSuggestions}
          onClose={() => setUploadModalOpen(false)}
          onUploaded={handleUploaded}
        />
      )}
    </div>
  );
}

function GalleryUploadModal({
  albumId,
  tagSuggestions,
  onClose,
  onUploaded,
}: {
  albumId?: string;
  tagSuggestions: string[];
  onClose: () => void;
  onUploaded: (items: FileOverviewItem[], errors: string[], albumId?: string) => void;
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [tagsValue, setTagsValue] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [albums, setAlbums] = useState<{ id: string; name: string }[]>([]);
  const [targetAlbumId, setTargetAlbumId] = useState(albumId ?? "");
  useEffect(() => {
    browserApiFetch<{ id: string; name: string }[]>("/api/files/albums")
      .then((data) => setAlbums(data ?? []))
      .catch(() => setError("Alben konnten nicht geladen werden."));
  }, []);

  function addFiles(fileList: FileList | File[]) {
    if (uploading) return;
    const addedFiles = Array.from(fileList);
    setSelectedFiles((current) => [...current, ...addedFiles]);
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
      onUploaded(result?.items ?? [], result?.errors ?? [], targetAlbumId || undefined);
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
      description="Die Bilder landen in der Galerie und werden beim Upload virengeprüft."
      onClose={() => { if (!uploading) onClose(); }}
      size="wide"
      className="gallery-upload-modal"
      hideCloseButton
      headerActions={<button type="button" className="gallery-upload-remove" aria-label="Schliessen" title="Schliessen" disabled={uploading} onClick={onClose}>×</button>}
    >
      <div className="gallery-upload">
        <div className="gallery-upload-scroll">
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
          onClick={() => { if (!uploading) inputRef.current?.click(); }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              if (!uploading) inputRef.current?.click();
            }
          }}
          role="button"
          aria-label="Bilder oder ZIP-Dateien wählen"
          aria-disabled={uploading}
          tabIndex={0}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={GALLERY_UPLOAD_ACCEPT}
            hidden
            disabled={uploading}
            onChange={(event) => {
              if (event.target.files) addFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <span className="gallery-upload-image-icon" aria-hidden="true"><NavIcon name="photos" /></span>
          <p>Bilder hierher ziehen oder Dateien wählen</p>
          <p className="muted">JPG, PNG, GIF, WebP, BMP, TIFF · ZIP-Archive</p>
        </div>

        <div className="gallery-upload-fields">
          <label>Bezug<input value="Galerie" readOnly /></label>
          <label>Album<select value={targetAlbumId} disabled={uploading || Boolean(albumId)} onChange={(event) => setTargetAlbumId(event.target.value)}>
            <option value="">Kein Album</option>
            {albumId && !albums.some((album) => album.id === albumId) && <option value={albumId}>Aktuelles Album</option>}
            {albums.map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}
          </select></label>
        </div>
        <div className="gallery-upload-tags">
          <span className="gallery-upload-label">Tags für alle Bilder</span>
          <TagInput value={tagsValue} onChange={setTagsValue} suggestions={tagSuggestions} placeholder="Tag hinzufügen …" readOnly={uploading} />
        </div>
        <section className="gallery-upload-queue" aria-label="Warteschlange" aria-busy={uploading}>
          <div className="gallery-upload-queue-heading"><span className="gallery-upload-label">Warteschlange</span><span>{selectedFiles.length} {selectedFiles.length === 1 ? "Datei gewählt" : "Dateien gewählt"}</span></div>
        {selectedFiles.length > 0 && (
          <ul className="gallery-upload-file-list">
            {selectedFiles.map((file, index) => (
              <li key={`${file.name}-${index}`}>
                <UploadThumbnail file={file} />
                <div className="gallery-upload-file-details">
                  <div className="gallery-upload-file-heading"><span className="gallery-upload-file-name" title={file.name}>{file.name}</span><span className="muted">{formatFileSize(file.size)}</span></div>
                  {uploading && <progress className="gallery-upload-progress" aria-label={`${file.name}: Upload und Virenprüfung laufen`} />}
                  <span className="gallery-upload-file-status">{uploading ? "Upload und Virenprüfung laufen …" : "Bereit zum Hochladen"}</span>
                </div>
                <button type="button" className="gallery-upload-remove" title="Datei entfernen" aria-label={`${file.name} entfernen`} disabled={uploading} onClick={() => removeFile(index)}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {selectedFiles.length === 0 && <p className="gallery-upload-empty">Keine Dateien gewählt</p>}
        </section>

        {error && <p className="form-error-banner">{error}</p>}
        </div>
        <div className="gallery-upload-footer">
        <span className="gallery-upload-summary" aria-live="polite">{selectedFiles.length} {selectedFiles.length === 1 ? "Datei" : "Dateien"} · {formatFileSize(selectedFiles.reduce((total, file) => total + file.size, 0))}</span>
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
              ? "Upload läuft …"
              : selectedFiles.length > 0
                ? `${selectedFiles.length} ${selectedFiles.length === 1 ? "Bild" : "Bilder"} hochladen`
                : "Hochladen"}
          </button>
        </div>
        </div>
      </div>
    </Modal>
  );
}

function UploadThumbnail({ file }: { file: File }) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!file.type.startsWith("image/")) return;
    const preview = URL.createObjectURL(file);
    setUrl(preview);
    return () => URL.revokeObjectURL(preview);
  }, [file]);
  return <span className="gallery-upload-thumbnail">{url && <img src={url} alt="" onError={() => setUrl(undefined)} />}</span>;
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
    <Modal open title={item.original_name} onClose={onClose} size="wide">
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
