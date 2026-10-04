"use client";

import { useEffect, useRef, useState } from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { DocumentUploadModal } from "./document-upload-modal";
import { FileDetailModal } from "./file-detail-modal";
import { FilesTable } from "./files-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FileDropOverlay } from "@/components/ui/file-drop-overlay";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useFileDrop } from "@/lib/hooks/use-file-drop";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { DocumentUploadResult, FileOverviewItem, FileOverviewSource } from "@/types/api";

const PAGE_SIZE = 60;

type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes";

type TFunc = (key: string) => string;

function sourceOptions(t: TFunc): { value: SourceFilter; label: string }[] {
  return [
    { value: "all", label: t("sourceOptions.all") },
    { value: "protocol_image", label: t("sourceOptions.protocols") },
    { value: "word_import", label: t("sourceOptions.wordImport") },
    { value: "submission_upload", label: t("sourceOptions.submissions") },
    { value: "gallery_upload", label: t("sourceOptions.uploads") },
  ];
}

type SortOption = { id: string; label: string; key: SortKey; dir: "asc" | "desc" };

function sortOptions(t: TFunc): SortOption[] {
  return [
    { id: "created_at:desc", label: t("sortOptions.newestFirst"), key: "created_at", dir: "desc" },
    { id: "created_at:asc", label: t("sortOptions.oldestFirst"), key: "created_at", dir: "asc" },
    { id: "original_name:asc", label: t("sortOptions.nameAsc"), key: "original_name", dir: "asc" },
    { id: "original_name:desc", label: t("sortOptions.nameDesc"), key: "original_name", dir: "desc" },
    { id: "file_size_bytes:desc", label: t("sortOptions.sizeDesc"), key: "file_size_bytes", dir: "desc" },
    { id: "file_size_bytes:asc", label: t("sortOptions.sizeAsc"), key: "file_size_bytes", dir: "asc" },
  ];
}

type Props = {
  initialItems: FileOverviewItem[];
};

export function FilesView({ initialItems }: Props) {
  const t = useTranslations("files");
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
  const [shareItem, setShareItem] = useState<FileOverviewItem | null>(null);
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
        if (requestIdRef.current === requestId) showToast(t("view.loadError"), "error");
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
      if (requestIdRef.current === requestId) showToast(t("view.loadError"), "error");
    } finally {
      if (requestIdRef.current === requestId) setIsReloading(false);
    }
  }

  function handleDocumentsUploaded(result: DocumentUploadResult) {
    const uploaded = result.items;
    void reloadFromStart();
    setTagSuggestions((current) => Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b)));
    showToast(t("view.uploadedToast", { count: uploaded.length }), "success");
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

  const hasNoFiles = items.length === 0 && !hasMore && sourceFilter === "all" && !search.trim() && tagFilter.length === 0;

  function openUpload() {
    setDroppedFiles([]);
    setUploadModalOpen(true);
  }

  return (
    <div className="grid grid-tight">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("view.title")}</h1>
          <p className="muted">
            {hasNoFiles ? t("view.descriptionEmpty") : t("view.description")}
          </p>
        </div>
        {hasNoFiles ? null : (
          <div className="table-toolbar-actions">
            <button type="button" className="button-primary" onClick={openUpload}>
              {t("view.uploadButton")}
            </button>
          </div>
        )}
      </div>

      {hasNoFiles ? (
        <EmptyState
          title={t("view.emptyTitle")}
          description={t("view.emptyDescription")}
          actions={
            <button type="button" className="button-primary" onClick={openUpload}>
              {t("view.uploadButton")}
            </button>
          }
          hint={t("view.emptyHint")}
        />
      ) : (
      <>
      <div className="list-filter-row list-filter-row-compact">
        <FilterTabs options={sourceOptions(t)} value={sourceFilter} onChange={(value) => setSourceFilter(value as SourceFilter)} />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("view.searchPlaceholder")} />
        </div>
        <SearchableSelect
          className="files-sort-select"
          options={sortOptions(t)}
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
            onChange={(value) => setTagFilter(value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [])}
            suggestions={tagSuggestions}
            placeholder={t("view.tagPlaceholder")}
          />
        </div>
        <span className="muted list-filter-count">{t("view.countFiles", { count: items.length })}</span>
      </div>

      <FilesTable items={items} onOpenDetail={setDetailItem} onNavigate={(href) => router.push(href as Route)} onShare={setShareItem} />
      </>
      )}

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">{t("view.loadMoreLoading")}</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              {t("view.loadMore", { count: items.length })}
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

      <FileDropOverlay active={isFileDragging} title={t("view.dropOverlayTitle")} hint={t("view.dropOverlayHint")} />

      <ShareLinkModal
        open={shareItem !== null}
        onClose={() => setShareItem(null)}
        fileIds={shareItem ? [shareItem.id] : []}
        defaultName={shareItem?.original_name ?? ""}
      />

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
