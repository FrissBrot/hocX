/**
 * Gemeinsame Fokus-Hilfen für Dialoge, Popover und zusammengesetzte Widgets
 * (design/KEYBOARD_ACCESSIBILITY.md, Abschnitt «Fokusmanagement»).
 *
 * Grundsatz: native Mittel zuerst (echte Buttons/Links, autoFocus, Tab-Reihenfolge aus dem DOM).
 * Diese Hilfen greifen nur dort ein, wo ein Overlay als Portal am Ende von <body> liegt oder ein
 * fokussiertes Element verschwindet.
 */

/** Kandidaten für die Tab-Reihenfolge; `getTabbables` filtert danach Unsichtbares/Deaktiviertes. */
export const TABBABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button",
  "input:not([type=\"hidden\"])",
  "select",
  "textarea",
  "iframe",
  "summary",
  "audio[controls]",
  "video[controls]",
  "[contenteditable]:not([contenteditable=\"false\"])",
  "[tabindex]",
].join(",");

/** Inhalt der Hauptspalte (Sprunglink-Ziel, Fallback, wenn das zuletzt fokussierte Element weg ist). */
export const MAIN_CONTENT_ID = "main-content";

function isDisabled(element: HTMLElement): boolean {
  if ("disabled" in element && (element as HTMLButtonElement).disabled) return true;
  // Felder in einem deaktivierten <fieldset> (ausser in dessen erster <legend>)
  const fieldset = element.closest("fieldset");
  return Boolean(fieldset?.disabled && !fieldset.querySelector("legend")?.contains(element));
}

function isHidden(element: HTMLElement): boolean {
  if (element.closest("[hidden], [inert]")) return true;
  // jsdom kennt kein Layout: dort zählt nur display/visibility aus dem Inline-/Computed-Style.
  const style = typeof window !== "undefined" ? window.getComputedStyle(element) : null;
  if (style && (style.visibility === "hidden" || style.display === "none")) return true;
  const layoutKnown = typeof navigator !== "undefined" && !/jsdom/i.test(navigator.userAgent);
  return layoutKnown && element.getClientRects().length === 0;
}

/** true, wenn das Element per Tab erreichbar ist (sichtbar, aktiv, kein tabindex="-1"). */
export function isTabbable(element: Element): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  if (!element.matches(TABBABLE_SELECTOR)) return false;
  const tabIndex = element.getAttribute("tabindex");
  if (tabIndex !== null && Number(tabIndex) < 0) return false;
  if (isDisabled(element)) return false;
  if (element instanceof HTMLInputElement && element.type === "radio" && !element.checked && element.name) {
    // Radiogruppe: nur die gewählte (oder ohne Wahl die erste) Option ist ein Tab-Halt
    const group = Array.from(element.form?.elements ?? element.ownerDocument.querySelectorAll("input[type=radio]")).filter(
      (other): other is HTMLInputElement => other instanceof HTMLInputElement && other.type === "radio" && other.name === element.name
    );
    if (group.some((other) => other.checked) || group[0] !== element) return false;
  }
  return !isHidden(element);
}

/** Alle Tab-Halte in `root` in Dokumentreihenfolge (positive tabindex gibt es in hocX nicht). */
export function getTabbables(root: ParentNode | null | undefined): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)).filter(isTabbable);
}

/** Fokussierbar per Skript (auch tabindex="-1"), sichtbar und aktiv. */
export function isFocusable(element: Element | null | undefined): element is HTMLElement {
  if (!(element instanceof HTMLElement) || !element.isConnected) return false;
  if (!element.matches(TABBABLE_SELECTOR) || isDisabled(element)) return false;
  return !isHidden(element);
}

/**
 * Fokus in einen Container legen: zuerst ein Element mit `data-autofocus`, dann das erste
 * Tab-Ziel, sonst der Container selbst (braucht tabIndex={-1}).
 */
export function focusFirst(root: HTMLElement | null | undefined, options: { preferContainer?: boolean } = {}): boolean {
  if (!root) return false;
  const preferred = root.querySelector<HTMLElement>("[data-autofocus]");
  const target = preferred && isFocusable(preferred) ? preferred : options.preferContainer ? root : getTabbables(root)[0] ?? root;
  if (!target || (target === root && !root.hasAttribute("tabindex"))) return false;
  target.focus({ preventScroll: true });
  return document.activeElement === target;
}

