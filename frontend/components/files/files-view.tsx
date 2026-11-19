"use client";

import { useEffect, useRef, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { DocumentUploadModal } from "./document-upload-modal";
import { UploadResultsModal, uploadResultsSummary } from "./upload-results-modal";
import { countUploadResults } from "@/lib/utils/upload-results";
import { FileDetailModal } from "./file-detail-modal";
import { useFileActions } from "./file-actions";
import { FilesGrid } from "./files-grid";
import { FilesTable } from "./files-table";
import { TrashModal } from "./trash-modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { EmptyState } from "@/components/ui/empty-state";
import { FileDropOverlay } from "@/components/ui/file-drop-overlay";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { useOpenRequest } from "@/lib/search/handoff";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { TagInput } from "@/components/ui/tag-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useFileDrop } from "@/lib/hooks/use-file-drop";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { DocumentUploadResult, FileOverviewItem, FileOverviewSource, FileTrashActionResult, UploadFileResult } from "@/types/api";

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
    { value: "protocol_export", label: t("sourceOptions.protocolExports") },
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

type FilesViewMode = "list" | "grid";
const VIEW_STORAGE_KEY = "hocx.files.view";

type Props = {
  initialItems: FileOverviewItem[];
  /** files.manage: Dateien in den Papierkorb legen. */
  canDelete?: boolean;
  /** files.manage oder photos.manage: Papierkorb öffnen. */
  canOpenTrash?: boolean;
};

export function FilesView({ initialItems, canDelete = false, canOpenTrash = false }: Props) {
  const t = useTranslations("files");
  const router = useRouter();
  const showToast = useToast();
  const confirm = useConfirm();
  const [trashOpen, setTrashOpen] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [uploadResults, setUploadResults] = useState<UploadFileResult[] | null>(null);
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
  // Ansicht Liste/Kacheln (Design «Dateien v2»), je Gerät gemerkt
  const [view, setView] = useState<FilesViewMode>("grid");
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(VIEW_STORAGE_KEY);
      if (stored === "list" || stored === "grid") setView(stored);
    } catch {
      // Speicher gesperrt (privater Modus): Standard bleibt
    }
  }, []);
  function chooseView(next: FilesViewMode) {
    setView(next);
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, next);
    } catch {
      // nur Komfort
    }
  }
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

  // Treffer aus der globalen Suche (?open=<id>): Suche mit dem Dateinamen vorbelegen und die
  // Datei öffnen, sobald sie in der (neu geladenen) Liste steht.
  useOpenRequest(items, (item) => setDetailItem(item), setSearch);

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
    if (uploaded.length > 0) void reloadFromStart();
    setTagSuggestions((current) => Array.from(new Set([...current, ...uploaded.flatMap((item) => item.tags)])).sort((a, b) => a.localeCompare(b)));
    const results = result.file_results ?? [];
    if (results.length > 0) {
      // Je Datei: hochgeladen / übersprungen (schon vorhanden) / fehlgeschlagen.
      const failed = countUploadResults(results).failed;
      showToast(uploadResultsSummary(results, t), failed > 0 ? "info" : "success", {
        action: { label: t("uploadResults.detailsAction"), onClick: () => setUploadResults(results) },
      });
      return;
    }
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

  async function moveToTrash(item: FileOverviewItem) {
    const ok = await confirm({ tone: "danger", message: t("trash.moveConfirm", { name: item.original_name }), confirmLabel: t("trash.moveLabel") });
    if (!ok) return;
    try {
      const result = await browserApiFetch<FileTrashActionResult>("/api/files/trash", { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
      if (result && result.file_ids.length > 0) {
        setItems((current) => current.filter((entry) => entry.id !== item.id));
        setDetailItem((current) => (current && current.id === item.id ? null : current));
        showToast(t("trash.movedToast", { name: item.original_name }), "success");
      }
      if (result && result.errors.length > 0) showToast(result.errors.join(" · "), "error");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("trash.actionError"), "error");
    }
  }

  const actionsFor = useFileActions({
    onOpenDetail: setDetailItem,
    onShare: setShareItem,
    onChanged: () => void reloadFromStart(),
    onTrash: canDelete ? (item) => void moveToTrash(item) : undefined,
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
    <div className="grid files-overview">
      <div className="page-header files-page-header">
        <div>
          <h1 className="page-title">{t("view.title")}</h1>
          <p className="muted">
            {hasNoFiles
              ? t("view.descriptionEmpty")
              : t.rich("view.descriptionLinked", { photos: (chunks) => <Link href="/photos">{chunks}</Link> })}
          </p>
        </div>
        {hasNoFiles && !canOpenTrash ? null : (
          <div className="table-toolbar-actions">
            {canOpenTrash ? (
              <button type="button" className="button-secondary" onClick={() => setTrashOpen(true)}>
                {t("trash.open")}
              </button>
            ) : null}
            {hasNoFiles ? null : (
              <button type="button" className="button-primary" onClick={openUpload}>
                {t("view.uploadButton")}
              </button>
            )}
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
      <div className="files-card">
      <div className="list-filter-row list-filter-row-compact photos-filter-row files-toolbar">
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
        <div className="files-view-toggle" role="group" aria-label={t("view.viewToggle")}>
          <button type="button" className={`button-icon${view === "list" ? " files-view-toggle-active" : ""}`} aria-pressed={view === "list"} aria-label={t("view.viewList")} title={t("view.viewList")} onClick={() => chooseView("list")}>
            <ActionIcon name="list" />
          </button>
          <button type="button" className={`button-icon${view === "grid" ? " files-view-toggle-active" : ""}`} aria-pressed={view === "grid"} aria-label={t("view.viewGrid")} title={t("view.viewGrid")} onClick={() => chooseView("grid")}>
            <ActionIcon name="grid" />
          </button>
        </div>
      </div>

      {view === "grid" ? (
        <FilesGrid items={items} onOpenDetail={setDetailItem} actionsFor={actionsFor} />
      ) : (
        <FilesTable items={items} onOpenDetail={setDetailItem} onNavigate={(href) => router.push(href as Route)} onShare={setShareItem} actionsFor={actionsFor} />
      )}
      </div>
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

      {uploadResults && <UploadResultsModal results={uploadResults} onClose={() => setUploadResults(null)} />}

      {canOpenTrash ? <TrashModal open={trashOpen} onClose={() => setTrashOpen(false)} onRestored={() => void reloadFromStart()} /> : null}

      <FileDropOverlay active={isFileDragging} title={t("view.dropOverlayTitle")} hint={t("view.dropOverlayHint")} />

      <ShareLinkModal
        open={shareItem !== null}
        onClose={() => setShareItem(null)}
        fileIds={shareItem ? [shareItem.id] : []}
        defaultName={shareItem?.original_name ?? ""}
        includesImages={shareItem?.is_image ?? false}
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
