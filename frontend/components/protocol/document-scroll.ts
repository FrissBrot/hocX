// Scrollverhalten des Protokoll-Dokuments (Design «Protokoll-Editor 1a»): Zielberechnung und
// zweistufiger Sprung zu einem Punkt, sanftes Scrollen. Alle Masse im Scrollraum von
// .protocol-doc (offsetTop/scrollTop).

/** Abstand zum Rand des Dokuments beim Verankern eines Abschnitts. */
export const SCROLL_INSET = 16;
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

/** scrollTop, mit dem ein Abschnitt angesprungen wird: Kopf des Punkts oben im Dokument (wie ein
 * Kapitelsprung in Docs/Word), im Scrollbereich begrenzt. */
export function sectionScrollTarget({ top, viewport, scrollHeight }: { top: number; viewport: number; scrollHeight: number }): number {
  return Math.max(0, Math.min(top - SCROLL_INSET, scrollHeight - viewport));
}

/** Ab so vielen Bildschirmhöhen Abstand springt jumpToSection zuerst sofort in die Nähe. */
export const FAR_JUMP_VIEWPORTS = 2;

/**
 * Sprung zu einem Punkt in zwei Stufen. Punkte ausserhalb des Bildes werden mit
 * content-visibility: auto nicht gerendert und haben nur ihre geschätzte bzw. zuletzt gemessene
 * Höhe (contain-intrinsic-size: auto). Ein weiter Sprung würde deshalb neben dem Ziel landen:
 * Stufe 1 springt sofort knapp vor das Ziel (der Browser rendert dort die echten Höhen), Stufe 2
 * misst im nächsten Frame neu und fährt das letzte Stück (sanft, wenn erlaubt). Gibt eine
 * Abbruchfunktion zurück; onDone läuft genau einmal.
 */
export function jumpToSection(
  container: HTMLElement,
  section: HTMLElement,
  { smooth, onDone }: { smooth: boolean; onDone: () => void }
): () => void {
  let cancelled = false;
  let cancelScroll: (() => void) | null = null;
  let frame: number | null = null;
  const target = () =>
    sectionScrollTarget({ top: offsetTopWithin(section, container), viewport: container.clientHeight, scrollHeight: container.scrollHeight });
  const finish = () => {
    if (cancelled) return;
    const exact = target();
    if (!smooth || Math.abs(exact - container.scrollTop) < 1) {
      container.scrollTop = exact;
      onDone();
      return;
    }
    cancelScroll = supportsNativeSmoothScroll()
      ? nativeSmoothScroll(container, exact, { onDone })
      : animateScroll(container, exact, { onDone });
  };
  const first = target();
  const far = Math.abs(first - container.scrollTop) > container.clientHeight * FAR_JUMP_VIEWPORTS;
  if (far) {
    // Knapp vor dem Ziel landen, damit die letzte Strecke sichtbar bleibt
    container.scrollTop = Math.max(0, first - (smooth ? container.clientHeight / 2 : 0));
    frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => {
        frame = null;
        finish();
      });
    });
  } else {
    finish();
  }
  return () => {
    if (cancelled) return;
    cancelled = true;
    if (frame !== null) window.cancelAnimationFrame(frame);
    if (cancelScroll) cancelScroll();
    else onDone();
  };
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
 * Sprung voraus (Stufe 1 von jumpToSection), kommt dessen scrollend erst danach an und beendete
 * sonst die Pause des Scroll-Spys zu früh. */
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
