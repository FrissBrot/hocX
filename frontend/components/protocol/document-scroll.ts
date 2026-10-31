// Scrollverhalten des Protokoll-Dokuments (Design «Protokoll-Editor v2»): Rad-Effekt, Ziel-
// berechnung für Sprünge und eine eigene Easing-Kurve. Alle Masse im Scrollraum von
// .protocol-document (offsetTop/scrollTop, also ungezoomt und unabhängig von den Transforms
// des Rad-Effekts - getBoundingClientRect würde die gekippten Abschnitte verzerrt messen).

/** Abstand zum Rand des Dokuments beim Verankern eines Abschnitts. */
export const SCROLL_INSET = 16;
/** Der aktive Abschnitt bleibt, bis die Mittellinie so weit über seine Kante hinaus ist. */
export const SPY_HYSTERESIS = 32;
/** Nach dem Betreten eines Abschnitts nach unten den Rest-Schwung des Mausrads so lange abfangen. */
export const WHEEL_HOLD_MS = 520;

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

export type WheelStyle = { transform: string; transformOrigin: string; opacity: string; filter: string };

const NO_WHEEL: WheelStyle = { transform: "", transformOrigin: "", opacity: "", filter: "" };

/** Rad-Effekt eines Abschnitts: je weiter von der Mittellinie entfernt, desto stärker kippt er
 * nach hinten weg, wird kleiner und blasser. Nur transform/opacity - kein Layout, die
 * Scrollposition bleibt exakt, und beides rechnet der Compositor ohne Neuzeichnen. Bewusst
 * kein filter (blur/grayscale): der zeichnet grosse Abschnitte auf breiten Bildschirmen in
 * jedem Frame neu und liess das Scrollen ruckeln. */
export function wheelStyle(
  { top, height, scrollTop, viewport }: { top: number; height: number; scrollTop: number; viewport: number }
): WheelStyle {
  const centerY = scrollTop + viewport / 2;
  const reach = viewport * 0.6;
  if (reach <= 0) return NO_WHEEL;
  const bottom = top + height;
  let distance = 0;
  let below = false;
  if (top > centerY) {
    distance = (top - centerY) / reach;
    below = true;
  } else if (bottom < centerY) {
    distance = (centerY - bottom) / reach;
  }
  const d = Math.min(1, distance);
  const e = d * d * (3 - 2 * d);
  if (e <= 0.001) return NO_WHEEL;
  return {
    transformOrigin: below ? "50% 0%" : "50% 100%",
    transform: `perspective(1400px) rotateX(${((below ? -1 : 1) * e * 24).toFixed(2)}deg) scale(${(1 - 0.12 * e).toFixed(4)})`,
    opacity: (1 - 0.6 * e).toFixed(3),
    filter: "",
  };
}

// Zuletzt geschriebener Stil je Abschnitt: unveränderte (z. B. weit entfernte, voll gekippte)
// Abschnitte werden nicht in jedem Frame neu gesetzt.
const appliedWheel = new WeakMap<HTMLElement, string>();

/** Rad-Effekt auf alle Abschnitte anwenden (enabled=false entfernt ihn wieder). Erst alle
 * Positionen lesen, dann schreiben - sonst erzwingt jeder Abschnitt eine eigene Neuberechnung. */
export function applyWheelFrame(container: HTMLElement, enabled: boolean) {
  const sections = Array.from(container.querySelectorAll<HTMLElement>(".protocol-doc-section"));
  const scrollTop = container.scrollTop;
  const viewport = container.clientHeight;
  // Der aktive Punkt bleibt immer flach: transform/filter machen ein Element zum Bezugsrahmen
  // für position:fixed, Menüs und Auswahllisten darin stünden sonst verschoben.
  const styles = sections.map((section) =>
    enabled && !section.classList.contains("protocol-doc-section-active")
      ? wheelStyle({ top: offsetTopWithin(section, container), height: section.offsetHeight, scrollTop, viewport })
      : NO_WHEEL
  );
  sections.forEach((section, index) => {
    const style = styles[index];
    const key = `${style.transform}|${style.opacity}`;
    if (appliedWheel.get(section) === key) return;
    appliedWheel.set(section, key);
    section.style.transformOrigin = style.transformOrigin;
    section.style.transform = style.transform;
    section.style.opacity = style.opacity;
    section.style.filter = style.filter;
  });
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

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Akkordeon: neu geöffneten Punkt kurz einblenden (nur transform/opacity, die Verankerung
 * bleibt exakt). Von oben kommend gleitet der Inhalt nach unten, von unten nach oben. */
export function revealSection(section: HTMLElement, fromBelow: boolean) {
  if (prefersReducedMotion()) return;
  const body = section.querySelector<HTMLElement>(":scope > .element-block-stack");
  body?.animate?.(
    [{ opacity: 0, transform: `translateY(${fromBelow ? "-6px" : "6px"})` }, { opacity: 1, transform: "none" }],
    { duration: 260, easing: "cubic-bezier(.2,.7,.2,1)" }
  );
  const heading = section.querySelector<HTMLElement>(":scope > .editor-panel-header h2");
  heading?.animate?.(
    [{ transform: "scale(.94)", transformOrigin: "left center" }, { transform: "none", transformOrigin: "left center" }],
    { duration: 220, easing: "cubic-bezier(.2,.7,.2,1)" }
  );
}
