"use client";

import { useMemo } from "react";

import { groupPhotosByDate } from "./grouping";
import { PhotoTile } from "./photo-tile";
import { formatWeekdayDate } from "@/lib/utils/format";
import { FileOverviewItem } from "@/types/api";

// First rows are almost certainly already in the viewport on load, so they skip native lazy
// loading and get fetched immediately instead of waiting for an intersection check. Both
// branches below render `items` in the same order (groupPhotosByDate only buckets it into
// contiguous date sections, see its own docstring), so this set lines up with either.
const PRIORITY_IMAGE_COUNT = 12;

export function PhotoDateGroups({
  items,
  grouped,
  selectedIds,
  onOpen,
  onToggleSelect,
}: {
  items: FileOverviewItem[];
  grouped: boolean;
  selectedIds: Set<string>;
  onOpen: (item: FileOverviewItem) => void;
  onToggleSelect: (id: string) => void;
}) {
  // Both re-walk the full `items` array (groupPhotosByDate also does several .flatMap/
  // .filter passes per group for its majority-vote context label) - memoized so they only
  // recompute when the photo list itself changes, not on every render (e.g. a selection
  // toggle, or every keystroke in the parent's search box before the debounced fetch even
  // fires) - audit fix, 2026-09-17.
  const priorityIds = useMemo(() => new Set(items.slice(0, PRIORITY_IMAGE_COUNT).map((item) => item.id)), [items]);
  const groups = useMemo(() => groupPhotosByDate(items), [items]);

  if (!grouped) {
    return (
      <div className="photo-grid">
        {items.map((item) => (
          <PhotoTile
            key={item.id}
            item={item}
            selected={selectedIds.has(item.id)}
            priority={priorityIds.has(item.id)}
            onOpen={() => onOpen(item)}
            onToggleSelect={() => onToggleSelect(item.id)}
          />
        ))}
      </div>
    );
  }

  return (
    <>
      {groups.map((group) => (
        <div key={group.key} className="photo-date-group">
          <div className="photo-date-header">
            <span className="photo-date-weekday">{formatWeekdayDate(group.date)}</span>
            {group.contextLabel && <span className="photo-date-context">{group.contextLabel}</span>}
            <span className="photo-date-count">
              · {group.items.length} {group.items.length === 1 ? "Foto" : "Fotos"}
            </span>
          </div>
          <div className="photo-grid">
            {group.items.map((item) => (
              <PhotoTile
                key={item.id}
                item={item}
                selected={selectedIds.has(item.id)}
                priority={priorityIds.has(item.id)}
                onOpen={() => onOpen(item)}
                onToggleSelect={() => onToggleSelect(item.id)}
              />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
