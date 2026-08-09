"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type ConfirmTone = "default" | "danger";

export interface ConfirmOptions {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
}

type ConfirmRequest = Required<Omit<ConfirmOptions, "title">> & { title: string; id: string };

type ConfirmFn = (options: ConfirmOptions | string) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const resolver = useRef<((value: boolean) => void) | null>(null);

  const settle = useCallback((value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setRequest(null);
  }, []);

  const confirm = useCallback<ConfirmFn>((options) => {
    const normalized = typeof options === "string" ? { message: options } : options;
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
      setRequest({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        title: normalized.title ?? (normalized.tone === "danger" ? "Wirklich löschen?" : "Bitte bestätigen"),
        message: normalized.message,
        confirmLabel: normalized.confirmLabel ?? (normalized.tone === "danger" ? "Löschen" : "Bestätigen"),
        cancelLabel: normalized.cancelLabel ?? "Abbrechen",
        tone: normalized.tone ?? "default"
      });
    });
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {request ? <ConfirmDialog request={request} onCancel={() => settle(false)} onConfirm={() => settle(true)} /> : null}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({
  request,
  onCancel,
  onConfirm
}: {
  request: ConfirmRequest;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  return createPortal(
    <div
      className="confirm-backdrop"
      role="presentation"
      onClick={onCancel}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <div
        className={`confirm-shell confirm-${request.tone}`}
        role="alertdialog"
        aria-modal="true"
        aria-label={request.title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="confirm-icon" aria-hidden="true">
          {request.tone === "danger" ? "!" : "?"}
        </div>
        <div className="confirm-body">
          <h3 className="confirm-title">{request.title}</h3>
          <p className="confirm-message">{request.message}</p>
        </div>
        <div className="confirm-actions">
          <button type="button" ref={cancelRef} className="button-ghost" onClick={onCancel} autoFocus={request.tone === "danger"}>
            {request.cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmRef}
            className={request.tone === "danger" ? "button-danger" : "button-primary"}
            onClick={onConfirm}
            autoFocus={request.tone !== "danger"}
          >
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used inside ConfirmProvider");
  return ctx;
}
