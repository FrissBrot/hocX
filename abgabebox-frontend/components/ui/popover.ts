"use client";

// Positionierung und Schliessen von Popups (Liste des Auswahlfelds). Schlanke Fassung von
// frontend/components/ui/popover.tsx: gleiche Platzierung (unter dem Anker, bei wenig Platz
// darüber), Schliessen per Klick ausserhalb und Escape.

import { CSSProperties, RefObject, useEffect, useRef } from "react";

export type Align = "start" | "end";

export function computePopoverPosition(rect: DOMRect, align: Align, gap: number, options?: { minWidth?: number; estimatedHeight?: number }): CSSProperties {
  const margin = 8;
  const estimatedHeight = options?.estimatedHeight ?? 320;
  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;
  const showAbove = spaceBelow < estimatedHeight && spaceAbove > spaceBelow;
  return {
    position: "fixed",
    ...(showAbove ? { bottom: window.innerHeight - rect.top + gap, maxHeight: spaceAbove } : { top: rect.bottom + gap, maxHeight: spaceBelow }),
    ...(align === "end" ? { right: window.innerWidth - rect.right } : { left: rect.left }),
    minWidth: options?.minWidth ? Math.max(rect.width, options.minWidth) : rect.width,
    zIndex: "var(--z-portal)",
    overflowY: "auto",
  };
}

export function usePopoverDismiss(open: boolean, onClose: () => void, refs: RefObject<HTMLElement | null>[]) {
  const latest = useRef(onClose);
  latest.current = onClose;
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (refs.some((ref) => ref.current?.contains(target))) return;
      latest.current();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.isComposing) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      latest.current();
    }
    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown, true);
    };
    // refs sind stabile Ref-Objekte
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}
