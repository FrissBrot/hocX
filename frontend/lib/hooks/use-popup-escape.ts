"use client";

import { RefObject, useLayoutEffect, useRef } from "react";

type Popup = { element: () => HTMLElement | null; close: () => void | Promise<void>; busy: boolean };
const popups: Popup[] = [];

function layer(element: HTMLElement | null) {
  let value = 0;
  for (let node = element; node; node = node.parentElement) {
    value = Math.max(value, Number.parseInt(getComputedStyle(node).zIndex, 10) || 0);
  }
  return value;
}

function topPopup() {
  return [...popups].sort((a, b) => {
    const left = a.element();
    const right = b.element();
    if (left && right && left !== right) {
      if (left.contains(right)) return -1;
      if (right.contains(left)) return 1;
      const difference = layer(left) - layer(right);
      if (difference) return difference;
      return left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    }
    return popups.indexOf(a) - popups.indexOf(b);
  }).at(-1);
}

function handleEscape(event: KeyboardEvent) {
  if (event.key !== "Escape" || event.isComposing) return;
  const popup = topPopup();
  if (!popup) return;
  // Vor allen lokalen/globalen Handlern konsumieren, auch während eines Speichervorgangs.
  event.preventDefault();
  event.stopImmediatePropagation();
  if (event.repeat || popup.busy) return;
  popup.busy = true;
  try {
    Promise.resolve(popup.close()).finally(() => { popup.busy = false; }).catch(() => {
      // Fehleranzeige und Offenhalten gehören zum fachlichen Speicherpfad.
    });
  } catch {
    popup.busy = false;
  }
}

/** Eine Registrierung pro sichtbarem Popup; Callback-Wechsel verändern die Reihenfolge nicht. */
export function usePopupEscape(open: boolean, onClose: () => void | Promise<void>, ref?: RefObject<HTMLElement | null>) {
  const latest = useRef(onClose);
  const elementRef = useRef(ref);
  useLayoutEffect(() => { latest.current = onClose; elementRef.current = ref; });
  useLayoutEffect(() => {
    if (!open) return;
    const popup: Popup = { element: () => elementRef.current?.current ?? null, close: () => latest.current(), busy: false };
    if (!popups.length) window.addEventListener("keydown", handleEscape, true);
    popups.push(popup);
    return () => {
      popups.splice(popups.indexOf(popup), 1);
      if (!popups.length) window.removeEventListener("keydown", handleEscape, true);
    };
  }, [open]);
}

let scrollLocks = 0;
let previousOverflow = "";
export function usePopupScrollLock(open: boolean) {
  useLayoutEffect(() => {
    if (!open) return;
    if (scrollLocks++ === 0) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    return () => { if (--scrollLocks === 0) document.body.style.overflow = previousOverflow; };
  }, [open]);
}
