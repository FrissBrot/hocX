"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

export type CollaboratorInfo = {
  user_id: string;
  display_name: string;
};

export type FieldUpdateEvent = {
  field_key: string;
  patch: unknown;
  user_id: string;
  display_name: string;
};

type StatusChangedEvent = {
  status: string;
  user_id: string;
  display_name: string;
};

export type ListChangedEvent = {
  list_definition_id: string;
  content_version: number;
};

/** Traktanden im Protokoll geändert (API «agenda_changed», Editor 1a) */
export type AgendaChangedEvent = {
  action: "added" | "renamed" | "visibility" | "reordered";
  element_id: string | null;
  element_ids: string[];
  user_id: string;
  display_name: string;
};

/** Wo eine Person im Protokoll gerade ist (API «presence_focus», je Verbindung). */
export type PresenceFocus = {
  user_id: string;
  display_name: string;
  connection_id: string;
  element_id: string | null;
  block_id: string | null;
  mode: "viewing" | "editing" | null;
};

export type FieldLocks = Readonly<Record<string, CollaboratorInfo>>;

const EMPTY_LOCKS: FieldLocks = Object.freeze({});

/**
 * Sperren fremder Personen ausserhalb des React-Zustands: ein Fokuswechsel einer anderen Person
 * ändert nur diesen Store. Neu rendern nur Komponenten, die die betroffenen Felder abonniert haben
 * (useFieldLocksSignature, useFieldLocks) - nicht mehr der ganze Editor mit allen Punkten
 * (Performance-Audit 2026-11-22, K1).
 */
