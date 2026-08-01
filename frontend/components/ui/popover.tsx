"use client";

import { CSSProperties, ReactNode, RefObject, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Align = "start" | "end";

// Anchors the popover to `anchorRef`'s rect, flipping above the anchor when there
// isn't enough room below - same heuristic todo-assignee-menu.tsx used before this
// primitive existed, generalized so every popover in the app positions consistently.
function usePopoverPosition(open: boolean, anchorRef: RefObject<HTMLElement | null>, align: Align, gap: number) {
  const [style, setStyle] = useState<CSSProperties>({});

  useEffect(() => {
    if (!open || !anchorRef.current) {
      return;
    }
    const rect = anchorRef.current.getBoundingClientRect();
    const margin = 8;
    const estimatedHeight = 320;
    const spaceBelow = window.innerHeight - rect.bottom - margin;
    const spaceAbove = rect.top - margin;
    const showAbove = spaceBelow < estimatedHeight && spaceAbove > spaceBelow;
    setStyle({
      position: "fixed",
      ...(showAbove
        ? { bottom: window.innerHeight - rect.top + gap, maxHeight: spaceAbove }
        : { top: rect.bottom + gap, maxHeight: spaceBelow }),
      ...(align === "end" ? { right: window.innerWidth - rect.right } : { left: rect.left }),
      minWidth: rect.width,
      zIndex: "var(--z-popover)",
      overflowY: "auto",
    });
  }, [open, anchorRef, align, gap]);

  return style;
}

function usePopoverDismiss(open: boolean, onClose: () => void, refs: RefObject<HTMLElement | null>[]) {
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
