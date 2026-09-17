"use client";

import { useMemo } from "react";

import { groupPhotosByDate } from "./grouping";
import { PhotoTile } from "./photo-tile";
import { formatWeekdayDate } from "@/lib/utils/format";
import { FileOverviewItem } from "@/types/api";

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
  const groups = useMemo(() => groupPhotosByDate(items), [items]);

  if (!grouped) {
    return (
      <div className="photo-grid">
        {items.map((item) => (
          <PhotoTile
            key={item.id}
            item={item}
            selected={selectedIds.has(item.id)}
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
