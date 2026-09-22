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
  onToggleGroup,
}: {
  items: FileOverviewItem[];
  grouped: boolean;
  selectedIds: Set<string>;
  onOpen: (item: FileOverviewItem) => void;
  onToggleSelect: (id: string) => void;
  onToggleGroup: (ids: string[]) => void;
}) {
  const groups = useMemo(() => groupPhotosByDate(items), [items]);
  const selectionMode = selectedIds.size > 0;

  if (!grouped) {
    return (
      <div className="photo-grid">
        {items.map((item) => (
          <PhotoTile
            key={item.id}
            item={item}
            selected={selectedIds.has(item.id)}
            selectionMode={selectionMode}
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
          <button
            type="button"
            className="button-ghost photo-date-header"
            aria-pressed={group.items.every((item) => selectedIds.has(item.id))}
            title="Alle Fotos dieser Datumsgruppe markieren oder abwählen"
            onClick={() => onToggleGroup(group.items.map((item) => item.id))}
          >
            <span className="photo-date-weekday">{formatWeekdayDate(group.date)}</span>
            {group.contextLabel && <span className="photo-date-context">{group.contextLabel}</span>}
            <span className="photo-date-count">
              · {group.items.length} {group.items.length === 1 ? "Foto" : "Fotos"}
            </span>
          </button>
          <div className="photo-grid">
            {group.items.map((item) => (
              <PhotoTile
                key={item.id}
                item={item}
                selected={selectedIds.has(item.id)}
                selectionMode={selectionMode}
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
