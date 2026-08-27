"use client";

import { useEffect, useSyncExternalStore } from "react";
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
      if (!window.confirm("Es gibt noch nicht gespeicherte Änderungen. Seite trotzdem verlassen?")) {
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
  }, [state.pending]);

  if (state.online && state.pending === 0 && !state.flushing && !state.lastError) return null;
  const message = !state.online
    ? `Offline – ${state.pending ? `${state.pending} Änderung${state.pending === 1 ? "" : "en"} lokal vorgemerkt` : "Verbindung wird überwacht"}`
    : state.flushing
      ? `${state.pending} Änderung${state.pending === 1 ? "" : "en"} wird nachgesendet …`
      : state.pending
        ? `${state.pending} Änderung${state.pending === 1 ? "" : "en"} noch nicht gespeichert`
        : state.lastError ?? "Verbindung wiederhergestellt";

  return (
    <div className={`connectivity-status ${!state.online || state.lastError ? "connectivity-status-error" : ""}`} role="status" aria-live="polite">
      <span>{message}</span>
      {state.online && state.pending > 0 && !state.flushing && (
        <button type="button" onClick={() => void flushOutbox()}>Jetzt erneut versuchen</button>
      )}
      {state.blocked > 0 && (
        // Mutations rejected with a non-retryable error (validation/auth/conflict) stay
        // queued forever otherwise - they no longer block unrelated pending changes from
        // being sent (see flushOutbox), but they also never resolve on their own, so give
        // the user an explicit way to give up on them.
        <button type="button" onClick={() => discardBlockedMutations()}>
          {state.blocked === 1
            ? "Fehlgeschlagene Änderung verwerfen"
            : `${state.blocked} fehlgeschlagene Änderungen verwerfen`}
        </button>
      )}
    </div>
  );
}
