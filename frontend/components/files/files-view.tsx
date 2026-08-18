"use client";

import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { LightboxImage } from "@/components/ui/lightbox-image";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem, FileOverviewSource } from "@/types/api";

const PAGE_SIZE = 60;

type ViewMode = "all" | "photos";
type SourceFilter = "all" | FileOverviewSource;
type SortKey = "created_at" | "original_name" | "file_size_bytes";

const SOURCE_LABEL: Record<FileOverviewSource, string> = {
  protocol_image: "Protokoll",
  word_import: "Word-Import",
  submission_upload: "Abgabe",
};

const SOURCE_BADGE_VARIANT: Record<FileOverviewSource, BadgeVariant> = {
  protocol_image: "info",
  word_import: "neutral",
  submission_upload: "success",
};

type Props = {
  initialItems: FileOverviewItem[];
};

export function FilesView({ initialItems }: Props) {
  const router = useRouter();
  const [view, setView] = useState<ViewMode>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [items, setItems] = useState<FileOverviewItem[]>(initialItems);
  const [hasMore, setHasMore] = useState(initialItems.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isReloading, setIsReloading] = useState(false);
  const didMountRef = useRef(false);
  const requestIdRef = useRef(0);

  function buildUrl(skip: number) {
    const params = new URLSearchParams();
    params.set("skip", String(skip));
    params.set("limit", String(PAGE_SIZE));
    if (view === "photos") params.set("only_images", "true");
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    if (search.trim()) params.set("search", search.trim());
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
  }, [view, sourceFilter, search, sortKey, sortDir]);

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

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dateien</h1>
          <p className="muted">Alle hochgeladenen Dateien dieses Mandanten - aus Protokollen, Word-Importen und Abgaben.</p>
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

      {items.length === 0 && !isReloading ? (
        <p className="muted">Keine Dateien gefunden.</p>
      ) : (
        <div className={view === "photos" ? "files-grid files-grid-photos" : "files-grid"}>
          {items.map((item) => (
            <FileCard key={item.id} item={item} onNavigate={(href) => router.push(href as Route)} />
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
    </div>
  );
}

function FileCard({ item, onNavigate }: { item: FileOverviewItem; onNavigate: (href: string) => void }) {
  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;
  const thumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : undefined;
  const extension = item.original_name.includes(".") ? item.original_name.split(".").pop()!.toUpperCase() : "DATEI";

  return (
    <div className="file-card">
      {item.is_image ? (
        <LightboxImage src={fileUrl} previewSrc={thumbnailUrl} alt={item.original_name} className="file-card-preview" />
      ) : (
        <a href={fileUrl} target="_blank" rel="noreferrer" className="file-card-preview file-card-preview-icon">
          <FileTypeIcon />
          <span className="file-card-ext">{extension}</span>
        </a>
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
      </div>
    </div>
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
