"use client";

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
import { FileOverviewItem, FileOverviewSource, StoredFileMetadata } from "@/types/api";

const GALLERY_UPLOAD_ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.zip";

const PAGE_SIZE = 60;

type ViewMode = "all" | "photos";
type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes";

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
  initialItems: FileOverviewItem[];
};

export function FilesView({ initialItems }: Props) {
  const router = useRouter();
  const showToast = useToast();
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [view, setView] = useState<ViewMode>("all");
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
    if (view === "photos") params.set("only_images", "true");
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    params.set("sort_by", sortKey);
    params.set("sort_dir", sortDir);
    return `/api/files?${params.toString()}`;
  }

  // Filters are applied server-side (the tenant can have far more files than one page),
  // so every filter change re-queries from skip=0 instead of re-filtering what's loaded -
  // unlike the client-side-only filtering used on smaller lists elsewhere in this app.
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    const requestId = ++requestIdRef.current;
    setIsReloading(true);
    const timer = setTimeout(async () => {
      try {
        const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
        if (requestIdRef.current !== requestId) return;
        setItems(next ?? []);
        setHasMore((next ?? []).length === PAGE_SIZE);
      } finally {
        if (requestIdRef.current === requestId) setIsReloading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, sourceFilter, search, tagFilter, sortKey, sortDir]);

  useEffect(() => {
    browserApiFetch<string[]>("/api/files/tags")
      .then((tags) => setTagSuggestions(tags ?? []))
      .catch(() => {});
  }, []);

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(items.length));
      setItems((current) => [...current, ...(next ?? [])]);
      setHasMore((next ?? []).length === PAGE_SIZE);
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore || isReloading,
    onLoadMore: () => void loadMore(),
  });

  function handleTagsSaved(itemId: number, tags: string[]) {
    setItems((current) => current.map((item) => (item.id === itemId ? { ...item, tags } : item)));
    setDetailItem((current) => (current && current.id === itemId ? { ...current, tags } : current));
    setTagSuggestions((current) => Array.from(new Set([...current, ...tags])).sort((a, b) => a.localeCompare(b)));
  }

  function handleUploaded(uploaded: FileOverviewItem[], errors: string[]) {
    if (uploaded.length > 0) {
      setItems((current) => [...uploaded, ...current]);
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
      <div className="page-header">
        <div>
          <h1 className="page-title">Dateien</h1>
          <p className="muted">Alle hochgeladenen Dateien dieses Mandanten - aus Protokollen, Word-Importen und Abgaben.</p>
        </div>
        <div className="table-toolbar-actions">
          <button type="button" className="button-inline" onClick={() => setUploadModalOpen(true)}>
            + Bilder hochladen
          </button>
        </div>
      </div>

      <FilterTabs
        options={[
          { value: "all", label: "Alle Dateien" },
          { value: "photos", label: "Fotos" },
        ]}
        value={view}
        onChange={(value) => setView(value as ViewMode)}
      />

      <div className="list-filter-row">
        <FilterTabs
          options={[
            { value: "all", label: "Alle Quellen" },
            { value: "protocol_image", label: "Protokolle" },
            { value: "word_import", label: "Word-Import" },
            { value: "submission_upload", label: "Abgaben" },
            { value: "gallery_upload", label: "Galerie" },
          ]}
          value={sourceFilter}
          onChange={(value) => setSourceFilter(value as SourceFilter)}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Dateien durchsuchen" />
        </div>
        <select
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
        </select>
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
        <p className="muted">Keine Dateien gefunden.</p>
      ) : (
        <div className={view === "photos" ? "files-grid files-grid-photos" : "files-grid"}>
          {items.map((item) => (
            <FileCard
              key={item.id}
              item={item}
              onNavigate={(href) => router.push(href as Route)}
              onOpenDetail={() => setDetailItem(item)}
              onTagClick={(tag) => setTagFilter((current) => (current.includes(tag) ? current : [...current, tag]))}
            />
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
