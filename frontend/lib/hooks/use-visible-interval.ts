"use client";

import { useEffect, useRef } from "react";

// Polling, das in einem Hintergrund-Tab pausiert: Solange document.hidden gilt, laeuft kein
// Timer; wird der Tab wieder sichtbar, wird callback sofort einmal aufgerufen (der Stand ist
// dann vermutlich veraltet) und der Takt neu gestartet. Muster wie in photos-view.tsx und
// lib/maintenance.ts, hier als wiederverwendbarer Hook.
//
// intervalMs = null schaltet das Polling ab (z. B. nur waehrend ein Job laeuft). Der callback
// darf sich bei jedem Render aendern, ohne den Timer neu zu starten.
export function useVisibleInterval(callback: () => void, intervalMs: number | null): void {
  const callbackRef = useRef(callback);
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (intervalMs === null) return;
    let timer: ReturnType<typeof setInterval> | undefined;

    const start = () => {
      if (timer === undefined) timer = setInterval(() => callbackRef.current(), intervalMs);
    };
    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
    };
    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
      } else if (timer === undefined) {
        callbackRef.current();
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [intervalMs]);
}
