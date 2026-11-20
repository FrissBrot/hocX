"use client";

import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";

import { focusIsLost, restoreFocus, stableFocusTarget } from "@/lib/a11y/focus";
import { useFocusTrap } from "@/lib/a11y/use-focus-trap";
import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";

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
  const t = useTranslations("common.confirm");
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const resolver = useRef<((value: boolean) => void) | null>(null);
  // Element, das die Rückfrage ausgelöst hat (z. B. «Löschen»): bekommt den Fokus danach zurück.
  // Wurde es inzwischen entfernt (gelöschte Zeile), fällt restoreFocus auf den Hauptinhalt zurück.
  const openerRef = useRef<HTMLElement | null>(null);

  const settle = useCallback((value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setRequest(null);
  }, []);

  const confirm = useCallback<ConfirmFn>((options) => {
    const normalized = typeof options === "string" ? { message: options } : options;
    return new Promise<boolean>((resolve) => {
      if (!resolver.current && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
        openerRef.current = stableFocusTarget(document.activeElement);
      }
      resolver.current = resolve;
      setRequest({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        title: normalized.title ?? (normalized.tone === "danger" ? t("deleteTitle") : t("defaultTitle")),
        message: normalized.message,
        confirmLabel: normalized.confirmLabel ?? (normalized.tone === "danger" ? t("deleteConfirmLabel") : t("confirmLabel")),
        cancelLabel: normalized.cancelLabel ?? t("cancelLabel"),
        tone: normalized.tone ?? "default"
      });
    });
  }, [t]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {request ? <ConfirmDialog request={request} openerRef={openerRef} onCancel={() => settle(false)} onConfirm={() => settle(true)} /> : null}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({
  request,
  openerRef,
  onCancel,
  onConfirm
}: {
  request: ConfirmRequest;
  openerRef: React.MutableRefObject<HTMLElement | null>;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const messageId = useId();
  usePopupEscape(true, onCancel, rootRef);
  usePopupScrollLock(true);
  useFocusTrap(true, shellRef);
  // Fokus an den Auslöser zurückgeben. Löscht der Aufrufer danach die Zeile samt Auslöser,
  // fängt useFocusRescue (App-Shell) den verlorenen Fokus auf.
  useEffect(() => () => {
    const opener = openerRef.current;
    openerRef.current = null;
    if (focusIsLost(rootRef.current)) restoreFocus(opener);
  }, [openerRef]);

  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  return createPortal(
    <div
      ref={rootRef}
      className="confirm-backdrop"
      role="presentation"
      onClick={onCancel}
    >
      <div
        ref={shellRef}
        tabIndex={-1}
        className={`confirm-shell confirm-${request.tone}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="confirm-icon" aria-hidden="true">
          {request.tone === "danger" ? "!" : "?"}
        </div>
        <div className="confirm-body">
          <h3 className="confirm-title" id={titleId}>{request.title}</h3>
          <p className="confirm-message" id={messageId}>{request.message}</p>
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
  if (!ctx) throw new Error("useConfirm must be used inside ConfirmProvider"); // i18n-ok: Entwicklerfehler
  return ctx;
}
