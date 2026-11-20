import type { KeyboardEvent as ReactKeyboardEvent } from "react";

/**
 * Roving tabindex für Gruppen mit genau einem Tab-Halt (Tabs, Filter-Schienen, Werkzeugleisten),
 * WAI-ARIA APG: Pfeile wandern zwischen den Einträgen, Pos1/Ende springen an den Rand.
 * Das aktive Element hat tabIndex=0, alle anderen -1 - das setzt die Komponente beim Rendern.
 *
 * `onMove` bekommt das neue Element; Tabs mit automatischer Aktivierung wählen es dort gleich aus
 * (Inhalt wechselt sofort), Link-Tabs (RouteTabs) verschieben nur den Fokus und navigieren mit Enter.
 */
export function rovingKeyDown(
  event: ReactKeyboardEvent<HTMLElement>,
  options: { itemSelector: string; orientation?: "horizontal" | "vertical" | "both"; onMove?: (element: HTMLElement) => void }
): void {
  if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
  const orientation = options.orientation ?? "horizontal";
  const forward = (orientation !== "vertical" && event.key === "ArrowRight") || (orientation !== "horizontal" && event.key === "ArrowDown");
  const backward = (orientation !== "vertical" && event.key === "ArrowLeft") || (orientation !== "horizontal" && event.key === "ArrowUp");
  if (!forward && !backward && event.key !== "Home" && event.key !== "End") return;
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(options.itemSelector)).filter(
    (item) => !item.hasAttribute("disabled") && item.getAttribute("aria-disabled") !== "true"
  );
  if (!items.length) return;
  const current = items.indexOf(document.activeElement as HTMLElement);
  if (current < 0) return;
  // Rechts-nach-links-Schrift: Pfeile tauschen
  const rtl = getComputedStyle(event.currentTarget).direction === "rtl" && orientation !== "vertical";
  const step = (forward ? 1 : -1) * (rtl && (event.key === "ArrowLeft" || event.key === "ArrowRight") ? -1 : 1);
  const index =
    event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (current + step + items.length) % items.length;
  event.preventDefault();
  const next = items[index];
  next.focus();
  options.onMove?.(next);
}
