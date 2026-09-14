"use client";

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
  const thumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : `${browserApiBaseUrl}${item.content_url}`;

  return (
    <div className={`photo-tile${selected ? " photo-tile-selected" : ""}`}>
      <button type="button" className="photo-tile-preview" onClick={onOpen}>
        <img alt={item.original_name} src={thumbnailUrl} loading="lazy" decoding="async" className="photo-tile-img" />
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
