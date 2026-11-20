"use client";

import { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode, RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { focusIsLost, focusTargetIn, getTabbables, registerReturnTarget } from "@/lib/a11y/focus";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";

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
    // Above .modal-backdrop (1200) and .confirm-backdrop (1300): popovers opened from inside a
    // modal (e.g. SearchableSelect in the upload dialog) are portaled to <body> and would
    // otherwise sit underneath it.
    zIndex: "var(--z-portal)",
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
  usePopupEscape(open, onClose, refs[refs.length - 1]);
  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (refs.some((ref) => ref.current?.contains(target))) {
        return;
      }
      // Aus dem Popover heraus geöffnete Panels (z. B. der Kalender eines DateInput) liegen als
      // eigenes Portal später im body. Ein Klick dort gehört zum Popover und darf es nicht
      // schliessen, sonst verschwindet das Feld samt Kalender, bevor das gewählte Datum ankommt.
      // Früher geöffnete Panels (das Menü unter einem Kalender) zählen nicht dazu.
      const own = refs[refs.length - 1]?.current;
      const panel = target instanceof Element ? target.closest(".popover-panel, .mini-menu-popover-portal") : null;
      if (own && panel && own.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING) {
        return;
      }
      onClose();
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, onClose]);
}

export type PopoverFocusMode = "menu" | "dialog";
export type PopoverInitialFocus = "first" | "panel" | "none";

const MENU_ITEMS = '[role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"]';

function menuItems(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(MENU_ITEMS)).filter(
    (item) => !item.hasAttribute("disabled") && item.getAttribute("aria-disabled") !== "true"
  );
}

/**
 * Tastaturvertrag aller Popover (design/KEYBOARD_ACCESSIBILITY.md, «Popover und Menüs»):
 *  - Öffnen legt den Fokus ins Panel (Menü: erster Eintrag, sonst erstes Feld bzw. das Panel),
 *    ausser der Fokus ist schon drin (z. B. Suchfeld per eigenem Effekt) oder `initialFocus="none"`.
 *  - Menüs: Pfeil hoch/runter, Pos1/Ende wandern zwischen den Einträgen; Tab verlässt das Menü wie
 *    vom Auslöser aus und schliesst es.
 *  - Dialog-artige Panels: Tab läuft durch die Felder; am Ende geht es hinter dem Auslöser
 *    weiter, Umschalt+Tab am Anfang zurück auf den Auslöser - das Panel schliesst dabei.
 *  - Escape (usePopupEscape) und Auswahl schliessen; lag der Fokus im Panel, kehrt er zum Auslöser
 *    zurück, statt auf <body> zu fallen.
 * Hintergrund: Popover liegen als Portal am Ende von <body>; ohne diese Regeln wären ihre
 * Einträge per Tab nur über die ganze Seite (in Dialogen gar nicht) erreichbar.
 */
export function usePopoverFocus({
  open,
  panelRef,
  anchorRef,
  returnFocusRef,
  onClose,
  mode,
  initialFocus = "first",
}: {
  open: boolean;
  panelRef: RefObject<HTMLElement | null>;
  anchorRef: RefObject<HTMLElement | null>;
  returnFocusRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
  mode: PopoverFocusMode;
  initialFocus?: PopoverInitialFocus;
}) {
  const hadFocusRef = useRef(false);
  const returnTarget = () => focusTargetIn(returnFocusRef?.current ?? anchorRef.current);

  useLayoutEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const unregister = registerReturnTarget(panel, returnTarget);
    if (initialFocus !== "none" && !panel.contains(document.activeElement)) {
      const target =
        initialFocus === "panel" ? panel : (mode === "menu" ? menuItems(panel)[0] : undefined) ?? getTabbables(panel)[0] ?? panel;
      if (target === panel && !panel.hasAttribute("tabindex")) panel.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    }
    return unregister;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open || !hadFocusRef.current) return;
    hadFocusRef.current = false;
    if (focusIsLost()) returnTarget()?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function onKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    const panel = panelRef.current;
    if (!panel || event.defaultPrevented || event.nativeEvent.isComposing) return;
    // Nur echte Menüs (mit menuitem-Einträgen) verhalten sich wie ein Menü; Panels mit Feldern
    // (Ansicht-Einstellungen, Checkbox-Listen) bleiben Tab-durchlaufbar, auch wenn role="menu" gesetzt ist.
    const isMenu = mode === "menu" && menuItems(panel).length > 0;
    if (event.key === "Tab") {
      const tabbables = getTabbables(panel);
      const active = document.activeElement;
      const atEnd = !event.shiftKey && (tabbables.length === 0 || active === tabbables[tabbables.length - 1]);
      const atStart = event.shiftKey && (tabbables.length === 0 || active === tabbables[0] || active === panel);
      if (!isMenu && !atEnd && !atStart) return;
      const back = returnTarget();
      hadFocusRef.current = false;
      onClose();
      if (!back) return;
      back.focus({ preventScroll: true });
      // Vorwärts: kein preventDefault - der Browser setzt die Tab-Reihenfolge ab dem Auslöser fort.
      // Rückwärts aus einem Dialog-Panel: auf dem Auslöser stehen bleiben (das Panel folgt ihm).
      if (event.shiftKey && !isMenu) event.preventDefault();
      return;
    }
    if (!isMenu || event.altKey || event.ctrlKey || event.metaKey) return;
    const items = menuItems(panel);
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "ArrowDown" ? items[(index + 1) % items.length]
      : event.key === "ArrowUp" ? items[(index - 1 + items.length) % items.length]
      : event.key === "Home" || event.key === "PageUp" ? items[0]
      : event.key === "End" || event.key === "PageDown" ? items[items.length - 1]
      : event.key.length === 1 && event.key !== " " ? typeahead(items, index, event.key)
      : undefined;
    if (next) {
      event.preventDefault();
      next.focus();
    }
  }

  return {
    onKeyDown,
    onFocus: () => {
      hadFocusRef.current = true;
    },
  };
}

