"use client";

import { useEffect, useRef, useState } from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";

import { FileDetailModal } from "./file-detail-modal";
import { FileStatCards } from "./file-stat-cards";
import { FilesTable } from "./files-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { FileOverviewItem, FileOverviewSource } from "@/types/api";

const PAGE_SIZE = 60;

type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes";

const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "Alle Quellen" },
  { value: "protocol_image", label: "Protokolle" },
  { value: "word_import", label: "Word-Import" },
  { value: "submission_upload", label: "Abgaben" },
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
  const didMountRef = useRef(false);
  const requestIdRef = useRef(0);

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
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dateien</h1>
          <p className="muted">
            Alle hochgeladenen Nicht-Bild-Dateien dieses Mandanten - aus Protokollen, Word-Importen und Abgaben. Fotos
            siehe die separate &quot;Fotos&quot;-Seite.
          </p>
        </div>
      </div>

      <FileStatCards />

      <div className="list-filter-row">
        <FilterTabs options={SOURCE_OPTIONS} value={sourceFilter} onChange={(value) => setSourceFilter(value as SourceFilter)} />
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
        <span className="muted">{items.length} {items.length === 1 ? "Datei" : "Dateien"}</span>
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
