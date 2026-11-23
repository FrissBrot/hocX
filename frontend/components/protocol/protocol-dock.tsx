"use client";

import { memo, ReactNode, RefObject, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { ariaKeyShortcuts, formatCombo, getShortcut, type KeyNameTranslator, type ShortcutId } from "@/lib/keyboard/registry";
import { useIsApple } from "@/lib/search/shortcuts";

// Dock und Schublade des Protokoll-Editors (Design «Protokoll-Editor 1a»): unten mittig vier
// Knöpfe, rechts eine Schublade mit Sitzungsnotizen, schneller Pendenz, Anliegen sowie Status &
// Zusammenarbeit. Ersetzt Schnellmenü-Pille, Hover-Flyouts und Statuspanel.

export type DrawerId = "notes" | "todo" | "agenda" | "status";

export const DRAWER_SHORTCUTS: Record<DrawerId, ShortcutId> = {
  notes: "protocol.openNotes",
  todo: "protocol.openTodo",
  agenda: "protocol.openAgenda",
  status: "protocol.openStatus",
};

const DRAWER_ORDER: DrawerId[] = ["notes", "todo", "agenda", "status"];

/** Beschriftung eines Kürzels aus der Registry (Apple: ⌥⌘N, sonst Strg+Alt+N). */
export function useShortcutCombo(): (id: ShortcutId) => string {
  const apple = useIsApple();
  const tKeys = useTranslations("common.keys");
  return (id) => formatCombo(getShortcut(id).keys[0], apple, tKeys as unknown as KeyNameTranslator);
}

type DockProps = {
  open: DrawerId | null;
  /** Pendenz und Anliegen gibt es im abgeschlossenen Protokoll nicht */
  readOnly: boolean;
  onToggle: (id: DrawerId) => void;
};

export const ProtocolDock = memo(function ProtocolDock({ open, readOnly, onToggle }: DockProps) {
  const t = useTranslations("protocols.editor.drawer");
  const combo = useShortcutCombo();
  return (
    <div className="protocol-dock" role="toolbar" aria-label={t("dockLabel")}>
      {DRAWER_ORDER.map((id) => {
        const disabled = readOnly && (id === "todo" || id === "agenda");
        return (
          <button
            key={id}
            type="button"
            className={`protocol-dock-button${open === id ? " protocol-dock-button-active" : ""}`}
            data-drawer-button={id}
            aria-expanded={open === id}
            aria-controls="protocol-drawer"
            aria-keyshortcuts={ariaKeyShortcuts(DRAWER_SHORTCUTS[id])}
            disabled={disabled}
            onClick={() => onToggle(id)}
          >
            {t(`${id}.dock`)}
            <span className="protocol-dock-key" aria-hidden="true">{combo(DRAWER_SHORTCUTS[id])}</span>
          </button>
        );
      })}
    </div>
  );
});

type DrawerProps = {
  open: DrawerId | null;
  onClose: () => void;
  /** Inhalt je Schublade; nicht aktive bleiben eingehängt, aber verborgen (Entwürfe gehen nicht verloren) */
  children: ReactNode;
  /** Escape behandelt die Schublade selbst nur dort, wo kein eigener Inhalt es tut */
  handlesEscape: boolean;
  drawerRef: RefObject<HTMLElement | null>;
};

export function ProtocolDrawer({ open, onClose, children, handlesEscape, drawerRef }: DrawerProps) {
  const t = useTranslations("protocols.editor.drawer");
  const tCommon = useTranslations("common");
  const combo = useShortcutCombo();
  usePopupEscape(!!open && handlesEscape, onClose, drawerRef);

  // Klick ausserhalb von Schublade, Dock und Popups schliesst (wie im Design)
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Element | null;
      if (!target || !(target instanceof Element)) return;
      if (drawerRef.current?.contains(target)) return;
      if (target.closest(".protocol-dock, .popover-panel, .mini-menu-popover-portal, [aria-modal='true'], .dropdown-panel")) return;
      onCloseRef.current();
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open, drawerRef]);

  return (
    <aside
      id="protocol-drawer"
      ref={drawerRef}
      className="protocol-drawer"
      hidden={!open}
      aria-labelledby="protocol-drawer-title"
    >
      <div className="protocol-drawer-head">
        <h2 className="protocol-drawer-title" id="protocol-drawer-title">{open ? t(`${open}.title`) : ""}</h2>
        {open ? <span className="protocol-drawer-key" aria-hidden="true">{combo(DRAWER_SHORTCUTS[open])}</span> : null}
        {open === "notes" ? <Badge variant="neutral">{t("notes.notInPdf")}</Badge> : null}
        <span className="protocol-header-spacer" aria-hidden="true" />
        <button type="button" className="button-ghost button-icon protocol-drawer-close" aria-label={tCommon("close")} onClick={onClose}>
          <ActionIcon name="close" />
        </button>
      </div>
      <div className="protocol-drawer-body">{children}</div>
    </aside>
  );
}
