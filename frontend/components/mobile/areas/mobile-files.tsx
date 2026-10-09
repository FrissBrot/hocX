"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useOpenMore } from "@/components/mobile/mobile-shell";
import { MobileActionSheet, MobileChip, MobileChipRow, MobileEmpty, MobileFab, MobileListRow, MobileSubHeader } from "@/components/mobile/mobile-ui";
import { dateParts } from "@/components/mobile/mobile-utils";
import { DocumentUploadModal } from "@/components/files/document-upload-modal";
import { FileDetailModal } from "@/components/files/file-detail-modal";
import { SearchInput } from "@/components/ui/search-input";
import { ShareLinkModal } from "@/components/ui/share-link-modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import type { DocumentUploadResult, FileOverviewItem, FileOverviewSource } from "@/types/api";

const PAGE_SIZE = 60;
type SourceFilter = "all" | FileOverviewSource;
const SOURCES: { value: SourceFilter; key: string }[] = [
  { value: "all", key: "all" },
  { value: "protocol_image", key: "protocols" },
  { value: "submission_upload", key: "submissions" },
  { value: "gallery_upload", key: "uploads" },
  { value: "word_import", key: "wordImport" },
];
const SORTS = [
  { id: "created_at:desc", key: "newestFirst" },
  { id: "created_at:asc", key: "oldestFirst" },
  { id: "original_name:asc", key: "nameAsc" },
  { id: "original_name:desc", key: "nameDesc" },
  { id: "file_size_bytes:desc", key: "sizeDesc" },
  { id: "file_size_bytes:asc", key: "sizeAsc" },
];

/** Dateityp-Kachel links in der Zeile (PDF rot, Text blau, Tabelle gruen). */
export function FileTypeTile({ name }: { name: string }) {
  const ext = (name.split(".").pop() ?? "").toLowerCase().slice(0, 4);
  const tone = ext === "pdf" ? "pdf" : ["doc", "docx", "odt", "rtf", "txt", "md"].includes(ext) ? "doc" : ["xls", "xlsx", "csv", "ods"].includes(ext) ? "sheet" : "";
  return <span className={`mobile-filetype${tone ? ` mobile-filetype-${tone}` : ""}`} aria-hidden="true">{ext || "?"}</span>;
}

export function MobileFiles({ initialItems }: { initialItems: FileOverviewItem[] }) {
  const t = useTranslations("files");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const router = useRouter();
  const openMore = useOpenMore();
  const showToast = useToast();
  const [items, setItems] = useState(initialItems);
  const [source, setSource] = useState<SourceFilter>("all");
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [sort, setSort] = useState(SORTS[0].id);
  const [sortOpen, setSortOpen] = useState(false);
  const [hasMore, setHasMore] = useState(initialItems.length >= PAGE_SIZE);
  const [detail, setDetail] = useState<FileOverviewItem | null>(null);
  const [share, setShare] = useState<FileOverviewItem | null>(null);
  const [uploading, setUploading] = useState(false);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const mounted = useRef(false);

  function url(skip: number) {
    const [sortBy, sortDir] = sort.split(":");
    const params = new URLSearchParams({ exclude_images: "true", skip: String(skip), limit: String(PAGE_SIZE), sort_by: sortBy, sort_dir: sortDir });
    if (source !== "all") params.set("source", source);
    if (search.trim()) params.set("search", search.trim());
    return `/api/files?${params.toString()}`;
  }

  async function reload() {
    try {
      const next = (await browserApiFetch<FileOverviewItem[]>(url(0))) ?? [];
      setItems(next);
      setHasMore(next.length === PAGE_SIZE);
    } catch {
      showToast(t("view.loadError"), "error");
    }
  }

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    const timer = window.setTimeout(() => void reload(), 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, search, sort]);

  useEffect(() => {
    browserApiFetch<string[]>("/api/files/tags")
      .then((tags) => setTagSuggestions(tags ?? []))
      .catch(() => {});
  }, []);

  async function loadMore() {
    const next = (await browserApiFetch<FileOverviewItem[]>(url(items.length))) ?? [];
    setItems((current) => [...current, ...next]);
    setHasMore(next.length === PAGE_SIZE);
  }

  function uploaded(result: DocumentUploadResult) {
    void reload();
    showToast(t("view.uploadedToast", { count: result.items.length }), "success");
    if (result.errors.length > 0) showToast(result.errors.join(" · "), "info");
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader
        title={t("view.title")}
        subtitle={t("view.description")}
        backLabel={tMobile("tabs.more")}
        onBack={openMore}
        actions={
          <>
            <button type="button" className={`mobile-icon-button${searchOpen ? " mobile-icon-button-active" : ""}`} aria-label={tMobile("common.search")} onClick={() => setSearchOpen((open) => !open)}>
              <MobileIcon name="search" />
            </button>
            <button type="button" className="mobile-icon-button" aria-label={tMobile("files.sort")} onClick={() => setSortOpen(true)}>
              <MobileIcon name="chevronDown" />
            </button>
          </>
        }
      />
      {searchOpen ? (
        <div className="mobile-section">
          <SearchInput value={search} onChange={setSearch} placeholder={t("view.searchPlaceholder")} autoFocus />
        </div>
      ) : null}
      <MobileChipRow>
        {SOURCES.map((option) => (
          <MobileChip key={option.value} active={source === option.value} onClick={() => setSource(option.value)}>
            {t(`sourceOptions.${option.key}`)}
          </MobileChip>
        ))}
      </MobileChipRow>
      {items.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {items.map((item) => (
              <MobileListRow
                key={item.id}
                onClick={() => setDetail(item)}
                leading={<FileTypeTile name={item.original_name} />}
                label={
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{item.original_name}</span>
                    <span className="mobile-row-meta">
                      {[item.ref_label || null, formatFileSize(item.file_size_bytes) || null, dateParts.dayMonth(item.created_at.slice(0, 10), locale)].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                }
              />
            ))}
          </div>
          {hasMore ? (
            <button type="button" className="button-secondary mobile-button-block" onClick={() => void loadMore()}>
              {t("view.loadMore", { count: items.length })}
            </button>
          ) : null}
        </div>
      ) : (
        <MobileEmpty title={t("view.emptyTitle")} hint={t("view.emptyDescription")} />
      )}

      <MobileFab label={tMobile("files.fab")} onClick={() => setUploading(true)} />

      {sortOpen ? (
        <MobileActionSheet
          title={tMobile("files.sort")}
          onClose={() => setSortOpen(false)}
          actions={SORTS.map((option) => ({ label: `${sort === option.id ? "✓ " : ""}${t(`sortOptions.${option.key}`)}`, onClick: () => setSort(option.id) }))}
        />
      ) : null}
      {detail ? (
        <FileDetailModal
          item={detail}
          tagSuggestions={tagSuggestions}
          onClose={() => setDetail(null)}
          onNavigate={(href) => router.push(href as Route)}
          onTagsSaved={(tags) => {
            setItems((current) => current.map((item) => (item.id === detail.id ? { ...item, tags } : item)));
            setDetail((current) => (current ? { ...current, tags } : current));
          }}
          onShare={() => {
            setShare(detail);
            setDetail(null);
          }}
        />
      ) : null}
      <ShareLinkModal open={share !== null} onClose={() => setShare(null)} fileIds={share ? [share.id] : []} defaultName={share?.original_name ?? ""} />
      {uploading ? <DocumentUploadModal tagSuggestions={tagSuggestions} initialFiles={[]} onClose={() => setUploading(false)} onUploaded={uploaded} /> : null}
    </div>
  );
}
