"use client";

import { useEffect, useRef, useState } from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";

import { DocumentUploadModal } from "./document-upload-modal";
import { FileDetailModal } from "./file-detail-modal";
import { FilesTable } from "./files-table";
import { FileDropOverlay } from "@/components/ui/file-drop-overlay";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useFileDrop } from "@/lib/hooks/use-file-drop";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { DocumentUploadResult, FileOverviewItem, FileOverviewSource } from "@/types/api";

const PAGE_SIZE = 60;

type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes";

const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "Alle Quellen" },
  { value: "protocol_image", label: "Protokolle" },
  { value: "word_import", label: "Word-Import" },
  { value: "submission_upload", label: "Abgaben" },
  { value: "gallery_upload", label: "Uploads" },
];

type SortOption = { id: string; label: string; key: SortKey; dir: "asc" | "desc" };

const SORT_OPTIONS: SortOption[] = [
  { id: "created_at:desc", label: "Neueste zuerst", key: "created_at", dir: "desc" },
  { id: "created_at:asc", label: "Älteste zuerst", key: "created_at", dir: "asc" },
  { id: "original_name:asc", label: "Name (A-Z)", key: "original_name", dir: "asc" },
  { id: "original_name:desc", label: "Name (Z-A)", key: "original_name", dir: "desc" },
  { id: "file_size_bytes:desc", label: "Grösse (gross-klein)", key: "file_size_bytes", dir: "desc" },
  { id: "file_size_bytes:asc", label: "Grösse (klein-gross)", key: "file_size_bytes", dir: "asc" },
];

type Props = {
  initialItems: FileOverviewItem[];
};

export function FilesView({ initialItems }: Props) {
  const router = useRouter();
  const showToast = useToast();
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
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  // Files dropped onto the page - they open the upload dialog with these already queued.
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const didMountRef = useRef(false);
  const requestIdRef = useRef(0);

  // The whole page is one big dropzone (not while a dialog is on top).
  const isFileDragging = useFileDrop(
    (files) => {
      setDroppedFiles(files);
      setUploadModalOpen(true);
    },
    !uploadModalOpen && detailItem === null,
  );

  function buildUrl(skip: number) {
    const params = new URLSearchParams();
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    params.set("exclude_images", "true");
    params.set("skip", String(skip));
    params.set("limit", String(PAGE_SIZE));
    params.set("sort_by", sortKey);
    params.set("sort_dir", sortDir);
    return `/api/files?${params.toString()}`;
  }

  // Filters are applied server-side (the tenant can have far more files than one page),
  // so every filter change re-queries from skip=0 instead of re-filtering what's loaded.
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
      } catch {
        if (requestIdRef.current === requestId) showToast("Dateien konnten nicht geladen werden.", "error");
      } finally {
        if (requestIdRef.current === requestId) setIsReloading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, search, tagFilter.join(","), sortKey, sortDir]);

  async function reloadFromStart() {
    const requestId = ++requestIdRef.current;
    setIsReloading(true);
    try {
      const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
      if (requestIdRef.current !== requestId) return;
      setItems(next ?? []);
      setHasMore((next ?? []).length === PAGE_SIZE);
    } catch {
      if (requestIdRef.current === requestId) showToast("Dateien konnten nicht geladen werden.", "error");
    } finally {
      if (requestIdRef.current === requestId) setIsReloading(false);
    }
  }

  function handleDocumentsUploaded(result: DocumentUploadResult) {
    const uploaded = result.items;
    void reloadFromStart();
    setTagSuggestions((current) => Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b)));
    showToast(uploaded.length === 1 ? "1 Datei hochgeladen." : `${uploaded.length} Dateien hochgeladen.`, "success");
    if (result.errors.length > 0) showToast(result.errors.join(" · "), "info");
  }

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
    hasMore,
    isLoading: isLoadingMore || isReloading,
    onLoadMore: () => void loadMore(),
  });

  function handleTagsSaved(itemId: string, tags: string[]) {
    setItems((current) => current.map((item) => (item.id === itemId ? { ...item, tags } : item)));
    setDetailItem((current) => (current && current.id === itemId ? { ...current, tags } : current));
    setTagSuggestions((current) => Array.from(new Set([...current, ...tags])).sort((a, b) => a.localeCompare(b)));
  }

  return (
    <div className="grid grid-tight">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dateien</h1>
          <p className="muted">
            Alle hochgeladenen Nicht-Bild-Dateien dieses Mandanten - aus Protokollen, Word-Importen, Abgaben und
            direkten Uploads. Fotos siehe die separate &quot;Fotos&quot;-Seite.
          </p>
        </div>
        <div className="table-toolbar-actions">
          <button type="button" className="button-inline" onClick={() => {
              setDroppedFiles([]);
              setUploadModalOpen(true);
            }}>
            + Dateien hochladen
          </button>
        </div>
      </div>

      <div className="list-filter-row list-filter-row-compact">
        <FilterTabs options={SOURCE_OPTIONS} value={sourceFilter} onChange={(value) => setSourceFilter(value as SourceFilter)} />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Dateien durchsuchen" />
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
          <TagInput
            value={tagFilter.join(",")}
            onChange={(value) => setTagFilter(value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [])}
            suggestions={tagSuggestions}
            placeholder="Tag wählen oder eingeben…"
          />
        </div>
        <span className="muted list-filter-count">{items.length} {items.length === 1 ? "Datei" : "Dateien"}</span>
      </div>

      <FilesTable items={items} onOpenDetail={setDetailItem} onNavigate={(href) => router.push(href as Route)} />

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

      {uploadModalOpen && (
        <DocumentUploadModal
          tagSuggestions={tagSuggestions}
          initialFiles={droppedFiles}
          onClose={() => setUploadModalOpen(false)}
          onUploaded={handleDocumentsUploaded}
        />
      )}

      <FileDropOverlay active={isFileDragging} title="Zum Hochladen loslassen" hint="Danach stellst du den Upload ein." />

      {detailItem && (
        <FileDetailModal
          item={detailItem}
          tagSuggestions={tagSuggestions}
          onClose={() => setDetailItem(null)}
          onNavigate={(href) => router.push(href as Route)}
          onTagsSaved={(tags) => handleTagsSaved(detailItem.id, tags)}
        />
      )}
    </div>
  );
}