function createLockStore() {
  let locks: FieldLocks = EMPTY_LOCKS;
  const listeners = new Set<() => void>();
  return {
    get: (): FieldLocks => locks,
    update(updater: (current: FieldLocks) => FieldLocks) {
      const next = updater(locks);
      if (next === locks) return;
      locks = next;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/**
 * Stabile Sperr-Schnittstelle für die Punkte des Editors: alle Funktionen behalten ihre Identität
 * über die ganze Lebensdauer der Verbindung, damit memoisierte Punkte nicht bei jeder Sperr- oder
 * Anwesenheitsänderung neu rendern. Den aktuellen Stand liest ``isLockedByOther``; neu gerendert
 * wird über ein Abonnement (``useFieldLocksSignature``).
 */
export type CollabFieldLocks = {
  lockField: (fieldKey: string) => void;
  unlockField: (fieldKey: string) => void;
  isLockedByOther: (fieldKey: string) => CollaboratorInfo | null;
  subscribeLocks: (listener: () => void) => () => void;
  getLocks: () => FieldLocks;
};

const HEARTBEAT_INTERVAL_MS = 20_000;
const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 15_000;

function wsUrlForProtocol(protocolId: string): string {
  // Same-origin: WS-Scheme + aktueller Host, damit das auf jeder Domain (Haupt- oder
  // Mandanten-Custom-Domain) automatisch gegen die richtige Origin geht.
  const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${wsScheme}://${window.location.host}/api/ws/protocols/${protocolId}`;
}

/**
 * Live collaboration channel for one protocol: presence, per-block/per-cell field locks,
 * and broadcast of "this changed" events. Value persistence itself still goes through the
 * normal REST autosave endpoints - this hook only carries the collaboration layer on top,
 * so it can fail/reconnect without affecting the ability to save.
 */
export function useProtocolCollaboration(protocolId: string | null | undefined) {
  const [connected, setConnected] = useState(false);
  const [canEdit, setCanEdit] = useState(true);
  const [selfUserId, setSelfUserId] = useState<string | null>(null);
  const [presence, setPresence] = useState<CollaboratorInfo[]>([]);
  // Ort je Verbindung (presence_focus); eigene Verbindungen bleiben drin, gefiltert wird beim Lesen
  const [focusByConnection, setFocusByConnection] = useState<Record<string, PresenceFocus>>({});
  const lastFocusRef = useRef<string | null>(null);
  const lockStoreRef = useRef<ReturnType<typeof createLockStore> | null>(null);
  if (lockStoreRef.current === null) lockStoreRef.current = createLockStore();
  const lockStore = lockStoreRef.current;
  const setLocks = lockStore.update;

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_BASE_DELAY_MS);
  const heartbeatTimerRef = useRef<number | null>(null);
  const ownLocksRef = useRef<Set<string>>(new Set());
  // Mirrors selfUserId for the onmessage closure, which is created once per connection and
  // would otherwise only ever see the selfUserId value from the render that opened the socket.
  const selfUserIdRef = useRef<string | null>(null);
  const fieldUpdateListenersRef = useRef<Set<(event: FieldUpdateEvent) => void>>(new Set());
  const statusChangedListenersRef = useRef<Set<(event: StatusChangedEvent) => void>>(new Set());
  const listChangedListenersRef = useRef<Set<(event: ListChangedEvent) => void>>(new Set());
  const agendaChangedListenersRef = useRef<Set<(event: AgendaChangedEvent) => void>>(new Set());

  const send = useCallback((message: Record<string, unknown>) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }, []);

  useEffect(() => {
    if (!protocolId) return;
    // Pro Effect-Lauf eigener Zustand (Audit MAIN-FE-008): ein von allen Laeufen geteiltes Ref
    // setzte der naechste Lauf sofort wieder auf "offen", bevor das asynchrone onclose des alten
    // Sockets feuerte - das plante dann einen Reconnect, raeumte den Heartbeat des neuen Sockets
    // ab und liess eine verwaiste Zusatzverbindung offen (in Dev/StrictMode bei jedem Mount).
    let disposed = false;

    function scheduleReconnect() {
      if (disposed) return;
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = window.setTimeout(connect, reconnectDelayRef.current);
      reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, RECONNECT_MAX_DELAY_MS);
    }

    function connect() {
      if (disposed || !protocolId) return;
      const socket = new WebSocket(wsUrlForProtocol(protocolId));
      socketRef.current = socket;

      socket.onopen = () => {
        setConnected(true);
        reconnectDelayRef.current = RECONNECT_BASE_DELAY_MS;
        if (heartbeatTimerRef.current) window.clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = window.setInterval(() => {
          ownLocksRef.current.forEach((fieldKey) => send({ type: "heartbeat", field_key: fieldKey }));
        }, HEARTBEAT_INTERVAL_MS);
      };

      socket.onclose = () => {
        setConnected(false);
        if (heartbeatTimerRef.current) window.clearInterval(heartbeatTimerRef.current);
        scheduleReconnect();
      };

      socket.onerror = () => {
        socket.close();
      };

      socket.onmessage = (event) => {
        let message: Record<string, any>;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (message.type) {
          case "snapshot": {
            const selfId = message.self?.user_id ?? null;
            selfUserIdRef.current = selfId;
            setSelfUserId(selfId);
            setCanEdit(message.self?.can_edit !== false);
            const presenceList = Array.isArray(message.presence) ? (message.presence as CollaboratorInfo[]) : [];
            setPresence(presenceList);
            const focusList = Array.isArray(message.focus) ? (message.focus as PresenceFocus[]) : [];
            setFocusByConnection(Object.fromEntries(focusList.filter((entry) => entry.connection_id).map((entry) => [entry.connection_id, entry])));
            // Nach (Wieder-)Verbindung den eigenen Ort erneut melden
            lastFocusRef.current = null;
            const serverLocks = (message.locks as Record<string, CollaboratorInfo>) ?? {};
            // Nur fremde Sperren im Store: eigene ändern nichts an der Anzeige, würden aber bei
            // jedem Fokuswechsel neu rendern lassen (eigene stehen in ownLocksRef).
            setLocks(() => Object.fromEntries(Object.entries(serverLocks).filter(([, holder]) => holder.user_id !== selfId)));
            // Reconciled against the server's authoritative snapshot on every (re)connect,
            // not left as whatever this client last knew locally (audit finding,
            // 2026-08-25) - ownLocksRef otherwise still listed a field this client held
            // before a disconnect even if the server no longer agrees (expired/reassigned
            // during the gap), so the heartbeat loop above kept renewing a lock on the new
            // connection that the server never actually granted it, and this client's own
            // editor could still believe it holds a field lock that's silently gone.
            for (const fieldKey of Array.from(ownLocksRef.current)) {
              if (serverLocks[fieldKey]?.user_id !== selfId) {
                ownLocksRef.current.delete(fieldKey);
              }
            }
            break;
          }
          case "presence_join": {
            setPresence((current) => {
              if (current.some((entry) => entry.user_id === message.user_id)) return current;
              return [...current, { user_id: message.user_id, display_name: message.display_name }];
            });
            break;
          }
          case "presence_leave": {
            setPresence((current) => current.filter((entry) => entry.user_id !== message.user_id));
            break;
          }
          case "lock_acquired":
          case "lock_denied": {
            const holder: CollaboratorInfo = message.type === "lock_denied" ? message.holder : {
              user_id: message.user_id,
              display_name: message.display_name,
            };
            const fieldKey = message.field_key as string;
            setLocks((current) => {
              if (holder.user_id === selfUserIdRef.current) {
                if (!(fieldKey in current)) return current;
                const next = { ...current };
                delete next[fieldKey];
                return next;
              }
              if (current[fieldKey]?.user_id === holder.user_id) return current;
              return { ...current, [fieldKey]: holder };
            });
            break;
          }
          case "lock_released": {
            ownLocksRef.current.delete(message.field_key);
            setLocks((current) => {
              if (!(message.field_key in current)) return current;
              const next = { ...current };
              delete next[message.field_key];
              return next;
            });
            break;
          }
          case "field_update": {
            if (message.user_id === selfUserIdRef.current) break;
            fieldUpdateListenersRef.current.forEach((listener) => listener(message as FieldUpdateEvent));
            break;
          }
          case "status_changed": {
            if (message.user_id === selfUserIdRef.current) break;
            statusChangedListenersRef.current.forEach((listener) => listener(message as StatusChangedEvent));
            break;
          }
          case "presence_focus": {
            const entry = message as PresenceFocus;
            if (!entry.connection_id) break;
            setFocusByConnection((current) => {
              if (!entry.element_id && !entry.block_id) {
                if (!(entry.connection_id in current)) return current;
                const next = { ...current };
                delete next[entry.connection_id];
                return next;
              }
              return { ...current, [entry.connection_id]: entry };
            });
            break;
          }
          case "agenda_changed": {
            if (message.user_id === selfUserIdRef.current) break;
            agendaChangedListenersRef.current.forEach((listener) => listener(message as AgendaChangedEvent));
            break;
          }
          case "list_changed": {
            // No user_id/self-filtering here - every open protocol referencing this list
            // (including whichever protocol/tab caused the change) reacts identically.
            listChangedListenersRef.current.forEach((listener) => listener(message as ListChangedEvent));
            break;
          }
          default:
            break;
        }
      };
    }

    connect();

    return () => {
      disposed = true;
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      if (heartbeatTimerRef.current) window.clearInterval(heartbeatTimerRef.current);
      const socket = socketRef.current;
      if (socket) {
        // Handler loesen, bevor geschlossen wird: das verspaetete onclose darf weder den
        // naechsten Effect-Lauf stoeren noch einen Reconnect planen.
        socket.onopen = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        socket.close();
      }
      socketRef.current = null;
      ownLocksRef.current.clear();
      setConnected(false);
      setPresence([]);
      setFocusByConnection({});
      setLocks(() => EMPTY_LOCKS);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    };
    // selfUserId intentionally excluded: message handlers read it via closure per-effect-run,
    // and the socket is not expected to reconnect just because our own id became known.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [protocolId, send]);

  const lockField = useCallback((fieldKey: string) => {
    ownLocksRef.current.add(fieldKey);
    send({ type: "lock_request", field_key: fieldKey });
  }, [send]);

  const unlockField = useCallback((fieldKey: string) => {
    ownLocksRef.current.delete(fieldKey);
    send({ type: "unlock", field_key: fieldKey });
    setLocks((current) => {
      if (!(fieldKey in current)) return current;
      if (current[fieldKey].user_id !== selfUserIdRef.current) return current;
      const next = { ...current };
      delete next[fieldKey];
      return next;
    });
  }, [send, setLocks]);

  const sendFieldUpdate = useCallback((fieldKey: string, patch: unknown) => {
    send({ type: "field_update", field_key: fieldKey, patch });
  }, [send]);

  const sendStatusChanged = useCallback((status: string) => {
    send({ type: "status_changed", status });
  }, [send]);

  const onFieldUpdate = useCallback((listener: (event: FieldUpdateEvent) => void) => {
    fieldUpdateListenersRef.current.add(listener);
    return () => {
      fieldUpdateListenersRef.current.delete(listener);
    };
  }, []);

  const onStatusChanged = useCallback((listener: (event: StatusChangedEvent) => void) => {
    statusChangedListenersRef.current.add(listener);
    return () => {
      statusChangedListenersRef.current.delete(listener);
    };
  }, []);

  /** Eigenen Ort melden (nur bei Wechsel; der Server drosselt zusätzlich). */
  const sendFocus = useCallback((elementId: string | null, blockId: string | null, mode: "viewing" | "editing") => {
    const key = `${elementId}|${blockId}|${mode}`;
    if (lastFocusRef.current === key) return;
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    lastFocusRef.current = key;
    send({ type: "focus", element_id: elementId, block_id: blockId, mode });
  }, [send]);

  const onAgendaChanged = useCallback((listener: (event: AgendaChangedEvent) => void) => {
    agendaChangedListenersRef.current.add(listener);
    return () => {
      agendaChangedListenersRef.current.delete(listener);
    };
  }, []);

  const onListChanged = useCallback((listener: (event: ListChangedEvent) => void) => {
    listChangedListenersRef.current.add(listener);
    return () => {
      listChangedListenersRef.current.delete(listener);
    };
  }, []);

  // Liest den aktuellen Stand (keine Abhängigkeit vom Render): wer neu rendern muss, abonniert
  // die Sperren (useFieldLocksSignature/useFieldLocks).
  const isLockedByOther = useCallback((fieldKey: string): CollaboratorInfo | null => {
    const holder = lockStore.get()[fieldKey];
    if (!holder || holder.user_id === selfUserIdRef.current) return null;
    return holder;
  }, [lockStore]);

  // Funktion statt Wert: nur in Rückfragen gebraucht, ein Wert liesse den Editor bei jeder
  // fremden Sperre neu rendern.
  const hasOtherActiveEditors = useCallback(
    () => Object.values(lockStore.get()).some((holder) => holder.user_id !== selfUserIdRef.current),
    [lockStore]
  );

  const otherPresence = useMemo(
    () => presence.filter((entry) => entry.user_id !== selfUserId),
    [presence, selfUserId]
  );
  // Ort der anderen Personen: je Person der zuletzt gemeldete Ort (mehrere Tabs: einer davon)
  const otherFocus = useMemo(() => {
    const byUser: Record<string, PresenceFocus> = {};
    for (const entry of Object.values(focusByConnection)) {
      if (entry.user_id === selfUserId) continue;
      byUser[entry.user_id] = entry;
    }
    return byUser;
  }, [focusByConnection, selfUserId]);

  const fieldLocks = useMemo<CollabFieldLocks>(
    () => ({ lockField, unlockField, isLockedByOther, subscribeLocks: lockStore.subscribe, getLocks: lockStore.get }),
    [lockField, unlockField, isLockedByOther, lockStore]
  );

  // Ändert sich nur bei Verbindung, Bearbeitungsrecht und Anwesenheit (selten), nie bei Sperren.
  // Die Punkte des Editors bekommen ``fieldLocks`` (stabil) statt dieses Objekts.
  return useMemo(
    () => ({
      connected,
      canEdit,
      selfUserId,
      presence,
      otherPresence,
      otherFocus,
      hasOtherActiveEditors,
      fieldLocks,
      lockField,
      unlockField,
      sendFieldUpdate,
      sendStatusChanged,
      sendFocus,
      onFieldUpdate,
      onStatusChanged,
      onListChanged,
      onAgendaChanged,
      isLockedByOther,
      subscribeLocks: lockStore.subscribe,
      getLocks: lockStore.get,
    }),
    [
      connected,
      canEdit,
      selfUserId,
      presence,
      otherPresence,
      otherFocus,
      hasOtherActiveEditors,
      fieldLocks,
      lockField,
      unlockField,
      sendFieldUpdate,
      sendStatusChanged,
      sendFocus,
      onFieldUpdate,
      onStatusChanged,
      onListChanged,
      onAgendaChanged,
      isLockedByOther,
      lockStore,
    ]
  );
}

const emptyLocks = () => EMPTY_LOCKS;
const emptySignature = () => "";

/** Alle fremden Sperren, mit Neu-Rendern bei jeder Änderung (z. B. mobiler Editor). */
export function useFieldLocks(source: Pick<CollabFieldLocks, "subscribeLocks" | "getLocks">): FieldLocks {
  return useSyncExternalStore(source.subscribeLocks, source.getLocks, emptyLocks);
}

/** Block-ID eines Feldschlüssels (`block-<id>` oder `block-<id>-…`, z. B. Matrixzellen). */
function blockIdOfFieldKey(fieldKey: string, blockIds: ReadonlySet<string>): string | null {
  if (!fieldKey.startsWith("block-")) return null;
  const rest = fieldKey.slice(6);
  for (const id of blockIds) {
    if (rest === id || rest.startsWith(`${id}-`)) return id;
  }
  return null;
}

/** Kurzform der fremden Sperren auf den Feldern dieser Blöcke (inkl. Matrixzellen). */
export function fieldLocksSignature(locks: FieldLocks, blockIds: ReadonlySet<string>): string {
  const parts: string[] = [];
  for (const [fieldKey, holder] of Object.entries(locks)) {
    if (blockIdOfFieldKey(fieldKey, blockIds) !== null) parts.push(`${fieldKey}=${holder.user_id}:${holder.display_name}`);
  }
  return parts.sort().join("|");
}

/**
 * Abonniert die Sperren der Felder einiger Blöcke: die Komponente rendert nur neu, wenn sich bei
 * genau diesen Feldern etwas ändert (useSyncExternalStore mit einer Zeichenkette als Snapshot).
 * Den Halter liest sie danach über ``isLockedByOther``.
 */
export function useFieldLocksSignature(source: Pick<CollabFieldLocks, "subscribeLocks" | "getLocks">, blockIds: readonly string[]): string {
  const key = blockIds.join(",");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ids = useMemo(() => new Set(blockIds), [key]);
  const getSnapshot = useCallback(() => fieldLocksSignature(source.getLocks(), ids), [source, ids]);
  return useSyncExternalStore(source.subscribeLocks, getSnapshot, emptySignature);
}
