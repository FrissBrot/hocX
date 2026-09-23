"use client";

import { ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";

type ModalProps = {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
  size?: "default" | "wide" | "fullscreen";
  headerActions?: ReactNode;
  hideCloseButton?: boolean;
  className?: string;
};

export function Modal({ open, title, description, children, onClose, size = "default", headerActions, hideCloseButton = false, className = "" }: ModalProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open || !mounted) {
    return null;
  }

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className={`modal-shell modal-${size} ${className}`} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
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
        <div className="modal-content">{children}</div>
      </div>
    </div>,
    document.body
  );
}
