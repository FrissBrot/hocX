"use client";

import { ComponentProps, createContext, ReactNode, useContext, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";

import { focusIsLost, restoreFocus, stableFocusTarget } from "@/lib/a11y/focus";
import { useFocusTrap } from "@/lib/a11y/use-focus-trap";
import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";
import { ActionIcon } from "@/components/ui/action-icons";

const ModalDepth = createContext(0);
const pendingSaves = new WeakMap<HTMLFormElement, Promise<void>>();

/** Behält native Formularvalidierung bei und macht laufende Submits für Escape sichtbar. */
export function ModalSaveForm({ onSubmit, ...props }: ComponentProps<"form">) {
  return <form {...props} onSubmit={(event) => {
    const form = event.currentTarget;
    if (pendingSaves.has(form)) { event.preventDefault(); return; }
    const pending = Promise.resolve(onSubmit?.(event));
    pendingSaves.set(form, pending);
    void pending.then(
      () => pendingSaves.delete(form),
      () => pendingSaves.delete(form),
    );
  }} />;
}

type ModalProps = {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
  onEscape?: () => void | Promise<void>;
  /** `sheet`: Bottom-Sheet der Mobile-Oberflaeche (volle Breite, unten angedockt). */
  size?: "default" | "wide" | "fullscreen" | "sheet";
  headerActions?: ReactNode;
  hideCloseButton?: boolean;
  /** Skips the title bar entirely (no h2, no close button) for shells that build their own
   * header, e.g. a command-palette-style search field. The dialog keeps its aria-label. */
  hideHeader?: boolean;
  /** Ersetzt Titel + Beschreibung im Kopf (z.B. Avatar + Name); `title` bleibt das aria-label. */
  header?: ReactNode;
  /** Feste Aktionsleiste unten, scrollt nicht mit dem Inhalt (Submit per `form`-Attribut). */
  footer?: ReactNode;
  className?: string;
};

export function Modal({ open, title, description, children, onClose, onEscape, size = "default", headerActions, hideCloseButton = false, hideHeader = false, header, footer, className = "" }: ModalProps) {
  const t = useTranslations("common");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const depth = useContext(ModalDepth);
  const titleId = useId();
  const descriptionId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  // Klick-Ziehen aus dem Dialog (z. B. Textauswahl bis ueber den Rand) endet als click auf dem
  // Backdrop - geschlossen wird nur, wenn auch der mousedown auf dem Backdrop selbst begann
  // (Audit MAIN-FE-009, sonst gingen ungespeicherte Eingaben verloren).
  const pressStartedOnBackdropRef = useRef(false);
  // Element, das vor dem Oeffnen den Fokus hatte - bekommt ihn nach dem Schliessen zurueck.
  const previousFocusRef = useRef<HTMLElement | null>(null);
  if (open && previousFocusRef.current === null && typeof document !== "undefined" && document.activeElement instanceof HTMLElement) {
    previousFocusRef.current = stableFocusTarget(document.activeElement);
  }

  // Fokus beim Oeffnen in den Dialog legen (sofern nicht schon ein Feld per autoFocus drin ist)
  // und beim Schliessen zurueckgeben (WCAG 2.4.3). Ist das ausloesende Element inzwischen weg
  // (z. B. die geloeschte Zeile), landet der Fokus auf dem Hauptinhalt statt auf <body>.
  useEffect(() => {
    if (!open || !mounted) return;
    const shell = shellRef.current;
    if (shell && !shell.contains(document.activeElement)) shell.focus({ preventScroll: true });
    return () => {
      const previous = previousFocusRef.current;
      previousFocusRef.current = null;
      // Nur zurueckgeben, wenn der Fokus noch im Dialog war bzw. verloren ist - nicht, wenn
      // jemand inzwischen bewusst anderswo hin navigiert hat.
      if (focusIsLost(shell)) restoreFocus(previous);
    };
  }, [open, mounted]);

  // Tab/Shift+Tab bleiben im Dialog (lib/a11y/use-focus-trap.ts): nur sichtbare, aktive
  // Tab-Ziele zaehlen, Popover/Rueckfragen aus dem Dialog heraus gelten als innen, und auch ein
  // Tab bei verlorenem Fokus (<body>) landet wieder im Dialog.
  useFocusTrap(open && mounted, shellRef);
  usePopupScrollLock(open && mounted);
  usePopupEscape(open && mounted, () => {
    if (onEscape) return onEscape();
    // Explizite Speicheraktion, keine Suche nach Buttontext oder beliebigen Submits.
    const save = rootRef.current?.querySelector<HTMLButtonElement>("[data-modal-save]");
    if (save) {
      if (save.form && pendingSaves.has(save.form)) return pendingSaves.get(save.form);
      if (!save.disabled) save.click();
      return save.form ? pendingSaves.get(save.form) : undefined;
    }
    onClose();
  }, rootRef);

  if (!open || !mounted) {
    return null;
  }

  return createPortal(
    <ModalDepth.Provider value={depth + 1}>
    <div
      ref={rootRef}
      style={{ zIndex: `calc(var(--z-modal) + ${depth})` }}
      className="modal-backdrop"
      onMouseDown={(event) => { pressStartedOnBackdropRef.current = event.target === event.currentTarget; }}
      onClick={(event) => {
        const startedOnBackdrop = pressStartedOnBackdropRef.current;
        pressStartedOnBackdropRef.current = false;
        if (event.target === event.currentTarget && startedOnBackdrop) onClose();
      }}
      role="presentation"
    >
      <div
        ref={shellRef}
        tabIndex={-1}
        className={`modal-shell modal-${size}${hideHeader ? " modal-noheader" : ""}${footer ? " modal-has-footer" : ""} ${className}`}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={hideHeader || header ? title : undefined}
        aria-labelledby={hideHeader || header ? undefined : titleId}
        aria-describedby={description && !hideHeader && !header ? descriptionId : undefined}
      >
        {!hideHeader ? (
          <div className="modal-header">
            {header ?? (
              <div>
                <h2 id={titleId}>{title}</h2>
                {description ? <p className="muted" id={descriptionId}>{description}</p> : null}
              </div>
            )}
            <div className="modal-header-actions">
              {headerActions}
              {!hideCloseButton ? (
                <button type="button" className="button-icon modal-close" onClick={onClose} aria-label={t("close")}>
                  <ActionIcon name="close" />
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="modal-content">{children}</div>
        {footer ? <div className="modal-footer">{footer}</div> : null}
      </div>
    </div>
    </ModalDepth.Provider>,
    document.body
  );
}
