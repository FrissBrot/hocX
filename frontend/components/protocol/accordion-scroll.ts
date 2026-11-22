// Akkordeon im Protokoll, an die Scrollposition gekoppelt (Wunsch 19.11.2026: «beim Scrollen
// sollen die Punkte daneben schon grösser oder kleiner werden, damit es nicht immer diesen
// Sprung gibt»).
//
// Früher klappte ein Punkt schlagartig auf, sobald die Mittellinie ihn erreichte, der vorherige
// zu, und die Ansicht wurde danach nachgerückt. Jetzt hat jeder Punkt einen Öffnungsgrad 0..1,
// der sich stetig aus seinem Abstand zur Mittellinie ergibt:
//   - Der Punkt unter der Mittellinie ist ganz offen.
//   - Ein Punkt darunter öffnet sich, während seine Oberkante zur Mitte hochkommt (Inhalt rollt
//     von oben nach unten aus).
//   - Ein Punkt darüber schliesst sich, während seine Unterkante nach oben weggeht (sichtbar
//     bleibt sein Ende, angrenzend an den nächsten Punkt).
// Die Rechnung geht vom Punkt unter der Mittellinie aus und läuft von dort nach oben und unten.
// Da jeder Punkt, der die Mittellinie enthält, nach dieser Regel ganz offen ist, ist das
// Ergebnis unabhängig davon, welcher Punkt gerade als Bezug dient: kein Sprung beim Wechsel.
//
// Scrollraum: Zwei Abstandshalter (::before/::after von .protocol-document-spaced) nehmen genau
// die Höhe auf, die den Punkten darüber bzw. darunter gerade fehlt. Damit liegt jeder Punkt im
// Scrollraum immer dort, wo er bei ganz offenem Dokument läge: der Bezugspunkt bewegt sich beim
// Umbau nicht, Scrollbalken und Sprungziele bleiben fest, und es muss nie nachkorrigiert werden
// (kein Eingriff in laufendes Scrollen, kein Scroll-Anchoring nötig).

import { offsetTopWithin } from "@/components/protocol/document-scroll";

/** Scrollweg (px), über den ein Punkt auf- bzw. zuklappt. */
export const ACCORDION_RAMP = 260;

export type AccordionMetrics = {
  /** Höhe des eingeklappten Punkts (Kopf, Ränder) */
  collapsed: number;
  /** Natürliche Höhe des Inhalts unter dem Kopf */
  body: number;
};

const smooth = (x: number) => {
  const t = Math.max(0, Math.min(1, x));
  return t * t * (3 - 2 * t);
};

/** Öffnungsgrad je Punkt. `anchorTop` ist die Oberkante des Bezugspunkts relativ zum sichtbaren
 * Bereich, `center` die Mittellinie, `gap` der Abstand zwischen zwei Punkten. Der Bezugspunkt
 * selbst ist ganz offen. Reine Funktion (getestet in accordion-scroll.test.ts). */
export function accordionOpenness(
  sections: AccordionMetrics[],
  anchorIndex: number,
  anchorTop: number,
  { center, gap, ramp = ACCORDION_RAMP }: { center: number; gap: number; ramp?: number }
): number[] {
  const open = sections.map(() => 0);
  if (anchorIndex < 0 || anchorIndex >= sections.length) return open;
  open[anchorIndex] = 1;
  // Nach unten: Oberkante je Punkt aus der Lage seines Vorgängers
  let top = anchorTop + sections[anchorIndex].collapsed + sections[anchorIndex].body + gap;
  for (let index = anchorIndex + 1; index < sections.length; index += 1) {
    // Der Abstand zum Vorgänger zählt nicht: steht die Mitte in der Lücke, sind beide offen
    const value = smooth(1 - (top - gap - center) / ramp);
    open[index] = value;
    if (value === 0) break; // weiter unten liegt alles noch weiter weg
    top += sections[index].collapsed + value * sections[index].body + gap;
  }
  // Nach oben: Unterkante je Punkt aus der Lage seines Nachfolgers
  let bottom = anchorTop - gap;
  for (let index = anchorIndex - 1; index >= 0; index -= 1) {
    const value = smooth(1 - (center - bottom - gap) / ramp);
    open[index] = value;
    if (value === 0) break;
    bottom -= sections[index].collapsed + value * sections[index].body + gap;
  }
  return open;
}

type Item = {
  id: string;
  section: HTMLElement;
  body: HTMLElement;
  inner: HTMLElement;
  metrics: AccordionMetrics | null;
  open: number;
  above: boolean;
};

export type AccordionEngine = {
  /** Neu berechnen und anwenden (rAF-gedrosselt). */
  schedule: () => void;
  /** Lage eines Punkts im Scrollraum und seine Höhe, wenn er offen ist (für Sprungziele). */
  target: (id: string) => { top: number; height: number } | null;
  /** Sofort neu berechnen (nach einem Sprung). */
  settle: () => void;
  destroy: () => void;
};

