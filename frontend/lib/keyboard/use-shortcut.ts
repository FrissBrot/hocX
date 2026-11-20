"use client";

/**
 * Ein einziger Dispatcher für alle Shortcuts aus `registry.ts`.
 *
 * Reihenfolge, wenn mehrere Bindungen auf dieselbe Taste passen (genau eine wird ausgeführt):
 *   1. oberstes Overlay: Escape, Tab-Falle und Tasten des Dialogs/Popovers selbst (usePopupEscape,
 *      Modal, Popover, Widgets) laufen vorher und setzen `defaultPrevented` - dann passiert hier nichts;
 *   2. fokussierte Komponente: Bindungen mit `scopeRef`, die das Ereignisziel enthalten;
 *   3. Seite/Feature (`scope: "page"`);
 *   4. global.
 * Innerhalb einer Stufe gewinnt die zuletzt registrierte Bindung. Ein Handler kann `false`
 * zurückgeben («nicht zuständig»), dann ist die nächste Bindung dran bzw. der Browser.
 *
 * Schutzregeln (für alle Bindungen gleich):
 *   - Beim Tippen (Textfeld, Select, Editor, contenteditable) nur Shortcuts mit `inInputs: true`.
 *   - Tasten ohne Strg/⌘/Alt in einem zusammengesetzten Widget (Liste, Menü, Tabs, Kalender, Slider
 *     …) gehören dem Widget.
 *   - Ist ein Overlay offen, wirken nur Bindungen innerhalb dieses Overlays oder solche mit
 *     `whenOverlayOpen: true`.
 *   - IME-Komposition (`isComposing`) und bereits behandelte Ereignisse werden nie angefasst.
 */

import { RefObject, useEffect, useRef, useSyncExternalStore } from "react";

import { getShortcut, matchesCombo, parseCombo, ShortcutDefinition, ShortcutId } from "./registry";

export type ShortcutHandler = (event: KeyboardEvent) => boolean | void;

type Registration = {
  id: ShortcutId;
  definition: ShortcutDefinition;
  handler: { current: ShortcutHandler };
  scopeRef?: RefObject<HTMLElement | null>;
  preventDefault: boolean;
  order: number;
};

const registrations: Registration[] = [];
const subscribers = new Set<() => void>();
let counter = 0;
let snapshot: readonly ShortcutId[] = [];

function publish() {
  snapshot = Array.from(new Set(registrations.map((registration) => registration.id)));
  subscribers.forEach((notify) => notify());
}

const TEXT_INPUT_EXCLUDED = new Set(["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image", "hidden"]);
const WIDGET_ROLES = "listbox, menu, menubar, grid, tree, treegrid, tablist, radiogroup, slider, spinbutton, toolbar"
  .split(", ")
  .map((role) => `[role="${role}"]`)
  .join(",");

/** Fokus in einem Feld, in dem getippt wird (Text, Auswahl, Editor). */
export function isTextEntryTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element || !element.tagName) return false;
  // isContentEditable gilt auch für Kinder eines Editors; closest() als Rückfall (jsdom kennt es nicht)
  if (element.isContentEditable || element.closest?.('[contenteditable]:not([contenteditable="false"])')) return true;
  if (element.tagName === "TEXTAREA" || element.tagName === "SELECT") return true;
  if (element.tagName === "INPUT") return !TEXT_INPUT_EXCLUDED.has((element as HTMLInputElement).type);
  const role = element.getAttribute("role");
  return role === "textbox" || role === "combobox" || role === "searchbox" || role === "spinbutton";
}

/** Fokus in einem zusammengesetzten Widget, das Pfeile/Buchstaben selbst nutzt. */
export function isInsideCompositeWidget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element || !element.closest) return false;
  return Boolean(element.closest(WIDGET_ROLES) || element.hasAttribute("aria-activedescendant"));
}

/** Oberstes offenes Overlay (Dialog, Rückfrage, Popover/Menü), sonst null. */
export function topOverlay(doc: Document = document): HTMLElement | null {
  const overlays = Array.from(doc.querySelectorAll<HTMLElement>('[aria-modal="true"], .popover-panel'));
  return overlays.length ? overlays[overlays.length - 1] : null;
}

const SCOPE_RANK: Record<string, number> = { component: 0, page: 1, global: 2 };

export function dispatchShortcut(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.isComposing) return false;
  const target = event.target as Node | null;
  const candidates = registrations.filter((registration) => registration.definition.keys.some((combo) => matchesCombo(event, combo)));
  if (!candidates.length) return false;

  const typing = isTextEntryTarget(event.target);
  const plain = !(event.ctrlKey || event.metaKey || event.altKey);
  const inWidget = plain && isInsideCompositeWidget(event.target);
  const overlay = topOverlay();

  const eligible = candidates.filter((registration) => {
    const { definition } = registration;
    if (typing && !definition.inInputs) return false;
    if (inWidget) return false;
    const scopeElement = registration.scopeRef?.current ?? null;
    if (registration.scopeRef && !scopeElement) return false;
    if (overlay && !definition.whenOverlayOpen && !(scopeElement && overlay.contains(scopeElement))) return false;
    return true;
  });

  const rank = (registration: Registration) => {
    const scopeElement = registration.scopeRef?.current;
    if (scopeElement && target && scopeElement.contains(target)) return -1;
    return SCOPE_RANK[registration.definition.scope];
  };
  eligible.sort((left, right) => rank(left) - rank(right) || right.order - left.order);

  for (const registration of eligible) {
    if (registration.handler.current(event) === false) continue;
    if (registration.preventDefault) event.preventDefault();
    return true;
  }
  return false;
}

let listening = false;
function ensureListener() {
  if (listening || typeof window === "undefined") return;
  window.addEventListener("keydown", dispatchShortcut);
  listening = true;
}

export type UseShortcutOptions = {
  enabled?: boolean;
  /** Bindung gilt nur, solange dieses Element im Dokument ist, und hat Vorrang, wenn der Fokus darin liegt. */
  scopeRef?: RefObject<HTMLElement | null>;
  /** Standard true: das Ereignis gilt nach dem Handler als behandelt (kein Browser-Standard). */
  preventDefault?: boolean;
};

/** Bindet eine Aktion an einen Shortcut aus der Registry. */
export function useShortcut(id: ShortcutId, handler: ShortcutHandler, options: UseShortcutOptions = {}): void {
  const { enabled = true, scopeRef, preventDefault = true } = options;
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  });
  useEffect(() => {
    if (!enabled) return;
    const definition = getShortcut(id);
    if (definition.kind === "standard") throw new Error(`Shortcut ${id} ist nur Dokumentation`); // i18n-ok: Entwicklerfehler
    ensureListener();
    const registration: Registration = { id, definition, handler: handlerRef, scopeRef, preventDefault, order: ++counter };
    registrations.push(registration);
    publish();
    return () => {
      registrations.splice(registrations.indexOf(registration), 1);
      publish();
    };
  }, [id, enabled, scopeRef, preventDefault]);
}

/** IDs aller gerade gebundenen Shortcuts (für die Shortcut-Hilfe). */
export function useActiveShortcutIds(): readonly ShortcutId[] {
  return useSyncExternalStore(
    (notify) => {
      subscribers.add(notify);
      return () => subscribers.delete(notify);
    },
    () => snapshot,
    () => snapshot
  );
}

/** Nur für Tests: alle Bindungen entfernen. */
export function resetShortcutRegistrationsForTests() {
  registrations.splice(0, registrations.length);
  publish();
}

export { parseCombo };
