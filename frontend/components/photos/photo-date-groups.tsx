"use client";

import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";

import { groupPhotosByDate } from "./grouping";
import { dateMarkersFor, PhotoDateMarker } from "./photo-date-marker";
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
  const t = useTranslations("photos.dateGroups");
  const locale = useLocale();
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
          <div className="photo-date-heading">
            <div className="photo-date-heading-labels">
              <h2 className="photo-date-weekday">{formatWeekdayDate(group.date, locale)}</h2>
              <span className="photo-date-context">
                {group.contextLabel}{group.contextLabel ? " " : null}{t("groupCount", { count: group.items.length })}
              </span>
              {dateMarkersFor(group.items.map((item) => item.date_source)).map((marker) => (
                <PhotoDateMarker key={marker.kind} variant="pill" {...marker} />
              ))}
            </div>
            <button type="button" className="button-secondary button-ghost photo-date-select-all" aria-pressed={group.items.every((item) => selectedIds.has(item.id))} onClick={() => onToggleGroup(group.items.map((item) => item.id))}>
              {group.items.every((item) => selectedIds.has(item.id)) ? t("deselectDay") : t("selectDay")}
            </button>
          </div>
          {/* Fotos einer Wandertour (automatisches Album, photo_tour_link_service) bilden innerhalb
              des Tages eine eigene Untergruppe; nicht zugeordnete Fotos bleiben ohne Kopfzeile. */}
          {group.tourGroups.map((tourGroup) => (
            <div key={tourGroup.key} className="photo-tour-group">
              {tourGroup.title && (
                <button
                  type="button"
                  className="button-ghost photo-tour-heading"
                  aria-pressed={tourGroup.items.every((item) => selectedIds.has(item.id))}
                  title={t("selectTour")}
                  onClick={() => onToggleGroup(tourGroup.items.map((item) => item.id))}
                >
                  <span className="photo-date-context">{tourGroup.title}</span>
                  <span className="photo-date-count">{t("groupCount", { count: tourGroup.items.length })}</span>
                </button>
              )}
              <div className="photo-grid">
                {tourGroup.items.map((item) => (
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
        </div>
      ))}
    </>
  );
}
