"use client";

import { useEffect, useRef, useState } from "react";
import { browserApiBaseUrl } from "@/lib/api/client";
import { FileOverviewItem } from "@/types/api";

export function PhotoTile({
  item,
  selected,
  onOpen,
  onToggleSelect,
}: {
  item: FileOverviewItem;
  selected: boolean;
  onOpen: () => void;
  onToggleSelect: () => void;
}) {
  const previewRef = useRef<HTMLButtonElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [requestedUrl, setRequestedUrl] = useState<string | null>(null);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
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
    <div className={`photo-tile${selected ? " photo-tile-selected" : ""}`}>
      <button
        type="button"
        ref={previewRef}
        className={`photo-tile-preview${loaded ? " photo-tile-preview-loaded" : ""}`}
        style={{ aspectRatio }}
        onClick={onOpen}
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
