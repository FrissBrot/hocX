"use client";

import { RefObject, useEffect } from "react";

import { focusIsLost, restoreFocus, stableFocusTarget, wrapTab } from "./focus";

/**
 * Fokusfalle für modale Dialoge (Modal, Rückfrage). Ergänzt das onKeyDown im Dialog um zwei
 * Fälle, die React-Ereignisse nicht sehen:
 *   - Fokus ist ausserhalb (z. B. auf <body>, weil das fokussierte Element gelöscht wurde) und
 *     jemand drückt Tab → der Fokus springt in den Dialog statt auf die Seite dahinter;
 *   - Fokus landet per Klick/Skript auf der Seite hinter dem Dialog → zurück in den Dialog.
 * Nur der oberste Dialog reagiert. Später geöffnete Ebenen (Popover/Menüs eines Feldes im
 * Dialog, Rückfragen) liegen als Portal hinter dem Dialog im DOM und zählen als «innen».
 */
const stack: Array<RefObject<HTMLElement | null>> = [];

const LAYERS = '[aria-modal="true"], .popover-panel, [data-overlay-layer]';

function belongsToLaterLayer(root: HTMLElement, node: Node): boolean {
  const element = node instanceof Element ? node : node.parentElement;
  const layer = element?.closest(LAYERS);
  if (!layer || root.contains(layer)) return false;
  return Boolean(root.compareDocumentPosition(layer) & Node.DOCUMENT_POSITION_FOLLOWING);
}

export function isInsideTopDialog(node: Node | null): boolean {
  const root = stack[stack.length - 1]?.current;
  if (!root || !node) return true;
  return root.contains(node) || belongsToLaterLayer(root, node);
}

export function useFocusTrap(active: boolean, containerRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!active) return;
    stack.push(containerRef);
    const isTop = () => stack[stack.length - 1] === containerRef;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab" || event.defaultPrevented || !isTop()) return;
      const container = containerRef.current;
      if (!container) return;
      const active = document.activeElement;
      // Im Dialog selbst übernimmt wrapTab nur die Ränder; in späteren Ebenen (Popover) nichts tun
      if (active && active !== document.body && belongsToLaterLayer(container, active)) return;
      wrapTab(event, container);
    }

    function onFocusIn(event: FocusEvent) {
      if (!isTop()) return;
      const container = containerRef.current;
      const target = event.target as Node | null;
      if (!container || !target || container.contains(target) || belongsToLaterLayer(container, target)) return;
      // Fokus ist auf die Seite hinter dem Dialog gewandert: zurückholen
      const fallback = container.querySelector<HTMLElement>('[role="dialog"], [role="alertdialog"]') ?? container;
      if (fallback.hasAttribute("tabindex") || fallback.tabIndex >= 0) fallback.focus({ preventScroll: true });
    }

    // Bubble-Phase am document: läuft nach den React-Handlern (Widgets mit eigener Tab-Logik
    // setzen defaultPrevented und haben Vorrang) und sieht auch Ereignisse mit Ziel <body>.
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocusIn);
      stack.splice(stack.indexOf(containerRef), 1);
    };
  }, [active, containerRef]);
}

/**
 * Komplettpaket für eigene Vollbild-Dialoge, die nicht `Modal` nutzen können (Foto-Viewer,
 * Lightbox): Auslöser merken, Fokus beim Öffnen auf den Dialog (Container braucht tabIndex={-1}),
 * Tab-Falle und Fokus-Rückgabe beim Schliessen. Neue Dialoge nehmen `Modal`.
 */
export function useModalFocus(active: boolean, containerRef: RefObject<HTMLElement | null>) {
  useFocusTrap(active, containerRef);
  useEffect(() => {
    if (!active) return;
    const opener = stableFocusTarget(document.activeElement);
    const container = containerRef.current;
    if (container && !container.contains(document.activeElement)) container.focus({ preventScroll: true });
    return () => {
      if (focusIsLost(container)) restoreFocus(opener);
    };
  }, [active, containerRef]);
}
