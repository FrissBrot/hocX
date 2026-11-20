"use client";

import { useTranslations } from "next-intl";

import { announce } from "@/lib/a11y/announce";

/**
 * Sichtbare Alternative zum Ziehen (WCAG 2.1.1/2.5.7): «nach oben»/«nach unten» für Zeilen, die
 * per Drag-and-Drop sortiert werden. Nach dem Verschieben bleibt der Fokus auf demselben Knopf der
 * verschobenen Zeile (bzw. dem anderen, wenn der Rand erreicht ist), Screenreader hören die neue
 * Position. `itemKey` muss je Zeile eindeutig und stabil sein.
 */
export function ReorderButtons({
  itemKey,
  name,
  index,
  count,
  onMove,
  disabled,
}: {
  itemKey: string;
  name: string;
  index: number;
  count: number;
  onMove: (from: number, to: number) => void | Promise<unknown>;
  disabled?: boolean;
}) {
  const t = useTranslations("common.keyboard");

  async function move(direction: -1 | 1) {
    const to = index + direction;
    if (to < 0 || to >= count) return;
    await onMove(index, to);
    announce(t("moved", { name, position: to + 1, total: count }));
    window.requestAnimationFrame(() => {
      const atEdge = (direction === -1 && to === 0) || (direction === 1 && to === count - 1);
      const wanted = atEdge ? (direction === -1 ? "down" : "up") : direction === -1 ? "up" : "down";
      document.querySelector<HTMLElement>(`[data-reorder-key="${CSS.escape(`${itemKey}-${wanted}`)}"]`)?.focus();
    });
  }

  return (
    <span className="reorder-buttons">
      <button
        type="button"
        className="button-icon-soft"
        data-reorder-key={`${itemKey}-up`}
        aria-label={t("moveUp", { name })}
        title={t("moveUp", { name })}
        disabled={disabled || index === 0}
        onClick={(event) => {
          event.stopPropagation();
          void move(-1);
        }}
      >
        <span aria-hidden="true">↑</span>
      </button>
      <button
        type="button"
        className="button-icon-soft"
        data-reorder-key={`${itemKey}-down`}
        aria-label={t("moveDown", { name })}
        title={t("moveDown", { name })}
        disabled={disabled || index === count - 1}
        onClick={(event) => {
          event.stopPropagation();
          void move(1);
        }}
      >
        <span aria-hidden="true">↓</span>
      </button>
    </span>
  );
}
