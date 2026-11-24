"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";

import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";
import { useModalFocus } from "@/lib/a11y/use-focus-trap";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { ariaKeyShortcuts } from "@/lib/keyboard/registry";
import { LivePhotoClip } from "@/components/photos/live-photo-clip";
import { PhotoDateMarker } from "@/components/photos/photo-date-marker";
import { ActionIcon } from "@/components/ui/action-icons";
import { Popover } from "@/components/ui/popover";
import { useDeferredPopupSave } from "@/lib/hooks/use-deferred-popup-save";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatWeekdayDate } from "@/lib/utils/format";
import type { FileAlbumRef, FileBulkDeleteResult, FileOverviewItem, FileTrashActionResult, StoredFileMetadata } from "@/types/api";
import { PhotoActionIcon } from "./photo-action-icon";
import {
  markSimilarityGroupReviewed,
  removeFromSimilarityCache,
  unmarkSimilarityGroupReviewed,
  useReviewedSimilarityGroups,
  useSimilarityGroups,
} from "./use-similarity-groups";
import { PhotoViewerCompare } from "./viewer/photo-viewer-compare";
import { PhotoViewerDelete } from "./viewer/photo-viewer-delete";
import { PhotoViewerShare } from "./viewer/photo-viewer-share";
import { PhotoViewerSidebar } from "./viewer/photo-viewer-sidebar";
import { PhotoViewerPlaceLink, SearchPlaceHandler } from "./viewer/photo-viewer-place";
import type { PhotoPlace } from "@/lib/photos/places";
import {
  CompareDecisions,
  compareSuggestion,
  compareSummary,
  filmstripRange,
  groupKey,
  groupsForItem,
  isDeletable,
  nextAfterRemoval,
} from "./viewer/viewer-logic";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

// Was ein Live Photo beim Herunterladen liefert - siehe GET /stored-files/{id}/download?part=.
function liveDownloadOptions(t: TFunc) {
  return [
    { part: "image", label: t("downloadOptions.image") },
    { part: "video", label: t("downloadOptions.video") },
    { part: "both", label: t("downloadOptions.both") },
  ];
}

const SWIPE_MIN_PX = 50;

/** Waagrechte Wischgeste: nach links = nächstes Foto, nach rechts = vorheriges. Senkrechte
 * Bewegungen (Scrollen) und kurze Tipps lösen nichts aus. */
export function swipeDirection(startX: number, startY: number, endX: number, endY: number): "prev" | "next" | null {
  const dx = endX - startX;
  const dy = endY - startY;
  if (Math.abs(dx) < SWIPE_MIN_PX || Math.abs(dx) < Math.abs(dy) * 1.5) return null;
  return dx < 0 ? "next" : "prev";
}

type Pop = "download" | "share" | "delete" | null;

/** Rechte für die Foto-Ansicht, von der Seite (Server-Session) durchgereicht. */
export type ViewerPermissions = { canManage?: boolean; canShare?: boolean; canManageSettings?: boolean };