/**
 * Auslöser eines Menüs (WAI-ARIA APG «Menu Button»): Pfeil runter/hoch öffnet zusätzlich zu
 * Enter/Leertaste (die über click laufen). Für alle Knöpfe mit aria-haspopup="menu".
 */
export function menuButtonKeyDown(open: boolean, setOpen: (open: boolean) => void) {
  return (event: ReactKeyboardEvent<HTMLElement>) => {
    if (open || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
    }
  };
}

function typeahead(items: HTMLElement[], index: number, key: string): HTMLElement | undefined {
  const needle = key.toLowerCase();
  const ordered = [...items.slice(index + 1), ...items.slice(0, index + 1)];
  return ordered.find((item) => (item.textContent ?? "").trim().toLowerCase().startsWith(needle));
}

type PopoverProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  anchorRef: RefObject<HTMLElement | null>;
  align?: Align;
  gap?: number;
  className?: string;
  /** ARIA-Rolle des Panels: «menu» (Standard, Aktionen), «dialog» (Felder/Filter), «presentation» (eigenes Widget darin, z. B. Listbox). */
  role?: "menu" | "dialog" | "presentation";
  /** Zugänglicher Name des Panels (Pflicht bei role="dialog"). */
  label?: string;
  /** Wohin der Fokus beim Öffnen geht (siehe usePopoverFocus). */
  initialFocus?: PopoverInitialFocus;
  children: ReactNode;
};

export function Popover({ open, onOpenChange, anchorRef, align = "start", gap = 6, className, role = "menu", label, initialFocus, children }: PopoverProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const style = usePopoverPosition(open, anchorRef, align, gap);
  usePopoverDismiss(open, () => onOpenChange(false), [anchorRef, panelRef]);
  const focus = usePopoverFocus({
    open,
    panelRef,
    anchorRef,
    onClose: () => onOpenChange(false),
    mode: role === "menu" ? "menu" : "dialog",
    initialFocus,
  });

  if (!open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      ref={panelRef}
      className={`popover-panel${className ? ` ${className}` : ""}`}
      style={style}
      role={role}
      aria-label={label}
      onKeyDown={focus.onKeyDown}
      onFocus={focus.onFocus}
    >
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
    <div className="menu-section" role="group" aria-label={label}>
      <div className="menu-section-label" aria-hidden="true">{label}</div>
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
      role={selected === undefined ? "menuitem" : "menuitemradio"}
      aria-checked={selected === undefined ? undefined : selected}
      className={`menu-item${selected ? " menu-item-selected" : ""}${danger ? " menu-item-danger" : ""}`}
      onClick={onSelect}
    >
      {icon ? <span className="menu-item-icon">{icon}</span> : null}
      <span className="menu-item-label">{children}</span>
      {selected ? <span className="menu-item-check" aria-hidden="true">✓</span> : null}
    </button>
  );
}

export function MenuDivider() {
  return <div className="menu-divider" role="separator" />;
}
