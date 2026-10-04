"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import {
  discardBlockedMutations,
  flushOutbox,
  getOfflineServerSnapshot,
  getOfflineSnapshot,
  initializeOfflineStore,
  setNetworkOnline,
  subscribeOfflineStore,
} from "@/lib/offline-store";

export function ConnectivityStatus() {
  const t = useTranslations("common.connectivity");
  const state = useSyncExternalStore(subscribeOfflineStore, getOfflineSnapshot, getOfflineServerSnapshot);

  useEffect(() => {
    initializeOfflineStore();
    const online = () => { setNetworkOnline(true); void flushOutbox(); };
    const offline = () => setNetworkOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    void flushOutbox();
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (state.pending > 0) event.preventDefault();
    };
    const guardInternalNavigation = (event: MouseEvent) => {
      if (state.pending === 0 || event.defaultPrevented || event.button !== 0) return;
      const anchor = (event.target as Element | null)?.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.origin !== window.location.origin || anchor.target === "_blank") return;
      // Synchrone Abfrage im Klick-Handler: useConfirm() ist async und kann die Navigation nicht mehr stoppen.
      if (!window.confirm(t("leaveConfirm"))) { // design-ok
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", guardInternalNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", guardInternalNavigation, true);
    };
  }, [state.pending, t]);

  if (state.online && state.pending === 0 && !state.flushing && !state.lastError) return null;
  const message = !state.online
    ? (state.pending ? t("offlineWithPending", { count: state.pending }) : t("offlineIdle"))
    : state.flushing
      ? t("flushing", { count: state.pending })
      : state.pending
        ? t("pendingUnsaved", { count: state.pending })
        : state.lastError ?? t("reconnected");

  return (
    <div className={`connectivity-status ${!state.online || state.lastError ? "connectivity-status-error" : ""}`} role="status" aria-live="polite">
      <span>{message}</span>
      {state.online && state.pending > 0 && !state.flushing && (
        <button type="button" onClick={() => void flushOutbox()}>{t("retryButton")}</button>
      )}
      {state.blocked > 0 && (
        // Mutations rejected with a non-retryable error (validation/auth/conflict) stay
        // queued forever otherwise - they no longer block unrelated pending changes from
        // being sent (see flushOutbox), but they also never resolve on their own, so give
        // the user an explicit way to give up on them.
        <button type="button" onClick={() => discardBlockedMutations()}>
          {t("discardBlocked", { count: state.blocked })}
        </button>
      )}
    </div>
  );
}