/** Erstes fokussierbares Element in/an `anchor` (Trigger eines Popovers, der selbst ein Wrapper sein kann). */
export function focusTargetIn(anchor: HTMLElement | null | undefined): HTMLElement | null {
  if (!anchor) return null;
  if (isFocusable(anchor)) return anchor;
  return getTabbables(anchor)[0] ?? null;
}

/**
 * Fokus zurückgeben (nach Dialog/Popover/Löschen). Ist das Ziel nicht mehr im Dokument oder nicht
 * fokussierbar, gehen die Fallbacks der Reihe nach durch, zuletzt der Hauptinhalt (#main-content),
 * damit der Fokus nie unbemerkt auf <body> landet.
 */
export function restoreFocus(target: HTMLElement | null | undefined, ...fallbacks: Array<HTMLElement | null | undefined>): HTMLElement | null {
  const main = typeof document !== "undefined" ? document.getElementById(MAIN_CONTENT_ID) : null;
  for (const candidate of [target, ...fallbacks, main]) {
    if (candidate && candidate.isConnected && (isFocusable(candidate) || candidate === main)) {
      candidate.focus({ preventScroll: candidate === main });
      if (document.activeElement === candidate) return candidate;
    }
  }
  return null;
}

/**
 * true, wenn der Fokus nirgends ist (body/null), etwa weil das fokussierte Element entfernt wurde,
 * oder nur auf dem Hauptinhalt als Auffangziel liegt. `within`: zusätzlich true, wenn der Fokus
 * noch in diesem (gleich verschwindenden) Container steht.
 */
export function focusIsLost(within?: Element | null): boolean {
  if (typeof document === "undefined") return false;
  const active = document.activeElement;
  if (!active || active === document.body || active === document.documentElement || !active.isConnected) return true;
  if (active.id === MAIN_CONTENT_ID) return true;
  return Boolean(within && within.contains(active));
}

/**
 * Tab an den Rändern eines Containers umlenken (Fokusfalle eines modalen Dialogs). Gibt true
 * zurück, wenn das Ereignis behandelt wurde.
 */
export function wrapTab(event: KeyboardEvent | { key: string; shiftKey: boolean; preventDefault: () => void }, root: HTMLElement): boolean {
  if (event.key !== "Tab") return false;
  const tabbables = getTabbables(root);
  if (tabbables.length === 0) {
    event.preventDefault();
    root.focus({ preventScroll: true });
    return true;
  }
  const first = tabbables[0];
  const last = tabbables[tabbables.length - 1];
  const active = document.activeElement as HTMLElement | null;
  const inside = Boolean(active && root.contains(active));
  const position = active ? tabbables.indexOf(active) : -1;
  if (event.shiftKey && (!inside || active === root || active === first || position === -1 && active === root)) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && (!inside || active === last)) {
    event.preventDefault();
    first.focus();
    return true;
  }
  if (inside && position === -1) {
    // Fokus auf einem nicht tabbaren Element im Dialog (z. B. tabindex=-1): nächstes Ziel selbst wählen
    const following = tabbables.find((element) => active!.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING);
    const preceding = [...tabbables].reverse().find((element) => active!.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_PRECEDING);
    event.preventDefault();
    (event.shiftKey ? preceding ?? last : following ?? first).focus();
    return true;
  }
  return false;
}

// ── Rückgabeziel von Popovern ─────────────────────────────────────────────
// Ein Menüeintrag, der einen Dialog öffnet, verschwindet mit dem Menü. Der Dialog merkt sich
// deshalb nicht den Eintrag, sondern den Auslöser des Menüs als Rückgabeziel.
const returnTargets = new WeakMap<Element, () => HTMLElement | null>();

export function registerReturnTarget(panel: Element, getTarget: () => HTMLElement | null): () => void {
  returnTargets.set(panel, getTarget);
  return () => {
    returnTargets.delete(panel);
  };
}

/** Stabiles Rückgabeziel für `element`: liegt es in einem Popover, dessen Auslöser. */
export function stableFocusTarget(element: Element | null): HTMLElement | null {
  if (!(element instanceof HTMLElement)) return null;
  for (let node: Element | null = element; node; node = node.parentElement) {
    const getter = returnTargets.get(node);
    if (getter) return getter() ?? element;
  }
  return element;
}
