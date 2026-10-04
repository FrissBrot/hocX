"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { confirmAddToSharedAlbum } from "./album-share-release";
import { groupPhotosByDate } from "./grouping";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatWeekdayDate } from "@/lib/utils/format";
import { FileOverviewItem, FileOverviewSource, PhotoAlbum } from "@/types/api";

const PAGE_SIZE = 60;

type SourceFilter = "all" | "protocols" | "submissions" | "uploads";

const SOURCE_BY_FILTER: Record<SourceFilter, FileOverviewSource | null> = {
  all: null,
  protocols: "protocol_image",
  submissions: "submission_upload",
  uploads: "gallery_upload",
};

/** Mehrfachauswahl vorhandener Fotos für ein Album. Fotos, die schon im Album sind, bleiben
 * sichtbar (gedimmt, "Im Album"), lassen sich aber nicht erneut wählen. */
export function AlbumPhotoPicker({ album, onClose, onAdded }: { album: PhotoAlbum; onClose: () => void; onAdded: () => void }) {
  const t = useTranslations("photos.albumPicker");
  const toast = useToast();
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [hideContained, setHideContained] = useState(false);
  const [items, setItems] = useState<FileOverviewItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [isReloading, setIsReloading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);
  const loadingMoreRef = useRef(false);
  const requestIdRef = useRef(0);
  const didMountRef = useRef(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  function buildUrl(skip: number) {
    const params = new URLSearchParams();
    params.set("only_images", "true");
    if (search.trim()) params.set("search", search.trim());
    const source = SOURCE_BY_FILTER[sourceFilter];
    if (source) params.set("source", source);
    if (hideContained) params.set("exclude_album_id", album.id);
    params.set("skip", String(skip));
    params.set("limit", String(PAGE_SIZE));
    params.set("sort_by", "group_date");
    params.set("sort_dir", "desc");
    return `/api/files?${params.toString()}`;
  }

  useEffect(() => {
    const firstLoad = !didMountRef.current;
    didMountRef.current = true;
    const requestId = ++requestIdRef.current;
    setIsReloading(true);
    setLoadMoreFailed(false);
    const timer = setTimeout(async () => {
      try {
        const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(0));
        if (requestIdRef.current !== requestId) return;
        setItems(next ?? []);
        setHasMore((next ?? []).length === PAGE_SIZE);
      } catch {
        if (requestIdRef.current === requestId) toast(t("loadError"), "error");
      } finally {
        if (requestIdRef.current === requestId) setIsReloading(false);
      }
    }, firstLoad ? 0 : 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, sourceFilter, hideContained, album.id]);

  async function loadMore() {
    if (loadingMoreRef.current || isReloading || !hasMore) return;
    const requestId = requestIdRef.current;
    loadingMoreRef.current = true;
    setIsLoadingMore(true);
    setLoadMoreFailed(false);
    try {
      const next = await browserApiFetch<FileOverviewItem[]>(buildUrl(items.length));
      if (requestId !== requestIdRef.current) return;
      setItems((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...current, ...(next ?? []).filter((item) => !known.has(item.id))];
      });
      setHasMore((next ?? []).length === PAGE_SIZE);
    } catch {
      if (requestId === requestIdRef.current) setLoadMoreFailed(true);
    } finally {
      loadingMoreRef.current = false;
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore: hasMore && !loadMoreFailed,
    isLoading: isLoadingMore || isReloading,
    onLoadMore: () => void loadMore(),
  });

  const groups = useMemo(() => groupPhotosByDate(items), [items]);

  function isInAlbum(item: FileOverviewItem) {
    return item.albums.some((ref) => ref.id === album.id);
  }

  function toggle(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleGroup(ids: string[]) {
    setSelectedIds((current) => {
      const next = new Set(current);
      const allSelected = ids.every((id) => current.has(id));
      for (const id of ids) {
        if (allSelected) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  async function submit() {
    if (busy || selectedIds.size === 0) return;
    const count = selectedIds.size;
    if (!(await confirmAddToSharedAlbum(confirm, album, count))) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/files/albums/${album.id}/items`, {
        method: "POST",
        body: JSON.stringify({ file_ids: Array.from(selectedIds) }),
      });
      toast(t("addedToast", { count }), "success");
      onAdded();
      onClose();
    } catch {
      toast(t("addError"), "error");
      setBusy(false);
    }
  }

  const filtered = search.trim() !== "" || sourceFilter !== "all" || hideContained;

  return (
    <Modal
      open
      title={t("title")}
      size="wide"
      className="album-picker-modal"
      onClose={() => { if (!busy) onClose(); }}
      header={
        <div>
          <div className="eyebrow">{t("eyebrow", { name: album.name })}</div>
          <h2>{t("title")}</h2>
        </div>
      }
      footer={
        <>
          <span className="album-picker-selection">
            {t("selection", { count: selectedIds.size })}
          </span>
          <div className="modal-footer-actions">
            <button type="button" className="button-ghost" disabled={busy} onClick={onClose}>{t("cancel")}</button>
            <button type="button" className="button-primary" disabled={busy || selectedIds.size === 0} onClick={() => void submit()}>
              {busy ? t("addingButton") : t("addButton")}
            </button>
          </div>
        </>
      }
    >
      <div className="album-picker-toolbar">
        <SearchInput className="album-picker-search" value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} aria-label={t("searchAriaLabel")} />
        <FilterTabs
          options={[
            { value: "all", label: t("filters.all") },
            { value: "protocols", label: t("filters.protocols") },
            { value: "submissions", label: t("filters.submissions") },
            { value: "uploads", label: t("filters.uploads") },
          ]}
          value={sourceFilter}
          onChange={setSourceFilter}
        />
        <label className="album-picker-switch">
          <input type="checkbox" role="switch" checked={hideContained} onChange={(event) => setHideContained(event.target.checked)} />
          <span className="album-picker-switch-track" aria-hidden="true" />
          <span>{t("hideContainedLabel")}</span>
        </label>
      </div>

      <div className="album-picker-body">
        {items.length === 0 && isReloading ? (
          <div className="album-picker-grid" role="status" aria-label={t("loadingAriaLabel")}>
            {Array.from({ length: 14 }, (_, index) => <div key={index} className="album-picker-tile album-picker-tile-skeleton" aria-hidden="true" />)}
          </div>
        ) : items.length === 0 ? (
          <p className="muted album-picker-empty">
            {filtered ? t("emptyFiltered") : t("emptyNone")}
          </p>
        ) : (
          groups.map((group) => {
            const selectableIds = group.items.filter((item) => !isInAlbum(item)).map((item) => item.id);
            const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedIds.has(id));
            return (
              <section key={group.key} className="album-picker-group">
                <div className="album-picker-group-header">
                  <h3 className="album-picker-group-title">{formatWeekdayDate(group.date)}</h3>
                  <span className="album-picker-group-count">{t("groupCount", { count: group.items.length })}</span>
                  <button
                    type="button"
                    className="album-picker-group-toggle"
                    disabled={selectableIds.length === 0}
                    onClick={() => toggleGroup(selectableIds)}
                  >
                    {allSelected ? t("deselectAll") : t("selectAll")}
                  </button>
                </div>
                <div className="album-picker-grid">
                  {group.items.map((item) => {
                    const contained = isInAlbum(item);
                    const selected = selectedIds.has(item.id);
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="checkbox"
                        aria-checked={contained || selected}
                        aria-disabled={contained || undefined}
                        aria-label={contained ? t("containedAriaLabel", { name: item.original_name }) : item.original_name}
                        className={`album-picker-tile${contained ? " album-picker-tile-contained" : ""}${selected ? " album-picker-tile-selected" : ""}`}
                        onClick={() => { if (!contained) toggle(item.id); }}
                      >
                        <img
                          alt=""
                          src={`${browserApiBaseUrl}${item.thumbnail_url ?? item.content_url}`}
                          loading="lazy"
                          decoding="async"
                          draggable={false}
                        />
                        {contained ? (
                          <span className="photo-tile-badge album-picker-tile-badge">{t("containedBadge")}</span>
                        ) : (
                          <span className="album-picker-tile-check" aria-hidden="true">
                            {selected && (
                              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M3 8.5l3 3 7-7" />
                              </svg>
                            )}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })
        )}

        {hasMore && (
          <div className="load-more-row" ref={loadMoreSentinelRef}>
            {loadMoreFailed ? (
              <button type="button" className="button-ghost" onClick={() => void loadMore()}>{t("retry")}</button>
            ) : (
              <span className="muted">{t("loadingMore")}</span>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
