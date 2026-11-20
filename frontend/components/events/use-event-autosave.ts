"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { EventPatch, EventSummary } from "@/types/api";

/** Text- und Zahlenfelder speichern entprellt: erst nach dieser Tipp-Pause (oder beim Verlassen). */
export const EVENT_TEXT_SAVE_DELAY_MS = 600;

export type EventSaveState = "idle" | "saving" | "saved" | "error";

/** Rückgabe `false` oder eine Exception gelten als «nicht gespeichert». */
export type EventUpdateHandler = (patch: EventPatch) => void | boolean | Promise<void | boolean>;

/**
 * Speichert Änderungen eines Termins der Reihe nach (nie zwei PATCH gleichzeitig, damit keine
 * ältere Anfrage eine neuere überholt). Textfelder werden entprellt gesammelt und beim
 * Verlassen des Feldes, beim Wechsel des Termins, beim Schliessen und vor dem Verlassen der
 * Seite sofort gespeichert. Bis zur Bestätigung zeigt das Formular den lokalen Entwurf.
 */
export function useEventAutosave(eventId: string, onUpdate: EventUpdateHandler) {
  const [draft, setDraft] = useState<Partial<EventSummary>>({});
  const [saveState, setSaveState] = useState<EventSaveState>("idle");
  const pendingRef = useRef<Partial<EventSummary>>({});
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chainRef = useRef<Promise<void>>(Promise.resolve());
  const inFlightRef = useRef(0);
  const mountedRef = useRef(true);
  const onUpdateRef = useRef(onUpdate);
  useLayoutEffect(() => {
    onUpdateRef.current = onUpdate;
  });

  const send = useCallback((patch: EventPatch) => {
    // Ziel jetzt festhalten: der Aufruf gilt dem Termin, zu dem die Änderung gehört.
    const target = onUpdateRef.current;
    inFlightRef.current += 1;
    if (mountedRef.current) setSaveState("saving");
    chainRef.current = chainRef.current.then(async () => {
      let ok = true;
      try {
        ok = (await target(patch)) !== false;
      } catch {
        ok = false;
      }
      inFlightRef.current -= 1;
      if (!mountedRef.current) return;
      setDraft((current) => {
        const next = { ...current };
        let changed = false;
        for (const key of Object.keys(patch) as (keyof EventSummary)[]) {
          if (key in next && next[key] === patch[key]) {
            delete next[key];
            changed = true;
          }
        }
        return changed ? next : current;
      });
      const idle = inFlightRef.current === 0 && Object.keys(pendingRef.current).length === 0;
      if (!ok) setSaveState("error");
      else if (idle) setSaveState((current) => (current === "error" ? current : "saved"));
    });
  }, []);

  const flush = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const patch = pendingRef.current;
    if (Object.keys(patch).length === 0) return;
    pendingRef.current = {};
    send(patch);
  }, [send]);

  /** Für Textfelder: sofort anzeigen, entprellt speichern. */
  const queue = useCallback(
    (patch: Partial<EventSummary>) => {
      setDraft((current) => ({ ...current, ...patch }));
      pendingRef.current = { ...pendingRef.current, ...patch };
      setSaveState("saving");
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(flush, EVENT_TEXT_SAVE_DELAY_MS);
    },
    [flush]
  );

  /** Für Klick-Felder (Checkbox, Datum, Auswahl): offene Texte zuerst, dann sofort speichern. */
  const commit = useCallback(
    (patch: EventPatch) => {
      flush();
      send(patch);
    },
    [flush, send]
  );

  // Termin gewechselt oder Formular geschlossen: Offenes sofort an den bisherigen Termin senden.
  useLayoutEffect(() => {
    mountedRef.current = true;
    return () => {
      flush();
      setDraft({});
    };
  }, [eventId, flush]);

  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    []
  );

  // Seite verlassen/neu laden: offene Eingaben noch abschicken und den Browser nachfragen lassen.
  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      const hasPending = Object.keys(pendingRef.current).length > 0;
      if (!hasPending && inFlightRef.current === 0) return;
      flush();
      event.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [flush]);

  return { draft, saveState, queue, commit, flush };
}
