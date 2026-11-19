// Scrollverhalten des Protokoll-Dokuments (Design «Protokoll-Editor v2»): Rad-Effekt im
// Akkordeon, Zielberechnung für Sprünge und sanftes Scrollen. Alle Masse im Scrollraum von
// .protocol-document (offsetTop/scrollTop, also ungezoomt und unabhängig von den Transforms
// des Rad-Effekts - getBoundingClientRect würde die gekippten Abschnitte verzerrt messen).

/** Abstand zum Rand des Dokuments beim Verankern eines Abschnitts. */
export const SCROLL_INSET = 16;
/** Der aktive Abschnitt bleibt, bis die Mittellinie so weit über seine Kante hinaus ist. */
export const SPY_HYSTERESIS = 32;
// Abweichung in px, ab der ein scrollend als «am Ziel» gilt (Rundung, Zoom).
export const SCROLL_END_TOLERANCE = 2;

/** Oberkante eines Elements im Scrollinhalt des Containers. */
export function offsetTopWithin(el: HTMLElement, container: HTMLElement): number {
  let top = 0;
  let node: HTMLElement | null = el;
  while (node && node !== container) {
    top += node.offsetTop;
    node = node.offsetParent as HTMLElement | null;
  }
  if (node === container) return top;
  // Container ist nicht positioniert: beide Ketten laufen bis zum Dokument, die Differenz zählt
  let containerTop = 0;
  for (let n: HTMLElement | null = container; n; n = n.offsetParent as HTMLElement | null) containerTop += n.offsetTop;
  return top - containerTop - container.clientTop;
}

/** scrollTop, mit dem ein Abschnitt angesprungen wird: lange Abschnitte und der erste Punkt
 * oben, alle anderen mittig. */
export function sectionScrollTarget(
  { top, height, viewport, scrollHeight, first }: { top: number; height: number; viewport: number; scrollHeight: number; first: boolean }
): number {
  const tall = height >= viewport - SCROLL_INSET * 2;
  const want = tall || first ? top - SCROLL_INSET : top - (viewport - height) / 2;
  return Math.max(0, Math.min(want, scrollHeight - viewport));
}

/** Weiter als so viele Punkte vom aktiven entfernt bleibt ein Punkt flach (keine eigene Ebene).
 * Eingeklappte Punkte sind rund 90 px hoch: so weit weg liegen sie ausserhalb des Bildes. */
export const WHEEL_RANGE = 10;

export type WheelVars = { "--wheel-dir": string; "--wheel-depth": string };

/** Rad-Effekt im Akkordeon: Lage eines (eingeklappten) Punkts auf der Walze, abhängig nur vom
 * Abstand zum aktiven Punkt in Punkten (offset < 0: darüber). Die Werte gehen als CSS-Variablen
 * an den Abschnitt; Neigung, Grösse und Deckkraft rechnet protocol.css daraus, eine
 * CSS-Transition dreht beim Wechsel auf dem Compositor - kein JavaScript pro Scroll-Frame.
 * null: aktiver Punkt oder zu weit weg (flach, ohne Transform). */
export function wheelVars(offset: number): WheelVars | null {
  if (!Number.isFinite(offset) || offset === 0 || Math.abs(offset) > WHEEL_RANGE) return null;
  const d = Math.min(1, Math.abs(offset) / 4);
  const depth = d * d * (3 - 2 * d);
  return { "--wheel-dir": offset < 0 ? "-1" : "1", "--wheel-depth": depth.toFixed(3) };
}

export type SectionLayout = { section: HTMLElement; top: number; height: number };

/** Positionen aller Abschnitte im Scrollraum. Unabhängig von den Transforms des Rad-Effekts,
 * ändert sich also nur bei Grössen- oder Inhaltsänderungen - Aufrufer können das Ergebnis
 * zwischenspeichern, statt es in jedem Scroll-Frame neu zu lesen. */
