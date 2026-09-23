"use client";

import { ComponentProps, createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";

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
  size?: "default" | "wide" | "fullscreen";
  headerActions?: ReactNode;
  hideCloseButton?: boolean;
  /** Skips the title bar entirely (no h2, no close button) for shells that build their own
   * header, e.g. a command-palette-style search field. The dialog keeps its aria-label. */
  hideHeader?: boolean;
  className?: string;
};

export function Modal({ open, title, description, children, onClose, onEscape, size = "default", headerActions, hideCloseButton = false, hideHeader = false, className = "" }: ModalProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const depth = useContext(ModalDepth);
  const rootRef = useRef<HTMLDivElement>(null);
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
    <div ref={rootRef} style={{ zIndex: `calc(var(--z-modal) + ${depth})` }} className="modal-backdrop" onClick={onClose} role="presentation">
      <div className={`modal-shell modal-${size}${hideHeader ? " modal-noheader" : ""} ${className}`} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        {!hideHeader ? (
          <div className="modal-header">
            <div>
              <h2>{title}</h2>
              {description ? <p className="muted">{description}</p> : null}
            </div>
            <div className="modal-header-actions">
              {headerActions}
              {!hideCloseButton ? (
                <button type="button" className="button-icon modal-close" onClick={onClose} aria-label="Schliessen">
                  <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="16" height="16">
                    <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="modal-content">{children}</div>
      </div>
    </div>
    </ModalDepth.Provider>,
    document.body
  );
}