export function createAccordionEngine(
  container: HTMLElement,
  { onActiveChange }: { onActiveChange: (id: string) => void }
): AccordionEngine {
  let items: Item[] = [];
  let gap = 0;
  let anchorIndex = 0;
  let activeId: string | null = null;
  let frame: number | null = null;

  function collect() {
    const previous = new Map(items.map((item) => [item.id, item]));
    const previousAnchor = items[anchorIndex]?.id;
    items = Array.from(container.querySelectorAll<HTMLElement>(":scope > .protocol-doc-section-wrap")).flatMap((wrap) => {
      const section = wrap.querySelector<HTMLElement>(":scope > .protocol-doc-section");
      const body = section?.querySelector<HTMLElement>(":scope > .protocol-doc-section-body");
      const inner = body?.firstElementChild as HTMLElement | null | undefined;
      if (!section || !body || !inner) return [];
      const id = section.id.replace("protocol-element-", "");
      const known = previous.get(id);
      return [{ id, section, body, inner, metrics: null, open: known?.open ?? -1, above: known?.above ?? false }];
    });
    anchorIndex = Math.max(0, items.findIndex((item) => item.id === previousAnchor));
    gap = parseFloat(getComputedStyle(container).rowGap) || 0;
  }

  function metricsOf(item: Item): AccordionMetrics {
    if (!item.metrics) {
      item.metrics = { collapsed: item.section.offsetHeight - item.body.offsetHeight, body: item.inner.offsetHeight };
    }
    return item.metrics;
  }

  const full = (item: Item) => metricsOf(item).collapsed + metricsOf(item).body;

  /** Lage aller Punkte im ganz offenen Dokument. Der zuletzt verwendete Bezugspunkt steht
   * bereits dort (siehe oben) - von ihm aus wird gerechnet. */
  function virtualTops(): number[] {
    const tops = items.map(() => 0);
    const reference = Math.min(anchorIndex, items.length - 1);
    tops[reference] = offsetTopWithin(items[reference].section, container);
    for (let index = reference + 1; index < items.length; index += 1) tops[index] = tops[index - 1] + full(items[index - 1]) + gap;
    for (let index = reference - 1; index >= 0; index -= 1) tops[index] = tops[index + 1] - gap - full(items[index]);
    return tops;
  }

  function apply(item: Item, open: number, above: boolean) {
    const value = open > 0.998 ? 1 : open < 0.002 ? 0 : open;
    if (Math.abs(value - item.open) < 0.002 && (value === 1 || value === 0 || above === item.above)) return;
    item.open = value;
    item.above = above;
    const body = metricsOf(item).body;
    item.section.style.setProperty("--open", value.toFixed(3));
    if (value === 1) {
      // Ganz offen: natürliche Höhe, Tippen lässt den Punkt frei wachsen
      item.body.style.height = "auto";
      item.inner.style.transform = "";
    } else {
      item.body.style.height = `${value * body}px`;
      // Punkte über dem Bezug zeigen ihr Ende (grenzt an den nächsten Punkt), darunter den Anfang
      item.inner.style.transform = above && value > 0 ? `translateY(${-(1 - value) * body}px)` : "";
    }
  }

  function run() {
    frame = null;
    if (!items.length) collect();
    if (!items.length) return;
    const scrollTop = container.scrollTop;
    const center = container.clientHeight / 2;
    const tops = virtualTops();
    // Bezug: der Punkt, in dessen Bereich (samt folgendem Abstand) die Mittellinie liegt
    const middle = scrollTop + center;
    let anchor = 0;
    for (let index = 0; index < items.length; index += 1) if (tops[index] <= middle) anchor = index;
    const metrics = items.map(metricsOf);
    const open = accordionOpenness(metrics, anchor, tops[anchor] - scrollTop, { center, gap });
    items.forEach((item, index) => apply(item, open[index], index < anchor));
    // Fehlende Höhe darüber/darunter in den Abstandshaltern: der Bezug bleibt, wo er ist
    let missingAbove = 0;
    let missingBelow = 0;
    items.forEach((item, index) => {
      const missing = (1 - item.open) * metrics[index].body;
      if (index < anchor) missingAbove += missing;
      else if (index > anchor) missingBelow += missing;
    });
    container.style.setProperty("--accordion-above", `${missingAbove}px`);
    container.style.setProperty("--accordion-below", `${missingBelow}px`);
    anchorIndex = anchor;
    if (activeId !== items[anchor].id) {
      activeId = items[anchor].id;
      onActiveChange(activeId);
    }
  }

  function schedule() {
    if (frame !== null) return;
    frame = window.requestAnimationFrame(run);
  }

  function relayout() {
    for (const item of items) item.metrics = null;
    schedule();
  }

  /** Nur die Punkte neu messen, deren Inhalt seine Höhe geändert hat (Tippen, Bilder, Daten) -
   * vorher verwarf jede Änderung die Masse aller Punkte (zwei offsetHeight-Lesungen je Punkt). */
  function remeasure(entries: ResizeObserverEntry[]) {
    let changed = false;
    for (const entry of entries) {
      const item = items.find((candidate) => candidate.inner === entry.target);
      if (!item) continue;
      item.metrics = null;
      changed = true;
    }
    if (changed) schedule();
  }

  const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(remeasure);
  function observe() {
    resizeObserver?.disconnect();
    collect();
    for (const item of items) resizeObserver?.observe(item.inner);
  }
  observe();
  // Punkte kommen hinzu oder fallen weg (Filter, Neuladen)
  const mutationObserver = typeof MutationObserver === "undefined" ? null : new MutationObserver(() => {
    observe();
    schedule();
  });
  mutationObserver?.observe(container, { childList: true });

  container.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", relayout);
  run();

  return {
    schedule,
    target(id) {
      const index = items.findIndex((entry) => entry.id === id);
      if (index < 0) return null;
      return { top: virtualTops()[index], height: full(items[index]) };
    },
    settle() {
      if (frame !== null) window.cancelAnimationFrame(frame);
      run();
    },
    destroy() {
      if (frame !== null) window.cancelAnimationFrame(frame);
      container.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", relayout);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      container.style.removeProperty("--accordion-above");
      container.style.removeProperty("--accordion-below");
    },
  };
}
