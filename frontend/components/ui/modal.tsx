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
};

export function Modal({ open, title, description, children, onClose, size = "default", headerActions }: ModalProps) {
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
      <div className={`modal-shell modal-${size}`} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <div>
            <div className="eyebrow">Editor</div>
            <h2>{title}</h2>
            {description ? <p className="muted">{description}</p> : null}
          </div>
          <div className="modal-header-actions">
            {headerActions}
            <button type="button" className="button-ghost modal-close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        <div className="modal-content">{children}</div>
      </div>
    </div>,
    document.body
  );
}
