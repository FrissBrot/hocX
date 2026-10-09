"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { useTranslations } from "next-intl";

export type ToastType = "success" | "error" | "info";

export interface ToastItem {
  id: string;
  message: string;
  type: ToastType;
  onMessageClick?: () => void;
  action?: ToastAction;
}

/** Einzelne Folgeaktion direkt im Toast, z.B. "Rückgängig" nach dem Abhaken eines Todos. */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

type ToastOptions = { onMessageClick?: () => void; action?: ToastAction };

interface ToastContextValue {
  showToast: (message: string, type?: ToastType, opts?: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const dismiss = useCallback((id: string) => {
    clearTimeout(timers.current[id]);
    delete timers.current[id];
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastType = "info", opts?: ToastOptions) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setToasts((prev) => [...prev.slice(-3), { id, message, type, onMessageClick: opts?.onMessageClick, action: opts?.action }]);
      timers.current[id] = setTimeout(() => dismiss(id), 8000);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <ToastList toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

function ToastList({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  const t = useTranslations("common");
  if (toasts.length === 0) return null;

  return (
    <div className="app-toast-stack" role="region" aria-label={t("notificationsRegion")} aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`app-toast app-toast-${toast.type}`} role="alert">
          <span
            className={`app-toast-message${toast.onMessageClick ? " app-toast-navigable" : ""}`}
            onClick={toast.onMessageClick}
          >
            {toast.message}
          </span>
          {toast.action ? (
            <button
              type="button"
              className="app-toast-action"
              onClick={() => {
                toast.action?.onClick();
                onDismiss(toast.id);
              }}
            >
              {toast.action.label}
            </button>
          ) : null}
          <button
            type="button"
            className="app-toast-close"
            aria-label={t("close")}
            onClick={() => onDismiss(toast.id)}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx.showToast;
}
