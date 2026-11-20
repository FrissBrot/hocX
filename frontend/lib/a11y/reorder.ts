import type { KeyboardEvent as ReactKeyboardEvent } from "react";

/**
 * Tastatur-Alternative zu Drag-and-Drop (WCAG 2.1.1, 2.5.7): Alt+Pfeil verschiebt das
 * fokussierte Element um eine Position (vertikal: hoch/runter, horizontal: links/rechts).
 * Dieselbe Kombination nutzt das Document Studio (Registry: `standard.reorder`, `designer.move`).
 *
 * `move(from, to)` führt die Verschiebung aus; danach bekommt das Element mit `focusKey`
 * (data-reorder-key) den Fokus zurück, weil React Zeilen beim Umsortieren neu einhängen kann.
 */
export function reorderKeyDown(
  event: ReactKeyboardEvent<HTMLElement>,
  options: {
    index: number;
    count: number;
    move: (from: number, to: number) => void | Promise<unknown>;
    orientation?: "vertical" | "horizontal";
    focusKey?: string;
  }
): void {
  if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const vertical = (options.orientation ?? "vertical") === "vertical";
  const back = vertical ? "ArrowUp" : "ArrowLeft";
  const forward = vertical ? "ArrowDown" : "ArrowRight";
  if (event.key !== back && event.key !== forward) return;
  event.preventDefault();
  event.stopPropagation();
  const to = options.index + (event.key === forward ? 1 : -1);
  if (to < 0 || to >= options.count) return;
  const done = options.move(options.index, to);
  const refocus = () => {
    if (!options.focusKey) return;
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(`[data-reorder-key="${CSS.escape(options.focusKey!)}"]`)?.focus();
    });
  };
  if (done && typeof (done as Promise<unknown>).then === "function") void (done as Promise<unknown>).then(refocus, refocus);
  else refocus();
}
