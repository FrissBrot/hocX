"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { PhotoActionIcon } from "./photo-action-icon";
import { LivePhotoClip } from "@/components/photos/live-photo-clip";
import { browserApiBaseUrl } from "@/lib/api/client";
import { useImageRetry } from "@/lib/hooks/use-image-retry";
import { FileOverviewItem } from "@/types/api";

// Während der Virenprüfung (425): bis zu sechsmal im Abstand von 10 s erneut laden.
const PENDING_RETRY_DELAYS_MS: readonly number[] = Array.from({ length: 6 }, () => 10000);

export function PhotoTile({
  item,
  selected,
  selectionMode,
  onOpen,
  onToggleSelect,
  square = false,
}: {
  item: FileOverviewItem;
  selected: boolean;
  selectionMode: boolean;
  onOpen: () => void;
  onToggleSelect: () => void;
  /** Zeitleiste (photo-timeline.tsx): feste quadratische Kachel, Höhe nie gemessen - sonst
   * verschiebt das Nachmessen nach dem Laden die ganze Galerie. */
  square?: boolean;
}) {
  const t = useTranslations("photos.tile");
  const previewRef = useRef<HTMLButtonElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [rowSpan, setRowSpan] = useState<number>();
  const [requestedUrl, setRequestedUrl] = useState<string | null>(null);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  // Live Photo: der Clip spielt, solange der Zeiger auf der Kachel liegt (oder sie per Tastatur fokussiert ist).
  const [liveActive, setLiveActive] = useState(false);
  // Vorschau nicht ladbar: vorübergehende Fehler (503 «Vorschau wird erzeugt»/Überlast, 429,
  // Abbruch) wiederholt useImageRetry begrenzt mit Backoff; erst danach erscheint der Hinweis
  // (Bug 1.6: vorher blieb ein einzelner Fehlschlag bis zum erneuten Mounten stehen). Bei
  // "wird geprüft" (425) in festen Abständen von 10 s.
  const scanStatus = item.scan_status ?? "clean";
  const blocked = scanStatus === "error" || scanStatus === "infected";
  const baseThumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : `${browserApiBaseUrl}${item.content_url}`;
  const image = useImageRetry(baseThumbnailUrl, scanStatus === "pending" ? { delays: PENDING_RETRY_DELAYS_MS } : undefined);
  const thumbnailUrl = image.src ?? baseThumbnailUrl;
  // Während der Virenprüfung zeigt die Kachel schon beim Warten den Prüf-Hinweis (wie bisher).
  const failed = image.failed || (scanStatus === "pending" && image.waiting);
  const requested = requestedUrl === thumbnailUrl;
  const loaded = loadedUrl === thumbnailUrl;
  const placeholderTone = Array.from(item.id).reduce((hash, character) => hash + character.charCodeAt(0), 0) % 6;

  useEffect(() => {
    const preview = previewRef.current;
    const grid = preview?.parentElement?.parentElement;
    if (square || !preview || !grid || typeof ResizeObserver === "undefined") return;
    // Die Höhe folgt dem Bildformat; der Abstand kommt aus dem jeweiligen Theme/Layout.
    const measure = () => {
      if (getComputedStyle(grid).display !== "grid") return;
      const gap = parseFloat(getComputedStyle(grid).getPropertyValue("--photo-grid-gap")) || 0;
      setRowSpan(Math.ceil(preview.getBoundingClientRect().height + gap));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(preview);
    measure();
    return () => observer.disconnect();
  }, [item.width, item.height, square]);

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview) return;
    // No src until the placeholder actually enters the viewport. Native lazy loading
    // can prefetch images several screens away; rootMargin: 0 prevents that here.
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting && entry.intersectionRatio > 0)) {
        setRequestedUrl(thumbnailUrl);
        observer.disconnect();
      }
    }, { rootMargin: "0px", threshold: 0 });
    observer.observe(preview);
    return () => observer.disconnect();
  }, [thumbnailUrl]);

  useEffect(() => {
    const image = imageRef.current;
    if (requested && image?.complete && image.naturalWidth > 0) setLoadedUrl(thumbnailUrl);
  }, [requested, thumbnailUrl]);

  // Reserve space even for older photos whose dimensions are not yet known.
  const aspectRatio = square ? 1 : item.width && item.height ? item.width / item.height : 4 / 3;

  return (
    <div
      className={`photo-tile photo-tile-tone-${placeholderTone}${square ? " photo-tile-square" : ""}${selected ? " photo-tile-selected" : ""}`}
      style={rowSpan && !square ? { gridRowEnd: `span ${rowSpan}` } : undefined}
      onMouseEnter={item.live_video_url ? () => setLiveActive(true) : undefined}
      onMouseLeave={item.live_video_url ? () => setLiveActive(false) : undefined}
      onFocus={item.live_video_url ? () => setLiveActive(true) : undefined}
      onBlur={item.live_video_url ? () => setLiveActive(false) : undefined}
    >
      <button
        type="button"
        ref={previewRef}
        className={`photo-tile-preview${loaded ? " photo-tile-preview-loaded" : ""}`}
        style={{ aspectRatio }}
        onClick={selectionMode ? onToggleSelect : onOpen}
      >
        {!blocked && !failed && (
          <img
            ref={imageRef}
            alt={item.original_name}
            src={requested ? thumbnailUrl : undefined}
            loading="lazy"
            decoding="async"
            className="photo-tile-img photo-tile-img-fitted"
            onLoad={() => { if (requested) setLoadedUrl(thumbnailUrl); }}
            onError={() => { if (requested) image.onError(); }}
          />
        )}
        {(blocked || failed) && (
          <span className="photo-tile-fallback">{blocked ? t("blockedHint") : scanStatus === "pending" ? t("scanningHint") : t("previewUnavailable")}</span>
        )}
      </button>
      {scanStatus === "pending" && <span className="photo-tile-badge photo-tile-badge-scan">{t("scanningBadge")}</span>}
      {blocked && <span className="photo-tile-badge photo-tile-badge-scan photo-tile-badge-blocked">{t("blockedBadge")}</span>}
      {item.live_video_url && (
        <>
          <LivePhotoClip src={`${browserApiBaseUrl}${item.live_video_url}`} active={liveActive} className="photo-tile-live-video" />
          <span className="photo-tile-badge photo-tile-badge-live">{t("liveBadge")}</span>
        </>
      )}
      <button
        type="button"
        className={`photo-tile-select${selected ? " photo-tile-select-checked" : ""}`}
        role="checkbox"
        aria-checked={selected}
        aria-label={selected ? t("deselectAriaLabel", { name: item.original_name }) : t("selectAriaLabel", { name: item.original_name })}
        onClick={(event) => {
          event.stopPropagation();
          onToggleSelect();
        }}
      >
        {selected && (
          <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 8.5l3 3 7-7" />
          </svg>
        )}
      </button>
      {item.is_best && <span className="photo-tile-badge photo-tile-badge-best" aria-label={t("bestBadge")} title={t("bestBadge")}><PhotoActionIcon name="star" /></span>}
      {item.share_pending && <span className="photo-tile-badge photo-tile-badge-pending">{t("pendingBadge")}</span>}
    </div>
  );
}