export function measureSections(container: HTMLElement): SectionLayout[] {
  return Array.from(container.querySelectorAll<HTMLElement>(".protocol-doc-section")).map((section) => ({
    section,
    top: offsetTopWithin(section, container),
    height: section.offsetHeight,
  }));
}

const easeOutQuart = (t: number) => 1 - Math.pow(1 - t, 4);

/** Dauer eines Sprungs: skaliert mit der Distanz, höchstens 620 ms. */
export function scrollDuration(distance: number): number {
  return Math.min(620, 260 + Math.abs(distance) * 0.25);
}

/** Sanft scrollen mit eigener Kurve (sanftes Abbremsen). Mausrad (optional) oder Touch brechen
 * ab. Gibt eine Abbruchfunktion zurück; onDone läuft immer genau einmal. */
export function animateScroll(
  container: HTMLElement,
  target: number,
  { duration, cancelOnWheel = true, onDone }: { duration?: number; cancelOnWheel?: boolean; onDone: () => void }
): () => void {
  const from = container.scrollTop;
  const distance = target - from;
  const total = duration ?? scrollDuration(distance);
  const start = performance.now();
  let frame: number | null = null;
  let finished = false;
  const stop = () => {
    if (finished) return;
    finished = true;
    if (frame !== null) window.cancelAnimationFrame(frame);
    container.removeEventListener("wheel", stop);
    container.removeEventListener("touchstart", stop);
    onDone();
  };
  if (cancelOnWheel) container.addEventListener("wheel", stop, { passive: true });
  container.addEventListener("touchstart", stop, { passive: true });
  const step = (now: number) => {
    const progress = Math.min(1, (now - start) / total);
    container.scrollTop = from + distance * easeOutQuart(progress);
    if (progress < 1) frame = window.requestAnimationFrame(step);
    else stop();
  };
  frame = window.requestAnimationFrame(step);
  return stop;
}

/** Der Browser kann sanft scrollen und meldet das Ende (scrollend). Dann scrollt er auch selbst,
 * auf dem Compositor-Thread - flüssig, selbst wenn der Hauptthread gerade beschäftigt ist. */
export function supportsNativeSmoothScroll(): boolean {
  return typeof window !== "undefined" && "onscrollend" in window;
}

/** Sanft scrollen über den Browser (scrollTo smooth). onDone läuft genau einmal: bei scrollend am
 * Ziel, nach dem Sicherheits-Timeout oder beim Abbruch (der Rückgabewert hält an der aktuellen
 * Stelle an).
 *
 * Ein scrollend zählt nur, wenn das Ziel erreicht ist: Geht dem sanften Scrollen ein sofortiger
 * Sprung voraus (Verankerung im Akkordeon), kommt dessen scrollend erst danach an. Es beendete
 * sonst sofort die Pause des Scroll-Spys, bevor der neue Punkt in Position war; der Spy sah die
 * Bildmitte noch über dem Punkt und wählte den vorherigen zurück (Rad-Effekt: man kam beim
 * Mausrad nicht mehr zum nächsten Punkt, Bug 2026-11-11). */
export function nativeSmoothScroll(container: HTMLElement, target: number, { onDone }: { onDone: () => void }): () => void {
  let finished = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const reachable = () => Math.max(0, Math.min(target, container.scrollHeight - container.clientHeight));
  const finish = () => {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    container.removeEventListener("scrollend", onScrollEnd);
    onDone();
  };
  const onScrollEnd = () => {
    if (Math.abs(container.scrollTop - reachable()) <= SCROLL_END_TOLERANCE) finish();
  };
  container.addEventListener("scrollend", onScrollEnd);
  // Ohne Bewegung (schon am Ziel, Rand des Scrollbereichs) kommt kein scrollend
  timer = setTimeout(finish, 1200);
  container.scrollTo({ top: target, behavior: "smooth" });
  return () => {
    if (finished) return;
    // Laufende Browser-Animation an der aktuellen Stelle anhalten
    container.scrollTo({ top: container.scrollTop, behavior: "instant" });
    finish();
  };
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