export type PhotoViewerProps = {
  items: FileOverviewItem[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  onToggleBest: (item: FileOverviewItem) => void;
  onTagsSaved: (id: string, tags: string[]) => void;
  // Geschätztes oder korrigiertes Aufnahmedatum geändert - die Galerie sortiert/gruppiert danach neu.
  onCaptureDateSaved?: (id: string, metadata: StoredFileMetadata) => void;
  /** photos.manage: Best-of, Löschen (Papierkorb), Vergleich anwenden, Alben, Tags. */
  canManage?: boolean;
  /** sharing.public + Abo «Fotos teilen»: Freigabelink für dieses Foto. */
  canShare?: boolean;
  /** settings.manage: «Verwalten» führt zu Einstellungen › Zugangslinks, sonst zu «Freigaben». */
  canManageSettings?: boolean;
  /** Fotos liegen im Papierkorb. `nextId`: wohin die Ansicht springen soll (null = schliessen). */
  onRemoved?: (ids: string[], nextId: string | null) => void;
  /** «Rückgängig» hat Fotos aus dem Papierkorb zurückgeholt. */
  onRestored?: (ids: string[]) => void;
  onAlbumsChanged?: (id: string, albums: FileAlbumRef[]) => void;
  /** Foto-Standorte: Klick auf den Ort startet die Umgebungssuche (Hauptgalerie). */
  onSearchPlace?: SearchPlaceHandler;
  /** Ort von Hand gesetzt/entfernt - Kachel aktualisieren. */
  onPlaceChanged?: (id: string, place: PhotoPlace | null) => void;
};

/** Foto-Einzelansicht (Design «hocX Foto-Ansicht»): dunkle Vollbildansicht mit Kopfzeile, Bühne,
 * Filmstreifen, Vergleichsmodus für Duplikat-/Ähnlich-Gruppen und Seitenleiste. Eigener
 * Vollbild-Dialog mit useModalFocus (Fokusfalle, Fokus zurück); Tastenkürzel über die Registry. */
export function PhotoViewer({
  items,
  index,
  onIndexChange,
  onClose,
  onToggleBest,
  onTagsSaved,
  onCaptureDateSaved,
  canManage = false,
  canShare = false,
  canManageSettings = false,
  onRemoved,
  onRestored,
  onAlbumsChanged,
  onSearchPlace,
  onPlaceChanged,
}: PhotoViewerProps) {
  const t = useTranslations("photos.viewer");
  const tc = useTranslations("photos.viewer.compare");
  const locale = useLocale();
  const showToast = useToast();
  const item = items[index];
  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;
  const thumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : fileUrl;
  const [readyUrl, setReadyUrl] = useState<string | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const loadingOriginal = readyUrl !== fileUrl && failedUrl !== fileUrl;
  const [metadata, setMetadata] = useState<StoredFileMetadata | null>(null);
  const [tagsValue, setTagsValue] = useState(item.tags.join(","));
  const [albumOverrides, setAlbumOverrides] = useState<Record<string, FileAlbumRef[]>>({});
  const albums = albumOverrides[item.id] ?? item.albums;
  // Ort: aus den Metadaten (aktuell), sonst aus der Liste
  const place = metadata && metadata.id === item.id ? metadata.place ?? null : item.place ?? null;
  const { schedule, flush, saving, saveError } = useDeferredPopupSave();
  // Live Photo: spielt, solange der Zeiger über der Bühne liegt, oder per Live-Knopf (Touch/Tastatur).
  const [liveHover, setLiveHover] = useState(false);
  const [livePinned, setLivePinned] = useState(false);
  const [pop, setPop] = useState<Pop>(null);
  const [busy, setBusy] = useState(false);
  const [compare, setCompare] = useState<{ key: string; decisions: CompareDecisions } | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const downloadRef = useRef<HTMLButtonElement>(null);
  const shareRef = useRef<HTMLButtonElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  usePopupEscape(true, saveAndClose, rootRef);
  usePopupScrollLock(true);
  useModalFocus(true, rootRef);

  // Duplikate und ähnliche Aufnahmen: dieselben, im Hintergrund berechneten Gruppen wie die Tabs.
  const groupLoadError = t("groups.loadError");
  const duplicates = useSimilarityGroups("duplicate", "", [], groupLoadError);
  const series = useSimilarityGroups("series", "", [], groupLoadError);
  const reviewed = useReviewedSimilarityGroups();
  const groups = useMemo(
    () => groupsForItem(item.id, duplicates.groups, series.groups, reviewed),
    [item.id, duplicates.groups, series.groups, reviewed]
  );
  const flaggedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [kind, list] of [["duplicate", duplicates.groups], ["series", series.groups]] as const) {
      for (const group of list ?? []) {
        if (group.images.length < 2 || reviewed.has(groupKey(kind, group))) continue;
        group.images.forEach((image) => ids.add(image.id));
      }
    }
    return ids;
  }, [duplicates.groups, series.groups, reviewed]);
  const activeGroup = compare ? (groups.find((entry) => entry.key === compare.key) ?? null) : null;

  const hasPrev = index > 0;
  const hasNext = index < items.length - 1;
  const viewing = activeGroup === null;

  useEffect(() => {
    if (thumbnailUrl === fileUrl) return;
    let cancelled = false;
    const original = new Image();
    original.onload = async () => {
      try {
        await original.decode();
        if (!cancelled) setReadyUrl(fileUrl);
      } catch {
        // Keep the thumbnail if the original cannot be decoded.
        if (!cancelled) setFailedUrl(fileUrl);
      }
    };
    original.onerror = () => {
      if (!cancelled) setFailedUrl(fileUrl);
    };
    original.src = fileUrl;
    return () => {
      cancelled = true;
      original.onload = null;
      original.onerror = null;
    };
  }, [fileUrl, thumbnailUrl]);

  // Blättern: Pfeile oder J/L (Registry `media.previous`/`media.next`). Der Dispatcher lässt
  // die Tasten beim Tippen (Tag-Feld) und in Widgets aus (Audit MAIN-FE-006). Im Vergleich nicht.
  useShortcut("media.previous", () => (viewing && hasPrev ? onIndexChange(index - 1) : false), { scopeRef: rootRef });
  useShortcut("media.next", () => (viewing && hasNext ? onIndexChange(index + 1) : false), { scopeRef: rootRef });
  useShortcut("media.toggleBest", () => (viewing && canManage ? onToggleBest(item) : false), { scopeRef: rootRef });
  useShortcut("media.delete", () => (viewing && canManage ? setPop("delete") : false), { scopeRef: rootRef });

  // Wischgeste (Touch/Stift) zum Blättern - mobil sind die Pfeil-Buttons klein (Audit Dateien/Fotos).
  const swipeStartRef = useRef<{ x: number; y: number } | null>(null);
  function handlePointerDown(event: React.PointerEvent) {
    if (event.pointerType === "mouse") return;
    swipeStartRef.current = { x: event.clientX, y: event.clientY };
  }
  function handlePointerUp(event: React.PointerEvent) {
    const start = swipeStartRef.current;
    swipeStartRef.current = null;
    if (!start) return;
    const direction = swipeDirection(start.x, start.y, event.clientX, event.clientY);
    if (direction === "prev" && hasPrev) onIndexChange(index - 1);
    if (direction === "next" && hasNext) onIndexChange(index + 1);
  }

  useEffect(() => {
    setLiveHover(false);
    setLivePinned(false);
    setPop(null);
  }, [item.id]);

  useEffect(() => {
    setTagsValue(item.tags.join(","));
    setMetadata(null);
    // Beim schnellen Blaettern darf eine verspaetete Antwort des vorigen Fotos dessen Metadaten
    // nicht beim aktuellen anzeigen (Audit MAIN-FE-007).
    let cancelled = false;
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => { if (!cancelled) setMetadata(data); })
      .catch(() => { if (!cancelled) setMetadata(null); });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  function reloadPlace() {
    const id = item.id;
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => {
        setMetadata((current) => (current && current.id === data.id ? data : current));
        onPlaceChanged?.(id, data.place ?? null);
      })
      .catch(() => {});
  }

  function handleCaptureDateSaved(saved: StoredFileMetadata) {
    setMetadata((current) => (current && current.id === saved.id ? saved : current));
    onCaptureDateSaved?.(item.id, saved);
  }

  function handleTagsChange(value: string) {
    setTagsValue(value);
    const tags = value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [];
    schedule(async () => {
      const saved = await browserApiFetch<string[]>(item.tags_url, { method: "PATCH", body: JSON.stringify({ tags }) });
      onTagsSaved(item.id, saved ?? tags);
    });
  }

  function handleAlbumsChange(next: FileAlbumRef[]) {
    setAlbumOverrides((current) => ({ ...current, [item.id]: next }));
    onAlbumsChanged?.(item.id, next);
  }

  async function saveAndClose() {
    if (await flush()) onClose();
  }

  /** Papierkorb mit «Rückgängig» im Toast. Einzelfoto über POST /files/trash, Vergleich über
   * POST /files/bulk-delete (beides file_trash_service; nicht löschbare Fotos lehnt das Backend ab). */
  async function moveToTrash(ids: string[], group: { key: string; group: (typeof groups)[number]["group"] } | null) {
    if (busy) return;
    setBusy(true);
    try {
      let removed: string[] = [];
      let errors: string[] = [];
      if (ids.length > 0) {
        if (group) {
          const result = await browserApiFetch<FileBulkDeleteResult>("/api/files/bulk-delete", { method: "POST", body: JSON.stringify({ file_ids: ids }) });
          removed = result?.deleted_ids ?? [];
          errors = result?.errors ?? [];
        } else {
          const result = await browserApiFetch<FileTrashActionResult>("/api/files/trash", { method: "POST", body: JSON.stringify({ file_ids: ids }) });
          removed = result?.file_ids ?? [];
          errors = result?.errors ?? [];
        }
      }
      if (group && errors.length === 0) markSimilarityGroupReviewed(group.key);
      if (errors.length > 0) showToast(errors.join(" · "), removed.length > 0 ? "info" : "error");
      if (removed.length > 0) {
        removeFromSimilarityCache(removed);
        onRemoved?.(removed, nextAfterRemoval(item.id, removed, group?.group ?? null));
      }
      setPop(null);
      setCompare(null);
      if (removed.length === 0 && errors.length > 0) return;
      const message = removed.length === 0
        ? (group?.key.startsWith("duplicate:") ? tc("reviewedDuplicates") : tc("reviewedSimilar"))
        : removed.length === 1 && !group
          ? t("trashedOne", { name: item.original_name })
          : t("trashedMany", { count: removed.length });
      showToast(message, "success", { action: { label: t("undo"), onClick: () => void undo(removed, group?.key ?? null) } });
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("trashError"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function undo(ids: string[], key: string | null) {
    try {
      if (ids.length > 0) {
        const result = await browserApiFetch<FileTrashActionResult>("/api/files/trash/restore", { method: "POST", body: JSON.stringify({ file_ids: ids }) });
        const restored = result?.file_ids ?? [];
        if (restored.length > 0) onRestored?.(restored);
        if (result?.errors.length) showToast(result.errors.join(" · "), "error");
      }
      if (key) unmarkSimilarityGroupReviewed(key);
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("undoError"), "error");
    }
  }

  function openCompare(key: string) {
    const entry = groups.find((candidate) => candidate.key === key);
    if (!entry) return;
    setPop(null);
    setCompare({ key, decisions: compareSuggestion(entry.group) });
  }

  // Same SSR guard ui/lightbox-image.tsx already has for its own createPortal call.
  if (typeof document === "undefined") {
    return null;
  }

  const dateSource = metadata?.date_source ?? item.date_source;
  const dateKind = dateSource === "estimated" ? "estimated" : dateSource === "corrected" ? "corrected" : null;
  let time: string | null = null;
  if (metadata?.capture_corrected_at) time = metadata.capture_corrected_has_time ? metadata.capture_corrected_at.slice(11, 16) : null;
  else if (metadata?.exif_taken_at) time = metadata.exif_taken_at.slice(11, 16);
  const subtitleDate = item.group_date
    ? time ? t("subtitleDateTime", { date: formatWeekdayDate(item.group_date, locale), time }) : formatWeekdayDate(item.group_date, locale)
    : t("dateUnknown");
  const stageHint = groups.map((entry) => (entry.kind === "duplicate"
    ? t("groups.hintDuplicates", { count: entry.group.images.length - 1 })
    : t("groups.hintSimilar", { count: entry.group.images.length - 1 }))).join(" · ");
  const [stripStart, stripEnd] = filmstripRange(index, items.length);
  const manageHref = canManageSettings ? "/tenant-settings/links" as const : "/shared-links" as const;

  return createPortal(
    <div ref={rootRef} className="photo-viewer" role="dialog" aria-modal="true" aria-label={item.original_name} tabIndex={-1}>
      {saveError && <p role="alert" className="photo-viewer-error">{saveError}</p>}
      <header className="photo-viewer-header">
        <div className="photo-viewer-header-left">
          <button type="button" className="photo-viewer-icon-button" aria-label={t("close")} title={t("closeTitle")} onClick={() => void saveAndClose()}>
            <ActionIcon name="close" />
          </button>
          <div className="photo-viewer-heading">
            <div className="photo-viewer-title-row">
              <span className="photo-viewer-title">{item.original_name}</span>
              {item.live_video_url ? <span className="photo-viewer-badge-live">{t("liveBadge")}</span> : null}
              {item.is_best ? <span className="photo-viewer-badge-best"><PhotoActionIcon name="star" />{t("bestBadge")}</span> : null}
            </div>
            <div className="photo-viewer-subtitle">
              <span>{subtitleDate}</span>
              {dateKind ? <span className={`photo-viewer-date-badge photo-viewer-date-badge-${dateKind}`}>{t(`dateBadge.${dateKind}`)}</span> : null}
              {item.group_date && dateSource === "upload" ? <PhotoDateMarker kind="upload" /> : null}
              {place ? (
                <>
                  <span aria-hidden="true">·</span>
                  <PhotoViewerPlaceLink place={place} onSearchPlace={onSearchPlace} />
                </>
              ) : null}
              <span aria-hidden="true">·</span>
              <span className="photo-viewer-position">{t("position", { index: index + 1, total: items.length })}</span>
            </div>
          </div>
        </div>
        <div className="photo-viewer-actions">
          {canManage ? (
            <button
              type="button"
              className={item.is_best ? "button-secondary photo-viewer-action photo-viewer-action-best" : "button-secondary photo-viewer-action"}
              aria-pressed={Boolean(item.is_best)}
              aria-keyshortcuts={ariaKeyShortcuts("media.toggleBest")}
              title={t("bestTitle")}
              onClick={() => onToggleBest(item)}
            >
              <PhotoActionIcon name="star" />
              <span className="photo-viewer-action-label">{item.is_best ? t("bestOn") : t("bestOff")}</span>
            </button>
          ) : null}
          {item.live_video_url ? (
            <button type="button" className="button-secondary photo-viewer-action" aria-pressed={livePinned} onClick={() => setLivePinned((pinned) => !pinned)}>
              <PhotoActionIcon name="live" />
              <span className="photo-viewer-action-label">{t("playLivePhoto")}</span>
            </button>
          ) : null}
          {item.live_video_url ? (
            <>
              <button
                ref={downloadRef}
                type="button"
                className="button-secondary photo-viewer-action"
                aria-haspopup="menu"
                aria-expanded={pop === "download"}
                aria-label={t("download")}
                onClick={() => setPop((current) => (current === "download" ? null : "download"))}
              >
                <PhotoActionIcon name="download" />
              </button>
              <Popover open={pop === "download"} onOpenChange={(open) => setPop(open ? "download" : null)} anchorRef={downloadRef} align="end" label={t("downloadLive")}>
                <div className="menu">
                  <div className="menu-section-label" aria-hidden="true">{t("downloadLive")}</div>
                  {liveDownloadOptions(t).map((option) => (
                    <a
                      key={option.part}
                      role="menuitem"
                      className="menu-item"
                      href={`${browserApiBaseUrl}/api/stored-files/${item.id}/download?part=${option.part}`}
                      onClick={() => setPop(null)}
                    >
                      <span className="menu-item-label">{option.label}</span>
                    </a>
                  ))}
                </div>
              </Popover>
            </>
          ) : (
            <a className="button-secondary photo-viewer-action" href={`${browserApiBaseUrl}/api/stored-files/${item.id}/download?part=image`} aria-label={t("download")} title={t("download")}>
              <PhotoActionIcon name="download" />
            </a>
          )}
          {canShare ? (
            <>
              <button
                ref={shareRef}
                type="button"
                className="button-secondary photo-viewer-action"
                aria-haspopup="dialog"
                aria-expanded={pop === "share"}
                onClick={() => setPop((current) => (current === "share" ? null : "share"))}
              >
                <PhotoActionIcon name="link" />
                <span className="photo-viewer-action-label">{t("share.button")}</span>
              </button>
              <Popover open={pop === "share"} onOpenChange={(open) => setPop(open ? "share" : null)} anchorRef={shareRef} align="end" role="dialog" label={t("share.title")} className="photo-viewer-popover">
                <PhotoViewerShare key={item.id} item={item} manageHref={manageHref} />
              </Popover>
            </>
          ) : null}
          {canManage ? (
            <>
              <button
                ref={deleteRef}
                type="button"
                className="button-secondary photo-viewer-action photo-viewer-action-danger"
                aria-haspopup="dialog"
                aria-expanded={pop === "delete"}
                aria-keyshortcuts={ariaKeyShortcuts("media.delete")}
                title={t("deleteTitle")}
                onClick={() => setPop((current) => (current === "delete" ? null : "delete"))}
              >
                <PhotoActionIcon name="delete" />
                <span className="photo-viewer-action-label">{t("delete.button")}</span>
              </button>
              <Popover
                open={pop === "delete"}
                onOpenChange={(open) => setPop(open ? "delete" : null)}
                anchorRef={deleteRef}
                align="end"
                role="dialog"
                label={isDeletable(item) ? t("delete.title") : t("delete.lockedTitle")}
                className="photo-viewer-popover"
              >
                <PhotoViewerDelete item={item} busy={busy} onCancel={() => setPop(null)} onConfirm={() => void moveToTrash([item.id], null)} />
              </Popover>
            </>
          ) : null}
          <span className="photo-viewer-actions-divider" aria-hidden="true" />
          <a href={fileUrl} target="_blank" rel="noreferrer" className="button-primary photo-viewer-action photo-viewer-action-original">
            <span className="photo-viewer-action-label">{t("openOriginal")}</span>
            <PhotoActionIcon name="external" />
          </a>
        </div>
      </header>

      <div className="photo-viewer-body">
        <div className="photo-viewer-main">
          {activeGroup && compare ? (
            <PhotoViewerCompare
              groups={groups}
              active={activeGroup}
              currentId={item.id}
              decisions={compare.decisions}
              busy={busy}
              onSelectGroup={openCompare}
              onDecisions={(decisions) => setCompare({ key: activeGroup.key, decisions })}
              onExit={() => setCompare(null)}
              onApply={() => {
                if (!canManage) return;
                void moveToTrash(compareSummary(activeGroup.group, compare.decisions).trashIds, activeGroup);
              }}
            />
          ) : (
            <>
              <div
                className="photo-viewer-stage"
                onPointerDown={handlePointerDown}
                onPointerUp={handlePointerUp}
                onPointerCancel={() => { swipeStartRef.current = null; }}
                onMouseEnter={item.live_video_url ? () => setLiveHover(true) : undefined}
                onMouseLeave={item.live_video_url ? () => setLiveHover(false) : undefined}
              >
                {groups.length > 0 && canManage ? (
                  <button type="button" className="photo-viewer-stage-hint" onClick={() => openCompare(groups[0].key)}>
                    <span className="photo-viewer-dot photo-viewer-dot-flag" aria-hidden="true" />
                    {t("groups.hint", { groups: stageHint })}
                  </button>
                ) : null}
                {hasPrev && (
                  <button type="button" className="photo-viewer-nav photo-viewer-nav-prev" aria-label={t("prevPhoto")} aria-keyshortcuts={ariaKeyShortcuts("media.previous")} onClick={() => onIndexChange(index - 1)}>
                    <PhotoActionIcon name="prev" />
                  </button>
                )}
                <div className="photo-viewer-frame">
                  <img
                    src={readyUrl === fileUrl ? fileUrl : thumbnailUrl}
                    alt={item.original_name}
                    className="photo-viewer-img"
                    onLoad={() => { if (thumbnailUrl === fileUrl) setReadyUrl(fileUrl); }}
                    onError={() => { if (thumbnailUrl === fileUrl) setFailedUrl(fileUrl); }}
                  />
                  {item.live_video_url && (
                    <LivePhotoClip
                      key={item.id}
                      src={`${browserApiBaseUrl}${item.live_video_url}`}
                      active={liveHover || livePinned}
                      className="photo-viewer-live-video"
                    />
                  )}
                </div>
                {loadingOriginal && (
                  <div className="photo-viewer-loading" role="status" aria-label={t("originalLoading")}>
                    <span className="photo-viewer-loading-spinner" aria-hidden="true" />
                  </div>
                )}
                {hasNext && (
                  <button type="button" className="photo-viewer-nav photo-viewer-nav-next" aria-label={t("nextPhoto")} aria-keyshortcuts={ariaKeyShortcuts("media.next")} onClick={() => onIndexChange(index + 1)}>
                    <PhotoActionIcon name="next" />
                  </button>
                )}
              </div>
              {items.length > 1 ? (
                <nav className="photo-viewer-filmstrip" aria-label={t("filmstripLabel")}>
                  {items.slice(stripStart, stripEnd).map((entry, offset) => {
                    const entryIndex = stripStart + offset;
                    const current = entryIndex === index;
                    return (
                      <button
                        key={entry.id}
                        type="button"
                        className={`photo-viewer-thumb${current ? " photo-viewer-thumb-current" : ""}`}
                        aria-current={current ? "true" : undefined}
                        aria-label={entry.original_name}
                        onClick={() => onIndexChange(entryIndex)}
                      >
                        <img src={`${browserApiBaseUrl}${entry.thumbnail_url ?? entry.content_url}`} alt="" loading="lazy" decoding="async" draggable={false} />
                        {flaggedIds.has(entry.id) ? <span className="photo-viewer-thumb-flag" aria-hidden="true" /> : null}
                        {entry.is_best ? <span className="photo-viewer-thumb-best" aria-hidden="true">★</span> : null}
                      </button>
                    );
                  })}
                </nav>
              ) : null}
            </>
          )}
        </div>

        <PhotoViewerSidebar
          item={item}
          metadata={metadata}
          groups={canManage ? groups : null}
          canManage={canManage}
          albums={albums}
          tagsValue={tagsValue}
          saving={saving}
          onOpenGroup={openCompare}
          onCaptureDateSaved={handleCaptureDateSaved}
          onAlbumsChange={handleAlbumsChange}
          onTagsChange={handleTagsChange}
          place={place}
          onSearchPlace={onSearchPlace}
          onPlaceChanged={reloadPlace}
        />
      </div>
    </div>,
    document.body
  );
}
