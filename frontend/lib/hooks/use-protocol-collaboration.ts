"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { browserApiBaseUrl } from "@/lib/api/client";

export type CollaboratorInfo = {
  user_id: number;
  display_name: string;
};

export type FieldUpdateEvent = {
  field_key: string;
  patch: unknown;
  user_id: number;
  display_name: string;
};

type StatusChangedEvent = {
  status: string;
  user_id: number;
  display_name: string;
};

const HEARTBEAT_INTERVAL_MS = 20_000;
const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 15_000;

function wsUrlForProtocol(protocolId: number): string {
  return `${browserApiBaseUrl.replace(/^http/, "ws")}/api/ws/protocols/${protocolId}`;
}

/**
 * Live collaboration channel for one protocol: presence, per-block/per-cell field locks,
 * and broadcast of "this changed" events. Value persistence itself still goes through the
 * normal REST autosave endpoints - this hook only carries the collaboration layer on top,
 * so it can fail/reconnect without affecting the ability to save.
 */
export function useProtocolCollaboration(protocolId: number | null | undefined) {
  const [connected, setConnected] = useState(false);
  const [canEdit, setCanEdit] = useState(true);
  const [selfUserId, setSelfUserId] = useState<number | null>(null);
  const [presence, setPresence] = useState<CollaboratorInfo[]>([]);
  const [locks, setLocks] = useState<Record<string, CollaboratorInfo>>({});

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_BASE_DELAY_MS);
  const heartbeatTimerRef = useRef<number | null>(null);
  const ownLocksRef = useRef<Set<string>>(new Set());
  // Mirrors selfUserId for the onmessage closure, which is created once per connection and
  // would otherwise only ever see the selfUserId value from the render that opened the socket.
  const selfUserIdRef = useRef<number | null>(null);
  const fieldUpdateListenersRef = useRef<Set<(event: FieldUpdateEvent) => void>>(new Set());
  const statusChangedListenersRef = useRef<Set<(event: StatusChangedEvent) => void>>(new Set());
  const closedByEffectRef = useRef(false);

  const send = useCallback((message: Record<string, unknown>) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }, []);

  useEffect(() => {
    if (!protocolId) return;
    closedByEffectRef.current = false;

    function scheduleReconnect() {
      if (closedByEffectRef.current) return;
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = window.setTimeout(connect, reconnectDelayRef.current);
      reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, RECONNECT_MAX_DELAY_MS);
    }

    function connect() {
      if (closedByEffectRef.current || !protocolId) return;
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
            selfUserIdRef.current = message.self?.user_id ?? null;
            setSelfUserId(message.self?.user_id ?? null);
            setCanEdit(message.self?.can_edit !== false);
            const presenceList = Array.isArray(message.presence) ? (message.presence as CollaboratorInfo[]) : [];
            setPresence(presenceList);
            setLocks((message.locks as Record<string, CollaboratorInfo>) ?? {});
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
            setLocks((current) => ({ ...current, [message.field_key]: holder }));
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
          default:
            break;
        }
      };
    }

    connect();

    return () => {
      closedByEffectRef.current = true;
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      if (heartbeatTimerRef.current) window.clearInterval(heartbeatTimerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      ownLocksRef.current.clear();
      setConnected(false);
      setPresence([]);
      setLocks({});
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
      if (current[fieldKey].user_id !== selfUserId) return current;
      const next = { ...current };
      delete next[fieldKey];
      return next;
    });
  }, [send, selfUserId]);

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

  const isLockedByOther = useCallback((fieldKey: string): CollaboratorInfo | null => {
    const holder = locks[fieldKey];
    if (!holder || holder.user_id === selfUserId) return null;
    return holder;
  }, [locks, selfUserId]);

  const hasOtherActiveEditors = useMemo(
    () => Object.values(locks).some((holder) => holder.user_id !== selfUserId),
    [locks, selfUserId]
  );

  const otherPresence = useMemo(
    () => presence.filter((entry) => entry.user_id !== selfUserId),
    [presence, selfUserId]
  );

  return {
    connected,
    canEdit,
    selfUserId,
    presence,
    otherPresence,
    locks,
    hasOtherActiveEditors,
    lockField,
    unlockField,
    sendFieldUpdate,
    sendStatusChanged,
    onFieldUpdate,
    onStatusChanged,
    isLockedByOther,
  };
}
