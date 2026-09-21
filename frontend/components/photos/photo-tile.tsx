"use client";

import { useEffect, useRef, useState } from "react";
import { LivePhotoClip } from "@/components/photos/live-photo-clip";
import { browserApiBaseUrl } from "@/lib/api/client";
import { FileOverviewItem } from "@/types/api";

export function PhotoTile({
  item,
  selected,
  selectionMode,
  onOpen,
  onToggleSelect,
}: {
  item: FileOverviewItem;
  selected: boolean;
  selectionMode: boolean;
  onOpen: () => void;
  onToggleSelect: () => void;
}) {
  const previewRef = useRef<HTMLButtonElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [requestedUrl, setRequestedUrl] = useState<string | null>(null);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  // Live Photo: der Clip spielt, solange der Zeiger auf der Kachel liegt (oder sie per Tastatur fokussiert ist).
  const [liveActive, setLiveActive] = useState(false);
  const thumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : `${browserApiBaseUrl}${item.content_url}`;
  const requested = requestedUrl === thumbnailUrl;
  const loaded = loadedUrl === thumbnailUrl;

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
  const aspectRatio = item.width && item.height ? item.width / item.height : 4 / 3;

  return (
    <div
      className={`photo-tile${selected ? " photo-tile-selected" : ""}`}
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
        <img
          ref={imageRef}
          alt={item.original_name}
          src={requested ? thumbnailUrl : undefined}
          loading="lazy"
          decoding="async"
          className="photo-tile-img photo-tile-img-fitted"
          onLoad={() => { if (requested) setLoadedUrl(thumbnailUrl); }}
        />
      </button>
      {item.live_video_url && (
        <>
          <LivePhotoClip src={`${browserApiBaseUrl}${item.live_video_url}`} active={liveActive} className="photo-tile-live-video" />
          <span className="photo-tile-badge photo-tile-badge-live">LIVE</span>
        </>
      )}
      <button
        type="button"
        className={`photo-tile-select${selected ? " photo-tile-select-checked" : ""}`}
        role="checkbox"
        aria-checked={selected}
        aria-label={selected ? "Auswahl aufheben" : "Auswählen"}
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
      {item.is_best && <span className="photo-tile-badge">★ Best-of</span>}
    </div>
  );
}
