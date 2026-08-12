"use client";

import { CSSProperties, ReactNode, RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type Align = "start" | "end";

type PopoverPositionOptions = {
  // Floor for the panel width below which it won't shrink, even if the anchor itself is
  // narrower (e.g. a small icon trigger opening a wider menu). Defaults to the anchor's
  // own width, matching the original behavior before this option existed.
  minWidth?: number;
  estimatedHeight?: number;
};

// Pure positioning calc, flipping above the anchor rect when there isn't enough room
// below - same heuristic todo-assignee-menu.tsx used before this primitive existed,
// generalized so every popover in the app positions consistently. Takes a plain
// DOMRect (not a ref) so it also covers point-anchored popovers like a right-click
// context menu, which has no persistent DOM element to attach a ref to.
export function computePopoverPosition(rect: DOMRect, align: Align, gap: number, options?: PopoverPositionOptions): CSSProperties {
  const margin = 8;
  const estimatedHeight = options?.estimatedHeight ?? 320;
  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;
  const showAbove = spaceBelow < estimatedHeight && spaceAbove > spaceBelow;
  return {
    position: "fixed",
    ...(showAbove
      ? { bottom: window.innerHeight - rect.top + gap, maxHeight: spaceAbove }
      : { top: rect.bottom + gap, maxHeight: spaceBelow }),
    ...(align === "end" ? { right: window.innerWidth - rect.right } : { left: rect.left }),
    minWidth: options?.minWidth ? Math.max(rect.width, options.minWidth) : rect.width,
    zIndex: "var(--z-popover)",
    overflowY: "auto",
  };
}

// Anchors the popover to `anchorRef`'s rect - see computePopoverPosition() for the
// actual placement heuristic.
export function usePopoverPosition(
  open: boolean,
  anchorRef: RefObject<HTMLElement | null>,
  align: Align,
  gap: number,
  options?: PopoverPositionOptions
) {
  // Fixed position must be set before the browser paints - otherwise the portaled
  // panel briefly renders unpositioned at the end of <body> (bottom of the whole
  // page), and an autoFocus input inside it makes the browser auto-scroll there.
  const [style, setStyle] = useState<CSSProperties>({});

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      return;
    }
    setStyle(computePopoverPosition(anchorRef.current.getBoundingClientRect(), align, gap, options));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, anchorRef, align, gap, options?.minWidth, options?.estimatedHeight]);

  return style;
}

export function usePopoverDismiss(open: boolean, onClose: () => void, refs: RefObject<HTMLElement | null>[]) {
  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (refs.some((ref) => ref.current?.contains(target))) {
        return;
      }
      onClose();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, onClose]);
}

type PopoverProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  anchorRef: RefObject<HTMLElement | null>;
  align?: Align;
  gap?: number;
  className?: string;
  children: ReactNode;
};

export function Popover({ open, onOpenChange, anchorRef, align = "start", gap = 6, className, children }: PopoverProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const style = usePopoverPosition(open, anchorRef, align, gap);
  usePopoverDismiss(open, () => onOpenChange(false), [anchorRef, panelRef]);

  if (!open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div ref={panelRef} className={`popover-panel${className ? ` ${className}` : ""}`} style={style} role="menu">
      {children}
    </div>,
    document.body
  );
}

export function Menu({ children }: { children: ReactNode }) {
  return <div className="menu">{children}</div>;
}

export function MenuSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="menu-section">
      <div className="menu-section-label">{label}</div>
      {children}
    </div>
  );
}

type MenuItemProps = {
  icon?: ReactNode;
  selected?: boolean;
  danger?: boolean;
  onSelect: () => void;
  children: ReactNode;
};

export function MenuItem({ icon, selected, danger, onSelect, children }: MenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`menu-item${selected ? " menu-item-selected" : ""}${danger ? " menu-item-danger" : ""}`}
      onClick={onSelect}
    >
      {icon ? <span className="menu-item-icon">{icon}</span> : null}
      <span className="menu-item-label">{children}</span>
      {selected ? <span className="menu-item-check">✓</span> : null}
    </button>
  );
}

export function MenuDivider() {
  return <div className="menu-divider" role="separator" />;
}
